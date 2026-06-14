from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    ClaimOrder,
    EvidenceRequestTask,
    Restaurant,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberStoreMapping,
)


def create_misclassified_history(db_session: Session) -> tuple[Restaurant, Restaurant, ClaimOrder, EvidenceRequestTask]:
    krousty = Restaurant(name="Krousty Bat", sender_email="krousty@example.com")
    asian = Restaurant(name="Asian Passion", sender_email="asian@example.com")
    db_session.add_all([krousty, asian])
    db_session.flush()
    db_session.add(
        UberStoreMapping(
            restaurant_id=asian.id,
            uber_store_id="store-asian",
            uber_store_name="Asian Passion",
            active=True,
        )
    )
    snapshot = UberOrderSnapshot(
        restaurant_id=krousty.id,
        uber_store_id="store-asian",
        uber_order_id="UBER-HIST-ASIAN-001",
        display_id="ASIAN-001",
        current_state="canceled",
        order_total_amount=Decimal("29.90"),
        currency="EUR",
        raw_payload_json={
            "restaurant_id": krousty.id,
            "uber_store_id": "store-asian",
            "uber_store_name": "Asian Passion",
            "uber_order_id": "UBER-HIST-ASIAN-001",
        },
        imported_from="manager_export",
    )
    transaction = UberFinancialTransaction(
        restaurant_id=krousty.id,
        uber_store_id="store-asian",
        uber_order_id="UBER-HIST-ASIAN-001",
        transaction_type="customer_refund",
        amount=Decimal("-8.50"),
        currency="EUR",
        transaction_date=date(2026, 6, 1),
        payout_reference="PAY-HIST-001",
        raw_payload_json={
            "restaurant_id": krousty.id,
            "uber_store_id": "store-asian",
            "uber_store_name": "Asian Passion",
            "uber_order_id": "UBER-HIST-ASIAN-001",
        },
        imported_from="manager_export",
    )
    order = ClaimOrder(
        restaurant_id=krousty.id,
        uber_order_number="UBER-HIST-ASIAN-001",
        order_amount=Decimal("29.90"),
        currency="EUR",
        status="missing_evidence",
    )
    db_session.add_all([snapshot, transaction, order])
    db_session.flush()
    dispute = UberCustomerRefundDispute(
        restaurant_id=krousty.id,
        uber_store_id="store-asian",
        uber_order_id="UBER-HIST-ASIAN-001",
        claim_order_id=order.id,
        financial_transaction_id=transaction.id,
        dispute_type="customer_refund",
        reason="unknown_reason",
        status="needs_evidence",
        customer_refund_amount=Decimal("8.50"),
        currency="EUR",
        evidence_required=True,
        evidence_status="missing",
        raw_payload_json={"restaurant_id": krousty.id, "uber_store_name": "Asian Passion"},
    )
    db_session.add(dispute)
    db_session.flush()
    task = EvidenceRequestTask(
        order_id=order.id,
        customer_refund_dispute_id=dispute.id,
        restaurant_id=krousty.id,
        task_type="missing_receipt",
        required_evidence_type="receipt",
        status="pending",
        priority="urgent",
        title="Ticket",
        reason="customer_refund_dispute",
    )
    db_session.add(task)
    db_session.commit()
    return krousty, asian, order, task


def test_historical_reclassification_preview_detects_wrong_restaurant(
    client: TestClient,
    db_session: Session,
) -> None:
    _krousty, asian, _order, _task = create_misclassified_history(db_session)

    response = client.post("/v1/uber/historical-reclassification/preview", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "preview"
    assert payload["total_candidates"] == 2
    assert payload["eligible_count"] == 2
    assert {candidate["target_restaurant_id"] for candidate in payload["candidates"]} == {asian.id}
    assert {candidate["entity_type"] for candidate in payload["candidates"]} == {
        "uber_order_snapshot",
        "uber_financial_transaction",
    }


def test_historical_reclassification_apply_moves_history_and_related_records(
    client: TestClient,
    db_session: Session,
) -> None:
    _krousty, asian, order, task = create_misclassified_history(db_session)

    response = client.post("/v1/uber/historical-reclassification/apply", json={"confirm": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "applied"
    assert payload["moved_count"] == 2
    snapshot = db_session.scalar(select(UberOrderSnapshot).where(UberOrderSnapshot.uber_order_id == "UBER-HIST-ASIAN-001"))
    transaction = db_session.scalar(
        select(UberFinancialTransaction).where(UberFinancialTransaction.uber_order_id == "UBER-HIST-ASIAN-001")
    )
    dispute = db_session.scalar(select(UberCustomerRefundDispute).where(UberCustomerRefundDispute.uber_order_id == "UBER-HIST-ASIAN-001"))
    db_session.refresh(order)
    db_session.refresh(task)
    assert snapshot is not None
    assert transaction is not None
    assert dispute is not None
    assert snapshot.restaurant_id == asian.id
    assert transaction.restaurant_id == asian.id
    assert dispute.restaurant_id == asian.id
    assert order.restaurant_id == asian.id
    assert task.restaurant_id == asian.id
    audit_actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "historical_restaurant_reclassification.apply" in audit_actions
    assert "historical_restaurant_reclassification.move" in audit_actions


def test_historical_reclassification_apply_requires_confirm(client: TestClient, db_session: Session) -> None:
    create_misclassified_history(db_session)

    response = client.post("/v1/uber/historical-reclassification/apply", json={"confirm": False})

    assert response.status_code == 422


def test_historical_reclassification_owner_only(client: TestClient, db_session: Session) -> None:
    create_misclassified_history(db_session)
    manager = client.post(
        "/v1/users",
        json={
            "email": "manager-reclass@example.com",
            "password": "manager-password",
            "full_name": "Manager Reclass",
            "role": "manager",
            "active": True,
        },
    ).json()
    login_response = client.post("/v1/auth/login", json={"email": manager["email"], "password": "manager-password"})
    token = login_response.json()["access_token"]

    response = client.post(
        "/v1/uber/historical-reclassification/preview",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
