from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AuditLog,
    CustomerRefundEvidenceRequirement,
    EmailDraft,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
)
from app.models.domain import utc_now
from app.services.customer_refund_detection_service import classify_transaction


@pytest.fixture()
def evidence_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    storage_dir = tmp_path / "evidence"
    monkeypatch.setenv("EVIDENCE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("MAX_EVIDENCE_FILE_SIZE_MB", "1")
    get_settings.cache_clear()
    yield storage_dir
    get_settings.cache_clear()


@pytest.fixture()
def configured_client(evidence_storage: Path, client: TestClient) -> TestClient:
    return client


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_restaurant(client: TestClient, name: str = "Customer Refund Restaurant") -> dict:
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


def create_order(client: TestClient, restaurant_id: int, order_number: str = "UBER-REFUND-1") -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
            "loss_type": "deduction Uber",
        },
    )
    assert response.status_code == 201
    return response.json()


def add_transaction(
    db_session: Session,
    restaurant_id: int,
    *,
    transaction_type: str = "refund",
    amount: str = "-12.50",
    order_id: str = "UBER-REFUND-1",
    payload: dict | None = None,
) -> UberFinancialTransaction:
    transaction = UberFinancialTransaction(
        restaurant_id=restaurant_id,
        uber_store_id="store-refund",
        uber_order_id=order_id,
        transaction_type=transaction_type,
        amount=amount,
        currency="EUR",
        transaction_date=utc_now().date(),
        payout_reference="PAYOUT-TEST",
        raw_payload_json=payload or {"description": transaction_type},
        imported_from="api_reporting",
    )
    db_session.add(transaction)
    db_session.commit()
    return transaction


def add_snapshot(
    db_session: Session,
    restaurant_id: int,
    order_id: str = "UBER-REFUND-1",
    *,
    customer_name: str | None = None,
) -> UberOrderSnapshot:
    snapshot = UberOrderSnapshot(
        restaurant_id=restaurant_id,
        uber_store_id="store-refund",
        uber_order_id=order_id,
        display_id=order_id,
        customer_name=customer_name,
        current_state="completed",
        placed_at=utc_now(),
        order_total_amount="24.90",
        currency="EUR",
        raw_payload_json={"source": "test"},
        imported_from="api_reporting",
    )
    db_session.add(snapshot)
    db_session.commit()
    return snapshot


def detect(client: TestClient, restaurant_id: int | None = None, token: str | None = None):
    payload = {"restaurant_id": restaurant_id} if restaurant_id else {}
    return client.post("/v1/customer-refunds/detect", json=payload, headers=auth_headers(token) if token else None)


def test_health_works(configured_client: TestClient) -> None:
    response = configured_client.get("/health")

    assert response.status_code == 200


def test_owner_can_detect_customer_refund(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"], transaction_type="refund", amount="-18.40")

    response = detect(configured_client)

    assert response.status_code == 200
    assert response.json()["detected_count"] == 1
    dispute = db_session.scalar(select(UberCustomerRefundDispute))
    assert dispute is not None
    assert dispute.dispute_type == "customer_refund"
    assert str(dispute.customer_refund_amount) == "18.40"


def test_manager_assigned_can_detect_for_restaurant(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"])
    manager = create_user(configured_client, "manager-refund@example.com", "manager")
    assign_restaurant(configured_client, manager["id"], restaurant["id"])
    manager_token = login(configured_client, manager["email"])

    response = detect(configured_client, restaurant["id"], manager_token)

    assert response.status_code == 200
    assert response.json()["detected_count"] == 1


def test_manager_non_assigned_is_refused(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    other = create_restaurant(configured_client, "Other Refund Restaurant")
    add_transaction(db_session, restaurant["id"])
    manager = create_user(configured_client, "manager-refund-denied@example.com", "manager")
    assign_restaurant(configured_client, manager["id"], other["id"])
    manager_token = login(configured_client, manager["email"])

    response = detect(configured_client, restaurant["id"], manager_token)

    assert response.status_code == 403


def test_staff_cannot_detect(configured_client: TestClient) -> None:
    staff = create_user(configured_client, "staff-refund@example.com", "staff")
    staff_token = login(configured_client, staff["email"])

    response = configured_client.post("/v1/customer-refunds/detect", json={}, headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_not_received_and_missing_item_classification(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"], order_id="UBER-NOT-RECEIVED", payload={"reason": "Commande non recue"})
    add_transaction(db_session, restaurant["id"], order_id="UBER-MISSING", payload={"reason": "article manquant"})

    response = detect(configured_client)

    assert response.status_code == 200
    disputes = db_session.scalars(select(UberCustomerRefundDispute)).all()
    assert {dispute.dispute_type for dispute in disputes} == {"order_not_received", "missing_item"}


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("Commande non recue", "order_not_received"),
        ("Commande non reçue", "order_not_received"),
        ("Order not received", "order_not_received"),
        ("Article manquant", "missing_item"),
        ("missing item", "missing_item"),
        ("mauvaise commande", "incorrect_item"),
        ("problème qualité", "quality_issue"),
        ("ajustement negatif erreur de commande", "order_error_adjustment"),
    ],
)
def test_customer_refund_classification_variants(text: str, expected_type: str) -> None:
    transaction = UberFinancialTransaction(
        restaurant_id=1,
        uber_store_id="store-refund",
        uber_order_id="UBER-CLASSIFICATION",
        transaction_type="refund",
        amount="-12.50",
        currency="EUR",
        transaction_date=utc_now().date(),
        raw_payload_json={"description": text, "line_item": text, "notes": text},
        imported_from="api_reporting",
    )

    dispute_type, _reason = classify_transaction(transaction)

    assert dispute_type == expected_type


def test_unknown_customer_refund_classification_stays_manual_review() -> None:
    transaction = UberFinancialTransaction(
        restaurant_id=1,
        uber_store_id="store-refund",
        uber_order_id="UBER-UNKNOWN",
        transaction_type="mystery",
        amount="-12.50",
        currency="EUR",
        transaction_date=utc_now().date(),
        raw_payload_json={"description": "unclear deduction"},
        imported_from="api_reporting",
    )

    dispute_type, reason = classify_transaction(transaction)

    assert dispute_type == "unknown"
    assert reason == "unknown_reason"


def test_unknown_transaction_goes_manual_review(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"], transaction_type="mystery", payload={"description": "unclear deduction"})

    detect(configured_client)

    dispute = db_session.scalar(select(UberCustomerRefundDispute))
    assert dispute is not None
    assert dispute.dispute_type == "unknown"
    assert dispute.status == "manual_review"
    assert dispute.evidence_status == "manual_review"


def test_detect_does_not_duplicate_same_transaction(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"])

    first = detect(configured_client)
    second = detect(configured_client)

    assert first.json()["detected_count"] == 1
    assert second.json()["detected_count"] == 0
    assert len(db_session.scalars(select(UberCustomerRefundDispute)).all()) == 1


def test_positive_order_error_adjustment_is_not_detected_as_deduction(
    configured_client: TestClient,
    db_session: Session,
) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(
        db_session,
        restaurant["id"],
        transaction_type="order_error_adjustment",
        amount="39.98",
        payload={"description": "Ajustement erreur de commande positif"},
    )

    response = detect(configured_client)

    assert response.status_code == 200
    assert response.json()["detected_count"] == 0
    assert response.json()["total_deducted_amount"] == "0"
    assert db_session.scalar(select(UberCustomerRefundDispute)) is None


def test_combined_report_item_adjustment_line_is_not_detected_as_deduction(
    configured_client: TestClient,
    db_session: Session,
) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(
        db_session,
        restaurant["id"],
        transaction_type="order_error_adjustment",
        amount="-24.99",
        payload={
            "row_kind": "transaction",
            "raw_data": {
                "id du flux": "UBER-ITEM-LINE",
                "nom du plat de l article": "Menu test",
                "prix a l unite": "24.99",
                "quantite demandee": "1",
                "ajustements lies a des erreurs de commande hors tva": "-24.99",
            },
            "description": "Ligne article du rapport combine Uber",
        },
    )

    response = detect(configured_client)

    assert response.status_code == 200
    assert response.json()["detected_count"] == 0
    assert response.json()["total_deducted_amount"] == "0"
    assert db_session.scalar(select(UberCustomerRefundDispute)) is None


def test_evidence_requirements_by_type(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"], order_id="UBER-NOT-RECEIVED", payload={"reason": "not received"})
    add_transaction(db_session, restaurant["id"], order_id="UBER-MISSING", payload={"reason": "missing item"})

    detect(configured_client)

    requirements = db_session.scalars(select(CustomerRefundEvidenceRequirement)).all()
    by_dispute = {}
    for requirement in requirements:
        by_dispute.setdefault(requirement.dispute.dispute_type, set()).add(requirement.required_evidence_type)
    assert by_dispute["order_not_received"] == {"receipt"}
    assert by_dispute["missing_item"] == {"receipt"}


def test_create_claim_order_from_dispute(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_snapshot(db_session, restaurant["id"], customer_name="Client Remboursement")
    add_transaction(db_session, restaurant["id"])
    detect(configured_client)
    dispute = db_session.scalar(select(UberCustomerRefundDispute))
    assert dispute is not None

    response = configured_client.post(f"/v1/customer-refunds/{dispute.id}/create-claim-order")

    assert response.status_code == 201
    assert response.json()["uber_order_number"] == "UBER-REFUND-1"
    assert response.json()["customer_name"] == "Client Remboursement"
    second = configured_client.post(f"/v1/customer-refunds/{dispute.id}/create-claim-order")
    assert second.status_code == 409


def test_create_draft_requires_complete_evidence(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_snapshot(db_session, restaurant["id"])
    add_transaction(db_session, restaurant["id"], payload={"reason": "missing item"})
    detect(configured_client)
    dispute = db_session.scalar(select(UberCustomerRefundDispute))
    assert dispute is not None
    order = configured_client.post(f"/v1/customer-refunds/{dispute.id}/create-claim-order").json()

    blocked = configured_client.post(f"/v1/customer-refunds/{dispute.id}/create-draft")
    assert blocked.status_code == 409

    response = configured_client.post(
        f"/v1/orders/{order['id']}/evidence",
        json={
            "evidence_type": "receipt",
            "original_filename": "ticket-agrafe-commande.png",
            "storage_path": "storage/ticket-agrafe-commande.png",
            "mime_type": "image/png",
            "file_size": 100,
        },
    )
    assert response.status_code == 201
    configured_client.post(f"/v1/customer-refunds/{dispute.id}/recalculate-evidence")

    draft = configured_client.post(f"/v1/customer-refunds/{dispute.id}/create-draft")

    assert draft.status_code == 201
    assert draft.json()["draft_type"] == "customer_refund_missing_item"


def test_staff_cannot_create_draft(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"])
    detect(configured_client)
    dispute = db_session.scalar(select(UberCustomerRefundDispute))
    assert dispute is not None
    staff = create_user(configured_client, "staff-refund-draft@example.com", "staff")
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = configured_client.post(f"/v1/customer-refunds/{dispute.id}/create-draft", headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_ignore_works(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"])
    detect(configured_client)
    dispute = db_session.scalar(select(UberCustomerRefundDispute))
    assert dispute is not None

    response = configured_client.post(f"/v1/customer-refunds/{dispute.id}/ignore", json={"reason": "Montant non contestable"})

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_reporting_includes_total_deductions(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"], amount="-42.00")
    detect(configured_client)

    response = configured_client.get("/v1/reports/commercial-summary")

    assert response.status_code == 200
    assert response.json()["customer_refunds"]["total_deducted_amount"] == "42.00"


def test_evidence_tasks_generated_for_existing_claim_order(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"], "UBER-REFUND-1")
    add_transaction(db_session, restaurant["id"], payload={"reason": "missing item"})

    detect(configured_client)

    tasks = db_session.scalars(select(EvidenceRequestTask)).all()
    assert {task.required_evidence_type for task in tasks} == {"receipt"}


def test_upload_via_evidence_task_completes_requirement(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"], "UBER-REFUND-1")
    add_transaction(db_session, restaurant["id"], payload={"reason": "missing item"})
    detect(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.required_evidence_type == "receipt"))
    assert task is not None

    response = configured_client.post(
        f"/v1/evidence-tasks/{task.id}/upload",
        files={"file": ("receipt.png", b"image-content", "image/png")},
    )

    assert response.status_code == 201
    requirement = db_session.scalar(
        select(CustomerRefundEvidenceRequirement).where(CustomerRefundEvidenceRequirement.required_evidence_type == "receipt")
    )
    assert requirement is not None
    assert requirement.status == "uploaded"


def test_detect_does_not_create_email_automatically(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    add_transaction(db_session, restaurant["id"])

    detect(configured_client)

    assert db_session.scalar(select(EmailDraft)) is None
    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "customer_refund_dispute.detect" in actions
    assert "customer_refund_dispute.created" in actions
