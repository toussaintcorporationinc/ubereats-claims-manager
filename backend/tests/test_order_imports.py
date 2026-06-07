import csv
from collections.abc import Generator
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuditLog, ClaimOrder

IMPORT_HEADERS = [
    "restaurant_id",
    "uber_order_number",
    "customer_name",
    "order_date",
    "order_time",
    "cancellation_time",
    "order_amount",
    "currency",
    "accepted_by_restaurant",
    "prepared_before_cancellation",
    "loss_type",
    "notes",
    "internal_reference",
]


@pytest.fixture()
def import_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    storage_dir = tmp_path / "imports"
    monkeypatch.setenv("IMPORT_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("IMPORT_MAX_FILE_SIZE_MB", "10")
    get_settings.cache_clear()
    yield storage_dir
    get_settings.cache_clear()


@pytest.fixture()
def configured_client(import_storage: Path, client: TestClient) -> TestClient:
    return client


@pytest.fixture()
def configured_unauthenticated_client(
    import_storage: Path,
    unauthenticated_client: TestClient,
) -> TestClient:
    return unauthenticated_client


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_restaurant(client: TestClient, name: str = "Restaurant Import") -> dict:
    response = client.post(
        "/v1/restaurants",
        json={"name": name, "sender_email": "claims@example.com"},
    )
    assert response.status_code == 201
    return response.json()


def create_order(client: TestClient, restaurant_id: int, uber_order_number: str = "UBER-IMPORT-EXISTING") -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": uber_order_number,
            "order_amount": "18.40",
            "currency": "EUR",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_staff_user(client: TestClient, email: str = "import-staff@example.com") -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "staff-password",
            "full_name": "Import Staff",
            "role": "staff",
            "active": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str, password: str = "staff-password") -> str:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def assign_restaurant(client: TestClient, user_id: int, restaurant_id: int) -> None:
    response = client.post(f"/v1/users/{user_id}/restaurants", json={"restaurant_id": restaurant_id})
    assert response.status_code == 201


def csv_content(rows: list[dict[str, str]], headers: list[str] | None = None) -> bytes:
    output = StringIO()
    fieldnames = headers or IMPORT_HEADERS
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def xlsx_content(rows: list[dict[str, str]], headers: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    fieldnames = headers or IMPORT_HEADERS
    sheet.append(fieldnames)
    for row in rows:
        sheet.append([row.get(header, "") for header in fieldnames])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def valid_row(restaurant_id: int, uber_order_number: str = "UBER-IMPORT-1") -> dict[str, str]:
    return {
        "restaurant_id": str(restaurant_id),
        "uber_order_number": uber_order_number,
        "customer_name": "Client Test",
        "order_date": "2026-06-01",
        "order_time": "20:15",
        "cancellation_time": "20:35",
        "order_amount": "24.90",
        "currency": "EUR",
        "accepted_by_restaurant": "true",
        "prepared_before_cancellation": "true",
        "loss_type": "gaspillage alimentaire",
        "notes": "commande preparee puis annulee",
        "internal_reference": "TEST-001",
    }


def preview_csv(client: TestClient, rows: list[dict[str, str]], token: str | None = None):
    return client.post(
        "/v1/imports/orders/preview",
        files={"file": ("orders.csv", csv_content(rows), "text/csv")},
        headers=auth_headers(token) if token else None,
    )


def preview_xlsx(client: TestClient, rows: list[dict[str, str]], token: str | None = None):
    return client.post(
        "/v1/imports/orders/preview",
        files={
            "file": (
                "orders.xlsx",
                xlsx_content(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=auth_headers(token) if token else None,
    )


def test_health_public_works(configured_unauthenticated_client: TestClient) -> None:
    response = configured_unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_owner_can_preview_csv_valid(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)

    response = preview_csv(configured_client, [valid_row(restaurant["id"])])

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "parsed"
    assert data["valid_rows"] == 1
    assert data["created_orders_count"] == 0
    assert data["rows_preview"][0]["status"] == "valid"


def test_owner_can_preview_xlsx_valid(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)

    response = preview_xlsx(configured_client, [valid_row(restaurant["id"])])

    assert response.status_code == 201
    assert response.json()["valid_rows"] == 1


def test_preview_rejects_forbidden_extension(configured_client: TestClient) -> None:
    response = configured_client.post(
        "/v1/imports/orders/preview",
        files={"file": ("orders.txt", b"restaurant_id,uber_order_number,order_amount\n1,ABC,12.00", "text/plain")},
    )

    assert response.status_code == 400


def test_preview_rejects_too_large_file(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMPORT_MAX_FILE_SIZE_MB", "0")
    get_settings.cache_clear()

    response = configured_client.post(
        "/v1/imports/orders/preview",
        files={"file": ("orders.csv", b"restaurant_id,uber_order_number,order_amount\n1,ABC,12.00", "text/csv")},
    )

    assert response.status_code == 413


def test_line_without_restaurant_is_invalid(configured_client: TestClient) -> None:
    row = valid_row(1)
    row.pop("restaurant_id")

    response = preview_csv(configured_client, [row])

    assert response.status_code == 201
    assert response.json()["invalid_rows"] == 1
    assert "missing_restaurant" in response.json()["rows_preview"][0]["errors"]


def test_unknown_restaurant_is_invalid(configured_client: TestClient) -> None:
    response = preview_csv(configured_client, [valid_row(9999)])

    assert response.status_code == 201
    assert response.json()["invalid_rows"] == 1
    assert "restaurant_not_found" in response.json()["rows_preview"][0]["errors"]


def test_line_without_uber_order_number_is_invalid(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    row = valid_row(restaurant["id"])
    row["uber_order_number"] = ""

    response = preview_csv(configured_client, [row])

    assert response.status_code == 201
    assert response.json()["invalid_rows"] == 1
    assert "missing_uber_order_number" in response.json()["rows_preview"][0]["errors"]


def test_line_without_order_amount_is_invalid(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    row = valid_row(restaurant["id"])
    row["order_amount"] = ""

    response = preview_csv(configured_client, [row])

    assert response.status_code == 201
    assert response.json()["invalid_rows"] == 1
    assert "missing_order_amount" in response.json()["rows_preview"][0]["errors"]


def test_french_amount_is_normalized(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    row = valid_row(restaurant["id"])
    row["order_amount"] = "12,50"

    response = preview_csv(configured_client, [row])

    assert response.status_code == 201
    assert response.json()["rows_preview"][0]["normalized_data"]["order_amount"] == "12.50"


def test_french_date_is_normalized(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    row = valid_row(restaurant["id"])
    row["order_date"] = "01/06/2026"

    response = preview_csv(configured_client, [row])

    assert response.status_code == 201
    assert response.json()["rows_preview"][0]["normalized_data"]["order_date"] == "2026-06-01"


def test_existing_duplicate_is_marked_duplicate(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"], "UBER-DUP-1")

    response = preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-DUP-1")])

    assert response.status_code == 201
    assert response.json()["duplicate_rows"] == 1
    assert "duplicate_existing_order" in response.json()["rows_preview"][0]["errors"]


def test_internal_duplicate_is_marked_duplicate(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    row = valid_row(restaurant["id"], "UBER-DUP-INTERNAL")

    response = preview_csv(configured_client, [row, row])

    assert response.status_code == 201
    assert response.json()["valid_rows"] == 1
    assert response.json()["duplicate_rows"] == 1


def test_same_uber_number_on_different_restaurants_is_allowed(configured_client: TestClient) -> None:
    first_restaurant = create_restaurant(configured_client, "Restaurant Import A")
    second_restaurant = create_restaurant(configured_client, "Restaurant Import B")

    response = preview_csv(
        configured_client,
        [
            valid_row(first_restaurant["id"], "UBER-SAME-OK"),
            valid_row(second_restaurant["id"], "UBER-SAME-OK"),
        ],
    )

    assert response.status_code == 201
    assert response.json()["valid_rows"] == 2
    assert response.json()["duplicate_rows"] == 0


def test_staff_non_assigned_row_is_unauthorized(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    staff = create_staff_user(configured_client)
    staff_token = login(configured_client, staff["email"])

    response = preview_csv(configured_client, [valid_row(restaurant["id"])], token=staff_token)

    assert response.status_code == 201
    assert response.json()["unauthorized_rows"] == 1
    assert response.json()["rows_preview"][0]["status"] == "unauthorized"


def test_confirm_creates_valid_orders(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    preview = preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-CONFIRM-1")]).json()

    response = configured_client.post(f"/v1/imports/{preview['batch_id']}/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["created_orders_count"] == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "UBER-CONFIRM-1"))
    assert order is not None


def test_confirm_skips_invalid_duplicate_and_unauthorized(configured_client: TestClient, db_session: Session) -> None:
    allowed_restaurant = create_restaurant(configured_client, "Allowed Import")
    blocked_restaurant = create_restaurant(configured_client, "Blocked Import")
    create_order(configured_client, allowed_restaurant["id"], "UBER-DUP-CONFIRM")
    staff = create_staff_user(configured_client, "staff-confirm@example.com")
    assign_restaurant(configured_client, staff["id"], allowed_restaurant["id"])
    staff_token = login(configured_client, staff["email"])
    invalid_row = valid_row(allowed_restaurant["id"], "UBER-INVALID-CONFIRM")
    invalid_row["order_amount"] = ""

    preview_response = preview_csv(
        configured_client,
        [
            valid_row(allowed_restaurant["id"], "UBER-VALID-CONFIRM"),
            invalid_row,
            valid_row(allowed_restaurant["id"], "UBER-DUP-CONFIRM"),
            valid_row(blocked_restaurant["id"], "UBER-BLOCKED-CONFIRM"),
        ],
        token=staff_token,
    )
    preview = preview_response.json()

    response = configured_client.post(f"/v1/imports/{preview['batch_id']}/confirm", headers=auth_headers(staff_token))

    assert response.status_code == 200
    assert response.json()["created_orders_count"] == 1
    assert response.json()["skipped_rows"] == 3
    order_count = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "UBER-VALID-CONFIRM"))
    assert order_count is not None


def test_confirm_refuses_already_confirmed_batch(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    preview = preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-CONFIRM-ONCE")]).json()
    first_response = configured_client.post(f"/v1/imports/{preview['batch_id']}/confirm")
    assert first_response.status_code == 200

    second_response = configured_client.post(f"/v1/imports/{preview['batch_id']}/confirm")

    assert second_response.status_code == 409


def test_cancel_before_confirm_works(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    preview = preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-CANCEL-1")]).json()

    response = configured_client.post(f"/v1/imports/{preview['batch_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancelled_batch_cannot_be_confirmed(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    preview = preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-CANCEL-2")]).json()
    cancel_response = configured_client.post(f"/v1/imports/{preview['batch_id']}/cancel")
    assert cancel_response.status_code == 200

    response = configured_client.post(f"/v1/imports/{preview['batch_id']}/confirm")

    assert response.status_code == 409


def test_audit_log_created_for_preview(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)

    preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-AUDIT-PREVIEW")])

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "import_batch",
            AuditLog.action == "import_batch.previewed",
        )
    )
    assert audit_log is not None


def test_audit_log_created_for_confirm(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    preview = preview_csv(configured_client, [valid_row(restaurant["id"], "UBER-AUDIT-CONFIRM")]).json()

    configured_client.post(f"/v1/imports/{preview['batch_id']}/confirm")

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "import_batch",
            AuditLog.action == "import_batch.confirmed",
        )
    )
    assert audit_log is not None
