from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.models import AuditLog


def restaurant_payload(name: str = "Restaurant Republique", sender_email: str = "claims@example.com") -> dict:
    return {
        "name": name,
        "legal_name": f"{name} SAS",
        "address": "10 rue Exemple, Paris",
        "sender_email": sender_email,
        "uber_merchant_id": f"merchant-{name.lower().replace(' ', '-')}",
    }


def create_restaurant(client: TestClient, name: str = "Restaurant Republique") -> dict:
    response = client.post("/v1/restaurants", json=restaurant_payload(name=name))
    assert response.status_code == 201
    return response.json()


def order_payload(restaurant_id: int, uber_order_number: str = "UBER-123", amount: str = "24.50") -> dict:
    return {
        "restaurant_id": restaurant_id,
        "internal_reference": "INT-001",
        "uber_order_number": uber_order_number,
        "customer_name": "Client Test",
        "order_date": "2026-06-07",
        "order_time": "12:30:00",
        "cancellation_time": "12:45:00",
        "order_amount": amount,
        "currency": "EUR",
        "accepted_by_restaurant": True,
        "prepared_before_cancellation": True,
        "loss_type": "prepared_cancelled_order",
        "notes": "Commande annulee apres preparation.",
    }


def create_order(client: TestClient, restaurant_id: int, uber_order_number: str = "UBER-123", amount: str = "24.50") -> dict:
    response = client.post("/v1/orders", json=order_payload(restaurant_id, uber_order_number, amount))
    assert response.status_code == 201
    return response.json()


def as_decimal(value: str | int | float) -> Decimal:
    return Decimal(str(value))


def test_create_restaurant_ok(client: TestClient) -> None:
    restaurant = create_restaurant(client)

    assert restaurant["id"] == 1
    assert restaurant["name"] == "Restaurant Republique"
    assert restaurant["sender_email"] == "claims@example.com"
    assert restaurant["active"] is True


def test_create_order_ok(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    assert order["restaurant_id"] == restaurant["id"]
    assert order["uber_order_number"] == "UBER-123"
    assert order["currency"] == "EUR"


def test_create_order_without_uber_order_number_is_rejected(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    payload = order_payload(restaurant["id"])
    payload.pop("uber_order_number")

    response = client.post("/v1/orders", json=payload)

    assert response.status_code == 422


def test_create_order_without_amount_is_rejected(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    payload = order_payload(restaurant["id"])
    payload.pop("order_amount")

    response = client.post("/v1/orders", json=payload)

    assert response.status_code == 422


def test_duplicate_order_number_for_same_restaurant_is_rejected(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    create_order(client, restaurant["id"], "UBER-DUPLICATE")

    response = client.post("/v1/orders", json=order_payload(restaurant["id"], "UBER-DUPLICATE"))

    assert response.status_code == 409


def test_same_uber_order_number_allowed_for_different_restaurants(client: TestClient) -> None:
    first_restaurant = create_restaurant(client, "Restaurant A")
    second_restaurant = create_restaurant(client, "Restaurant B")
    create_order(client, first_restaurant["id"], "UBER-SHARED")

    response = client.post("/v1/orders", json=order_payload(second_restaurant["id"], "UBER-SHARED"))

    assert response.status_code == 201
    assert response.json()["restaurant_id"] == second_restaurant["id"]


def test_add_evidence_ok(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    response = client.post(
        f"/v1/orders/{order['id']}/evidence",
        json={
            "evidence_type": "cancellation_proof",
            "original_filename": "annulation.png",
            "storage_path": "storage/evidence/annulation.png",
            "mime_type": "image/png",
            "file_size": 1200,
        },
    )

    assert response.status_code == 201
    assert response.json()["evidence_type"] == "cancellation_proof"


def test_invalid_evidence_type_is_rejected(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    response = client.post(
        f"/v1/orders/{order['id']}/evidence",
        json={
            "evidence_type": "invoice",
            "original_filename": "preuve.pdf",
            "storage_path": "storage/evidence/preuve.pdf",
        },
    )

    assert response.status_code == 422


def test_claim_order_default_status_is_draft(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    payload = order_payload(restaurant["id"])
    payload.pop("status", None)

    response = client.post("/v1/orders", json=payload)

    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_audit_log_created_when_order_is_created(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"])

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "claim_order",
            AuditLog.entity_id == order["id"],
            AuditLog.action == "claim_order.created",
        )
    )

    assert audit_log is not None


def test_dashboard_summary_returns_expected_totals(client: TestClient) -> None:
    first_restaurant = create_restaurant(client, "Restaurant A")
    second_restaurant = create_restaurant(client, "Restaurant B")
    create_order(client, first_restaurant["id"], "UBER-1", "10.00")

    refused_order = create_order(client, first_restaurant["id"], "UBER-2", "20.00")
    client.patch(f"/v1/orders/{refused_order['id']}", json={"status": "refused"})

    recovered_order = create_order(client, second_restaurant["id"], "UBER-1", "30.00")
    client.patch(
        f"/v1/orders/{recovered_order['id']}",
        json={
            "status": "payment_confirmed",
            "result": "payment_confirmed_from_uber_reporting",
            "recovered_amount": "25.00",
        },
    )
    promised_order = create_order(client, second_restaurant["id"], "UBER-3", "40.00")
    client.patch(
        f"/v1/orders/{promised_order['id']}",
        json={
            "status": "payment_confirmed",
            "result": "payment_confirmed",
            "recovered_amount": "40.00",
        },
    )

    response = client.get("/v1/dashboard/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_orders"] == 4
    assert as_decimal(data["total_claimed_amount"]) == Decimal("100.00")
    assert as_decimal(data["total_recovered_amount"]) == Decimal("25.00")
    assert as_decimal(data["total_refused_amount"]) == Decimal("20.00")
    assert as_decimal(data["total_pending_amount"]) == Decimal("10.00")
    assert data["orders_by_status"] == {
        "draft": 1,
        "payment_confirmed": 2,
        "refused": 1,
    }
    assert len(data["orders_by_restaurant"]) == 2
    second_summary = next(
        row for row in data["orders_by_restaurant"] if row["restaurant_id"] == second_restaurant["id"]
    )
    assert as_decimal(second_summary["total_recovered_amount"]) == Decimal("25.00")


def test_initial_alembic_migration_creates_domain_tables() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    work_dir = repo_root / "work"
    work_dir.mkdir(exist_ok=True)
    db_path = work_dir / "test_migration.db"
    if db_path.exists():
        db_path.unlink()

    config = Config("alembic.ini")
    config.attributes["database_url"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    engine = None

    try:
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        assert {
            "restaurants",
            "claim_orders",
            "evidence_files",
            "email_drafts",
            "email_threads",
            "audit_logs",
            "users",
            "user_restaurant_access",
            "alembic_version",
        }.issubset(tables)
    finally:
        if engine is not None:
            engine.dispose()
        if db_path.exists():
            db_path.unlink()
