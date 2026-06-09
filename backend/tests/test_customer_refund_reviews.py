from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    ClaimOrder,
    CustomerRefundDisputeReview,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    User,
)
from app.models.domain import utc_now


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_restaurant(client: TestClient, name: str = "Refund Review Restaurant") -> dict:
    response = client.post("/v1/restaurants", json={"name": name, "sender_email": "claims@example.com"})
    assert response.status_code == 201
    return response.json()


def create_user(client: TestClient, email: str, role: str) -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "user-password",
            "full_name": f"{role.title()} Review",
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


def create_order(client: TestClient, restaurant_id: int, order_number: str = "UBER-REFUND-REVIEW") -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
            "loss_type": "customer_refund_dispute",
            "status": "sent",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_dispute(
    db_session: Session,
    restaurant_id: int,
    *,
    claim_order_id: int | None = None,
    status: str = "sent",
    evidence_status: str = "complete",
    amount: str = "24.90",
    dispute_type: str = "customer_refund",
) -> UberCustomerRefundDispute:
    dispute = UberCustomerRefundDispute(
        restaurant_id=restaurant_id,
        uber_store_id="store-review",
        uber_order_id="UBER-REFUND-REVIEW",
        display_id="UBER-REFUND-REVIEW",
        claim_order_id=claim_order_id,
        customer_refund_reference="REFUND-REVIEW",
        dispute_type=dispute_type,
        reason="refund_without_sufficient_proof",
        status=status,
        customer_refund_amount=amount,
        order_amount=amount,
        currency="EUR",
        deducted_at=utc_now().date(),
        order_date=utc_now().date(),
        evidence_required=True,
        evidence_status=evidence_status,
        raw_payload_json={"source": "test"},
    )
    db_session.add(dispute)
    db_session.commit()
    db_session.refresh(dispute)
    return dispute


def post_review(
    client: TestClient,
    dispute_id: int,
    review_type: str,
    *,
    token: str | None = None,
    recovered_amount: str | None = None,
):
    payload: dict[str, object] = {"review_type": review_type, "notes": f"Decision {review_type}"}
    if recovered_amount is not None:
        payload["recovered_amount"] = recovered_amount
    return client.post(
        f"/v1/customer-refunds/{dispute_id}/reviews",
        json=payload,
        headers=auth_headers(token) if token else None,
    )


def test_health_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200


def test_owner_can_create_customer_refund_review_accepted(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    dispute = create_dispute(db_session, restaurant["id"], claim_order_id=order["id"])

    response = post_review(client, dispute.id, "accepted", recovered_amount="24.90")

    assert response.status_code == 201
    data = response.json()
    assert data["dispute_status"] == "accepted"
    assert data["claim_order_status"] == "accepted"
    db_session.refresh(dispute)
    assert dispute.status == "accepted"
    assert str(dispute.recovered_amount) == "24.90"
    claim_order = db_session.get(ClaimOrder, order["id"])
    assert claim_order is not None
    assert claim_order.status == "accepted"


def test_manager_assigned_can_create_review(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    dispute = create_dispute(db_session, restaurant["id"])
    manager = create_user(client, "manager-refund-review@example.com", "manager")
    assign_restaurant(client, manager["id"], restaurant["id"])
    token = login(client, manager["email"])

    response = post_review(client, dispute.id, "manual_review", token=token)

    assert response.status_code == 201
    assert response.json()["dispute_status"] == "manual_review"


def test_manager_non_assigned_and_staff_are_refused(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    other = create_restaurant(client, "Other Refund Review Restaurant")
    dispute = create_dispute(db_session, restaurant["id"])
    manager = create_user(client, "manager-refund-review-denied@example.com", "manager")
    assign_restaurant(client, manager["id"], other["id"])
    staff = create_user(client, "staff-refund-review@example.com", "staff")
    assign_restaurant(client, staff["id"], restaurant["id"])

    manager_response = post_review(client, dispute.id, "accepted", token=login(client, manager["email"]))
    staff_response = post_review(client, dispute.id, "accepted", token=login(client, staff["email"]))

    assert manager_response.status_code == 403
    assert staff_response.status_code == 403


def test_review_transitions_update_dispute_and_linked_order(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    transitions = {
        "payment_to_verify": "payment_to_verify",
        "payment_confirmed": "payment_confirmed",
        "refused": "refused",
        "information_requested": "manual_review",
        "followup_needed": "manual_review",
        "manual_review": "manual_review",
    }

    for review_type, expected_status in transitions.items():
        order = create_order(client, restaurant["id"], f"UBER-REFUND-{review_type}")
        dispute = create_dispute(db_session, restaurant["id"], claim_order_id=order["id"])
        response = post_review(client, dispute.id, review_type, recovered_amount="12.50")

        assert response.status_code == 201
        db_session.refresh(dispute)
        assert dispute.status == expected_status
        claim_order = db_session.get(ClaimOrder, order["id"])
        assert claim_order is not None
        assert claim_order.status == expected_status


def test_evidence_requested_recalculates_tasks(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    dispute = create_dispute(
        db_session,
        restaurant["id"],
        claim_order_id=order["id"],
        evidence_status="missing",
        dispute_type="order_not_received",
    )

    response = post_review(client, dispute.id, "evidence_requested")

    assert response.status_code == 201
    db_session.refresh(dispute)
    assert dispute.status == "needs_evidence"
    tasks = db_session.scalars(select(EvidenceRequestTask).where(EvidenceRequestTask.customer_refund_dispute_id == dispute.id)).all()
    assert {task.required_evidence_type for task in tasks} >= {"receipt", "delivery_proof"}


def test_ignored_and_payment_confirmed_are_protected(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    ignored = create_dispute(db_session, restaurant["id"], status="sent")
    ignored_response = post_review(client, ignored.id, "ignored")
    assert ignored_response.status_code == 201

    blocked_ignored = post_review(client, ignored.id, "accepted")
    confirmed = create_dispute(db_session, restaurant["id"], status="payment_confirmed")
    blocked_confirmed = post_review(client, confirmed.id, "refused")

    assert blocked_ignored.status_code == 409
    assert blocked_confirmed.status_code == 409


def test_review_history_and_audit_log_created(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    dispute = create_dispute(db_session, restaurant["id"])

    response = post_review(client, dispute.id, "refused")
    assert response.status_code == 201
    review_id = response.json()["review"]["id"]

    history = client.get(f"/v1/customer-refunds/{dispute.id}/reviews")
    assert history.status_code == 200
    assert history.json()[0]["review_type"] == "refused"
    assert db_session.get(CustomerRefundDisputeReview, review_id) is not None
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "customer_refund_dispute_review",
            AuditLog.entity_id == review_id,
            AuditLog.action == "customer_refund_dispute.review_created",
        )
    )
    assert audit is not None


def test_global_customer_refund_reviews_list(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    dispute = create_dispute(db_session, restaurant["id"])
    assert post_review(client, dispute.id, "accepted").status_code == 201

    response = client.get("/v1/customer-refund-reviews")

    assert response.status_code == 200
    assert response.json()["reviews"][0]["review_type"] == "accepted"


def test_payment_confirmed_updates_recovered_amount(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    dispute = create_dispute(db_session, restaurant["id"])

    response = post_review(client, dispute.id, "payment_confirmed", recovered_amount="18.75")

    assert response.status_code == 201
    db_session.refresh(dispute)
    assert dispute.status == "payment_confirmed"
    assert str(dispute.recovered_amount) == "18.75"
    assert dispute.last_reviewed_at is not None
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    assert dispute.last_reviewed_by_user_id == owner.id
