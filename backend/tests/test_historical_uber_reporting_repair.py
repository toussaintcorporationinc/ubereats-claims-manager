from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Restaurant,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReportingImportBatch,
    UberReportingImportRow,
)


def create_batch_with_row(
    db_session: Session,
    *,
    report_type: str,
    raw_data: dict[str, object],
    status: str = "invalid",
    errors: list[str] | None = None,
) -> UberReportingImportRow:
    batch = UberReportingImportBatch(
        uploaded_by_user_id=1,
        original_filename="download.csv",
        report_type=report_type,
        file_type="csv",
        status="partially_imported",
        total_rows=1,
        invalid_rows=1 if status == "invalid" else 0,
        warning_rows=1 if status == "warning" else 0,
        duplicate_rows=1 if status == "duplicate" else 0,
    )
    db_session.add(batch)
    db_session.flush()
    row = UberReportingImportRow(
        batch_id=batch.id,
        row_number=2,
        raw_data=raw_data,
        normalized_data={"source": "old_failed_normalization"},
        status=status,
        errors=errors or ["missing_uber_store_id"],
        warnings=[],
    )
    db_session.add(row)
    db_session.commit()
    return row


def create_restaurants(db_session: Session) -> tuple[Restaurant, Restaurant]:
    krousty = Restaurant(name="Krousty Bat", sender_email="krousty@example.com")
    asian = Restaurant(name="Asian Passion", sender_email="asian@example.com")
    db_session.add_all([krousty, asian])
    db_session.commit()
    return krousty, asian


def test_historical_import_repair_preview_finds_exact_restaurant_name(
    client: TestClient,
    db_session: Session,
) -> None:
    _krousty, asian = create_restaurants(db_session)
    create_batch_with_row(
        db_session,
        report_type="orders_report",
        raw_data={
            "store_name": "Asian Passion",
            "order_id": "UBER-OLD-ASIAN-001",
            "customer_name": "Client Test",
            "status": "cancelled",
            "amount": "24.90",
            "currency": "EUR",
        },
    )

    response = client.post("/v1/uber/historical-import-repair/preview", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "preview"
    assert payload["eligible_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["target_restaurant_id"] == asian.id
    assert candidate["target_restaurant_name"] == "Asian Passion"
    assert candidate["row_kind"] == "order"
    assert candidate["uber_order_id"] == "UBER-OLD-ASIAN-001"
    assert candidate["reason"] == "restaurant_name_exact_match"


def test_historical_import_repair_apply_creates_missing_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    _krousty, asian = create_restaurants(db_session)
    row = create_batch_with_row(
        db_session,
        report_type="orders_report",
        raw_data={
            "store_name": "Asian Passion",
            "order_id": "UBER-OLD-ASIAN-002",
            "customer_name": "Client Snapshot",
            "status": "cancelled",
            "amount": "31.50",
            "currency": "EUR",
        },
    )

    response = client.post("/v1/uber/historical-import-repair/apply", json={"confirm": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "applied"
    assert payload["repaired_count"] == 1
    assert payload["created_snapshots_count"] == 1
    snapshot = db_session.scalar(select(UberOrderSnapshot).where(UberOrderSnapshot.uber_order_id == "UBER-OLD-ASIAN-002"))
    db_session.refresh(row)
    assert snapshot is not None
    assert snapshot.restaurant_id == asian.id
    assert snapshot.customer_name == "Client Snapshot"
    assert row.status == "created"
    assert row.created_snapshot_id == snapshot.id
    assert db_session.scalar(
        select(AuditLog).where(AuditLog.action == "historical_uber_reporting_import_repair.row_applied")
    )


def test_historical_import_repair_apply_creates_missing_transaction(
    client: TestClient,
    db_session: Session,
) -> None:
    _krousty, asian = create_restaurants(db_session)
    row = create_batch_with_row(
        db_session,
        report_type="payments_report",
        raw_data={
            "store_name": "Asian Passion",
            "order_id": "UBER-OLD-ASIAN-TX",
            "payment_type": "compensation",
            "payment_date": "2026-06-02",
            "payout_id": "PAYOUT-ASIAN",
            "net_amount": "18.25",
            "currency": "EUR",
        },
    )

    response = client.post("/v1/uber/historical-import-repair/apply", json={"confirm": True})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["created_transactions_count"] == 1
    transaction = db_session.scalar(
        select(UberFinancialTransaction).where(UberFinancialTransaction.uber_order_id == "UBER-OLD-ASIAN-TX")
    )
    db_session.refresh(row)
    assert transaction is not None
    assert transaction.restaurant_id == asian.id
    assert transaction.amount == Decimal("18.25")
    assert transaction.transaction_date == date(2026, 6, 2)
    assert row.status == "created"
    assert row.created_transaction_id == transaction.id


def test_historical_import_repair_does_not_guess_unknown_restaurant(
    client: TestClient,
    db_session: Session,
) -> None:
    create_restaurants(db_session)
    create_batch_with_row(
        db_session,
        report_type="orders_report",
        raw_data={
            "store_name": "Crousty Best",
            "order_id": "UBER-UNKNOWN-RESTAURANT",
            "status": "cancelled",
            "amount": "19.90",
            "currency": "EUR",
        },
    )

    response = client.post("/v1/uber/historical-import-repair/preview", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["eligible_count"] == 0
    assert payload["blocked_count"] == 1
    assert "missing_target_restaurant" in payload["candidates"][0]["blockers"]


def test_historical_import_repair_apply_requires_confirm(client: TestClient, db_session: Session) -> None:
    create_restaurants(db_session)
    create_batch_with_row(
        db_session,
        report_type="orders_report",
        raw_data={
            "store_name": "Asian Passion",
            "order_id": "UBER-CONFIRM-REQUIRED",
            "status": "cancelled",
            "amount": "12.00",
        },
    )

    response = client.post("/v1/uber/historical-import-repair/apply", json={"confirm": False})

    assert response.status_code == 422


def test_historical_import_repair_owner_only(client: TestClient, db_session: Session) -> None:
    create_restaurants(db_session)
    create_batch_with_row(
        db_session,
        report_type="orders_report",
        raw_data={
            "store_name": "Asian Passion",
            "order_id": "UBER-OWNER-ONLY",
            "status": "cancelled",
            "amount": "12.00",
        },
    )
    manager = client.post(
        "/v1/users",
        json={
            "email": "manager-repair@example.com",
            "password": "manager-password",
            "full_name": "Manager Repair",
            "role": "manager",
            "active": True,
        },
    ).json()
    login_response = client.post("/v1/auth/login", json={"email": manager["email"], "password": "manager-password"})
    token = login_response.json()["access_token"]

    response = client.post(
        "/v1/uber/historical-import-repair/preview",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_historical_import_repair_does_not_duplicate_existing_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    _krousty, asian = create_restaurants(db_session)
    db_session.add(
        UberOrderSnapshot(
            restaurant_id=asian.id,
            uber_store_id=f"restaurant-name:{asian.id}",
            uber_order_id="UBER-EXISTS",
            current_state="cancelled",
            order_total_amount=Decimal("22.00"),
            currency="EUR",
            raw_payload_json={"source": "existing"},
            imported_from="manager_export",
        )
    )
    create_batch_with_row(
        db_session,
        report_type="orders_report",
        raw_data={
            "store_name": "Asian Passion",
            "order_id": "UBER-EXISTS",
            "status": "cancelled",
            "amount": "22.00",
            "currency": "EUR",
        },
    )
    db_session.commit()

    response = client.post("/v1/uber/historical-import-repair/preview", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["eligible_count"] == 0
    assert payload["blocked_count"] == 1
    assert "snapshot_already_exists" in payload["candidates"][0]["blockers"]
