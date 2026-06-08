from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, ClaimOrder, EmailAccount, InboundEmailMessage, User
from app.models.domain import utc_now


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_user(db_session: Session, email: str) -> User:
    user = db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def create_restaurant(client: TestClient, name: str = "Review Restaurant") -> dict:
    response = client.post("/v1/restaurants", json={"name": name, "sender_email": "claims@example.com"})
    assert response.status_code == 201
    return response.json()


def create_user(client: TestClient, email: str, role: str) -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "user-password",
            "full_name": f"{role.title()} Test",
            "role": role,
            "active": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def assign_restaurant(client: TestClient, user_id: int, restaurant_id: int) -> None:
    response = client.post(f"/v1/users/{user_id}/restaurants", json={"restaurant_id": restaurant_id})
    assert response.status_code == 201


def login(client: TestClient, email: str, password: str = "user-password") -> str:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def create_order(client: TestClient, restaurant_id: int, order_number: str, status: str = "response_received") -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
            "status": status,
        },
    )
    assert response.status_code == 201
    return response.json()


def connect_email_account(db_session: Session, user_id: int, email_address: str = "reviewer@example.com") -> EmailAccount:
    account = EmailAccount(
        user_id=user_id,
        provider="gmail",
        email_address=email_address,
        access_token_encrypted="encrypted-access-token",
        refresh_token_encrypted="encrypted-refresh-token",
        scopes="https://www.googleapis.com/auth/gmail.readonly",
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def create_inbound_message(
    db_session: Session,
    account: EmailAccount,
    order_id: int | None,
    message_id: str = "review-message-1",
) -> InboundEmailMessage:
    inbound_message = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order_id,
        provider="gmail",
        provider_message_id=message_id,
        provider_thread_id=f"thread-{message_id}",
        from_email="support@uber.com",
        to_email=account.email_address,
        subject="Reponse Uber Eats",
        snippet="Uber confirme le traitement.",
        body_text="Uber confirme le traitement manuel.",
        received_at=utc_now(),
        raw_headers_json={"from": "support@uber.com"},
        match_status="linked" if order_id else "unlinked",
        match_reason="thread_id_match" if order_id else "no_match",
    )
    db_session.add(inbound_message)
    db_session.commit()
    db_session.refresh(inbound_message)
    return inbound_message


def post_review(
    client: TestClient,
    order_id: int,
    review_type: str,
    *,
    token: str | None = None,
    inbound_message_id: int | None = None,
    recovered_amount: str | None = None,
):
    payload: dict[str, object] = {
        "review_type": review_type,
        "notes": f"Manual review {review_type}",
    }
    if inbound_message_id is not None:
        payload["inbound_message_id"] = inbound_message_id
    if recovered_amount is not None:
        payload["recovered_amount"] = recovered_amount
    return client.post(
        f"/v1/orders/{order_id}/response-reviews",
        json=payload,
        headers=auth_headers(token) if token else None,
    )


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_owner_can_create_review_accepted(client: TestClient, db_session: Session) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_email_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-OWNER")
    inbound_message = create_inbound_message(db_session, account, order_data["id"])

    response = post_review(
        client,
        order_data["id"],
        "accepted",
        inbound_message_id=inbound_message.id,
        recovered_amount="24.90",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["review_type"] == "accepted"
    assert data["previous_order_status"] == "response_received"
    assert data["new_order_status"] == "accepted"
    assert data["order_status"] == "accepted"

    order = db_session.get(ClaimOrder, order_data["id"])
    assert order is not None
    assert order.status == "accepted"
    assert order.result == "accepted"
    assert str(order.recovered_amount) == "24.90"
    db_session.refresh(inbound_message)
    assert inbound_message.review_status == "reviewed"
    assert inbound_message.reviewed_by_user_id == owner.id


def test_manager_assigned_can_create_review_accepted(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-MANAGER")
    manager = create_user(client, "manager-review@example.com", "manager")
    assign_restaurant(client, manager["id"], restaurant["id"])
    manager_token = login(client, manager["email"])

    response = post_review(client, order_data["id"], "accepted", token=manager_token)

    assert response.status_code == 201
    assert response.json()["order_status"] == "accepted"


def test_manager_non_assigned_cannot_create_review(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-MANAGER-BLOCKED")
    manager = create_user(client, "manager-review-blocked@example.com", "manager")
    manager_token = login(client, manager["email"])

    response = post_review(client, order_data["id"], "accepted", token=manager_token)

    assert response.status_code == 403


def test_staff_cannot_create_review(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-STAFF")
    staff = create_user(client, "staff-review@example.com", "staff")
    assign_restaurant(client, staff["id"], restaurant["id"])
    staff_token = login(client, staff["email"])

    response = post_review(client, order_data["id"], "accepted", token=staff_token)

    assert response.status_code == 403


def test_review_transitions_update_order_status(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    expectations = {
        "accepted": "accepted",
        "payment_to_verify": "payment_to_verify",
        "payment_confirmed": "payment_confirmed",
        "refused": "refused",
        "evidence_requested": "manual_review",
        "information_requested": "manual_review",
        "followup_needed": "manual_review",
        "manual_review": "manual_review",
    }

    for review_type, expected_status in expectations.items():
        order_data = create_order(client, restaurant["id"], f"UBER-REVIEW-{review_type}")
        response = post_review(client, order_data["id"], review_type, recovered_amount="12.50")

        assert response.status_code == 201
        assert response.json()["order_status"] == expected_status
        order = db_session.get(ClaimOrder, order_data["id"])
        assert order is not None
        assert order.status == expected_status
        assert order.result == review_type


def test_review_ignored_does_not_change_order_status(client: TestClient, db_session: Session) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_email_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-IGNORED", status="waiting_uber_response")
    inbound_message = create_inbound_message(db_session, account, order_data["id"], "ignored-message")

    response = post_review(client, order_data["id"], "ignored", inbound_message_id=inbound_message.id)

    assert response.status_code == 201
    assert response.json()["order_status"] == "waiting_uber_response"
    order = db_session.get(ClaimOrder, order_data["id"])
    assert order is not None
    assert order.status == "waiting_uber_response"
    assert order.result is None
    db_session.refresh(inbound_message)
    assert inbound_message.review_status == "ignored"


def test_review_with_inbound_message_links_unlinked_message(client: TestClient, db_session: Session) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_email_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-LINK-FIRST")
    inbound_message = create_inbound_message(db_session, account, None, "unlinked-message")

    response = post_review(client, order_data["id"], "manual_review", inbound_message_id=inbound_message.id)

    assert response.status_code == 201
    db_session.refresh(inbound_message)
    assert inbound_message.order_id == order_data["id"]
    assert inbound_message.match_status == "linked"
    assert inbound_message.review_status == "reviewed"


def test_review_creates_audit_log(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-AUDIT")

    response = post_review(client, order_data["id"], "refused")

    assert response.status_code == 201
    review_id = response.json()["id"]
    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "claim_response_review",
            AuditLog.entity_id == review_id,
            AuditLog.action == "response_review_created",
        )
    )
    assert audit_log is not None


def test_order_response_reviews_list_returns_reviews(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-LIST")
    assert post_review(client, order_data["id"], "accepted").status_code == 201

    response = client.get(f"/v1/orders/{order_data['id']}/response-reviews")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["review_type"] == "accepted"


def test_dashboard_summary_includes_response_review_counters(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    accepted_order = create_order(client, restaurant["id"], "UBER-REVIEW-DASH-ACCEPTED")
    refused_order = create_order(client, restaurant["id"], "UBER-REVIEW-DASH-REFUSED")
    manual_order = create_order(client, restaurant["id"], "UBER-REVIEW-DASH-MANUAL")
    assert post_review(client, accepted_order["id"], "accepted", recovered_amount="10.00").status_code == 201
    assert post_review(client, refused_order["id"], "refused").status_code == 201
    assert post_review(client, manual_order["id"], "manual_review").status_code == 201

    response = client.get("/v1/dashboard/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["accepted_count"] >= 1
    assert data["refused_count"] >= 1
    assert data["manual_review_count"] >= 1
    assert "payment_to_verify_count" in data
    assert "payment_confirmed_count" in data
    assert "pending_response_count" in data


def test_payment_confirmed_refuses_dangerous_change(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-PROTECTED-PAYMENT", status="payment_confirmed")

    response = post_review(client, order_data["id"], "refused")

    assert response.status_code == 409


def test_closed_refuses_dangerous_change(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order_data = create_order(client, restaurant["id"], "UBER-REVIEW-PROTECTED-CLOSED", status="closed")

    response = post_review(client, order_data["id"], "accepted")

    assert response.status_code == 409
