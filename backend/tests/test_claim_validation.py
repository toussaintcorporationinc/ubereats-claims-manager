from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, ClaimOrder


def create_restaurant(client: TestClient, name: str = "Restaurant Validation") -> dict:
    response = client.post(
        "/v1/restaurants",
        json={
            "name": name,
            "sender_email": "claims@example.com",
        },
    )
    assert response.status_code == 201
    return response.json()


def order_payload(restaurant_id: int, uber_order_number: str = "UBER-VALIDATE-1", amount: str = "18.90") -> dict:
    return {
        "restaurant_id": restaurant_id,
        "uber_order_number": uber_order_number,
        "order_amount": amount,
        "currency": "EUR",
        "accepted_by_restaurant": True,
        "prepared_before_cancellation": True,
    }


def create_order(
    client: TestClient,
    restaurant_id: int,
    uber_order_number: str = "UBER-VALIDATE-1",
    amount: str = "18.90",
) -> dict:
    response = client.post("/v1/orders", json=order_payload(restaurant_id, uber_order_number, amount))
    assert response.status_code == 201
    return response.json()


def add_evidence(client: TestClient, order_id: int, evidence_type: str) -> dict:
    response = client.post(
        f"/v1/orders/{order_id}/evidence",
        json={
            "evidence_type": evidence_type,
            "original_filename": f"{evidence_type}.png",
            "storage_path": f"storage/evidence/{evidence_type}.png",
            "mime_type": "image/png",
            "file_size": 2048,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_incomplete_order_without_amount(db_session: Session, restaurant_id: int) -> ClaimOrder:
    order = ClaimOrder(
        restaurant_id=restaurant_id,
        uber_order_number="UBER-MISSING-AMOUNT",
        order_amount=None,
        currency="EUR",
        status="draft",
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


def get_validation_audit_log(db_session: Session, order_id: int) -> AuditLog | None:
    return db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "claim_order",
            AuditLog.entity_id == order_id,
            AuditLog.action == "validate_claim_order",
        )
    )


def test_complete_claim_order_becomes_ready_to_send(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    add_evidence(client, order["id"], "receipt")

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "order_id": order["id"],
        "is_complete": True,
        "previous_status": "draft",
        "new_status": "ready_to_send",
        "missing_items": [],
        "blocking_reasons": [],
    }


def test_claim_order_without_unified_order_proof_becomes_missing_evidence(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["is_complete"] is False
    assert data["previous_status"] == "draft"
    assert data["new_status"] == "missing_evidence"
    assert "receipt" in data["missing_items"]
    assert "missing_unified_order_proof" in data["blocking_reasons"]


def test_legacy_cancellation_and_preparation_set_still_valid(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    add_evidence(client, order["id"], "cancellation_proof")
    add_evidence(client, order["id"], "preparation_proof")

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["is_complete"] is True
    assert data["new_status"] == "ready_to_send"


def test_claim_order_without_order_amount_becomes_missing_evidence(
    client: TestClient,
    db_session: Session,
) -> None:
    restaurant = create_restaurant(client)
    order = create_incomplete_order_without_amount(db_session, restaurant["id"])
    add_evidence(client, order.id, "receipt")

    response = client.post(f"/v1/orders/{order.id}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["is_complete"] is False
    assert data["new_status"] == "missing_evidence"
    assert "order_amount" in data["missing_items"]
    assert "missing_order_amount" in data["blocking_reasons"]


def test_order_creation_without_uber_order_number_is_rejected(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    payload = order_payload(restaurant["id"])
    payload.pop("uber_order_number")

    response = client.post("/v1/orders", json=payload)

    assert response.status_code == 422


def test_accepted_claim_order_cannot_be_revalidated(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    patch_response = client.patch(f"/v1/orders/{order['id']}", json={"status": "accepted"})
    assert patch_response.status_code == 200

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 409
    data = response.json()
    assert data["previous_status"] == "accepted"
    assert data["new_status"] == "accepted"
    assert data["blocking_reasons"] == ["final_status_cannot_be_validated"]
    assert client.get(f"/v1/orders/{order['id']}").json()["status"] == "accepted"


def test_payment_confirmed_claim_order_cannot_be_revalidated(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    patch_response = client.patch(f"/v1/orders/{order['id']}", json={"status": "payment_confirmed"})
    assert patch_response.status_code == 200

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 409
    data = response.json()
    assert data["previous_status"] == "payment_confirmed"
    assert data["new_status"] == "payment_confirmed"
    assert data["blocking_reasons"] == ["final_status_cannot_be_validated"]
    assert client.get(f"/v1/orders/{order['id']}").json()["status"] == "payment_confirmed"


def test_audit_log_created_after_complete_validation(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])
    add_evidence(client, order["id"], "receipt")

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    audit_log = get_validation_audit_log(db_session, order["id"])
    assert audit_log is not None
    assert '"status": "ready_to_send"' in (audit_log.new_value or "")


def test_audit_log_created_after_incomplete_validation(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    audit_log = get_validation_audit_log(db_session, order["id"])
    assert audit_log is not None
    assert '"status": "missing_evidence"' in (audit_log.new_value or "")


def test_validation_response_contains_missing_items_and_blocking_reasons(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["missing_items"] == ["receipt"]
    assert data["blocking_reasons"] == ["missing_unified_order_proof"]


def test_validation_response_returns_previous_and_new_status(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    response = client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["previous_status"] == "draft"
    assert data["new_status"] == "missing_evidence"

