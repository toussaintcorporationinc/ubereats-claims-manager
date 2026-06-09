from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClaimOrder, UberFinancialTransaction, UberOrderSnapshot, UberReconciliationResult


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def bootstrap_owner(client: TestClient) -> str:
    response = client.post(
        "/v1/auth/register",
        json={"email": "owner@example.com", "password": "owner-password", "full_name": "Owner Test"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def create_restaurant(client: TestClient, token: str, name: str) -> dict:
    response = client.post(
        "/v1/restaurants",
        json={"name": name, "sender_email": "claims@example.com"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def create_user(client: TestClient, token: str, email: str, role: str) -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "user-password",
            "full_name": f"{role.title()} Test",
            "role": role,
            "active": True,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str, password: str = "user-password") -> str:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def assign_restaurant(client: TestClient, token: str, user_id: int, restaurant_id: int) -> None:
    response = client.post(
        f"/v1/users/{user_id}/restaurants",
        json={"restaurant_id": restaurant_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201


def create_store_mapping(client: TestClient, token: str, restaurant_id: int, store_id: str) -> dict:
    response = client.post(
        "/v1/uber/store-mappings",
        json={
            "restaurant_id": restaurant_id,
            "uber_store_id": store_id,
            "uber_store_name": f"Uber Store {store_id}",
            "active": True,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def upload_report(client: TestClient, token: str, csv_text: str) -> dict:
    response = client.post(
        "/v1/uber/reporting/import",
        files={"file": ("uber-report.csv", BytesIO(csv_text.encode("utf-8")), "text/csv")},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def preview_report(client: TestClient, token: str, csv_text: str, report_type: str = "orders_report") -> dict:
    response = client.post(
        f"/v1/uber/reporting/preview?report_type={report_type}",
        files={"file": ("uber-report.csv", BytesIO(csv_text.encode("utf-8")), "text/csv")},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def xlsx_bytes(headers: list[str], rows: list[list[object]]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def test_health_still_public(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200


def test_owner_can_create_mapping_and_manager_non_assigned_cannot_see_it(unauthenticated_client: TestClient) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber A")
    mapping = create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-a")
    manager = create_user(unauthenticated_client, owner_token, "manager@example.com", "manager")
    manager_token = login(unauthenticated_client, manager["email"])

    response = unauthenticated_client.get("/v1/uber/store-mappings", headers=auth_headers(manager_token))

    assert response.status_code == 200
    assert response.json() == []
    assert mapping["uber_store_id"] == "store-a"


def test_manager_assigned_can_import_reporting_file(unauthenticated_client: TestClient, db_session: Session) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Import")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-import")
    manager = create_user(unauthenticated_client, owner_token, "manager@example.com", "manager")
    assign_restaurant(unauthenticated_client, owner_token, manager["id"], restaurant["id"])
    manager_token = login(unauthenticated_client, manager["email"])

    result = upload_report(
        unauthenticated_client,
        manager_token,
        "\n".join(
            [
                "uber_store_id,uber_order_id,current_state,order_total_amount,currency,canceled_at",
                "store-import,UBER-CANCEL-1,canceled,24.90,EUR,2026-06-01",
            ]
        ),
    )

    assert result["snapshots_created"] == 1
    assert db_session.scalar(select(UberOrderSnapshot).where(UberOrderSnapshot.uber_order_id == "UBER-CANCEL-1"))


def test_reconciliation_detects_not_compensated_partially_and_compensated(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Reco")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-reco")
    csv_text = "\n".join(
        [
            "uber_store_id,uber_order_id,current_state,order_total_amount,currency,canceled_at,transaction_type,amount,transaction_date",
            "store-reco,UBER-NONE,canceled,24.90,EUR,2026-06-01,,,",
            "store-reco,UBER-PART,canceled,24.90,EUR,2026-06-01,,,",
            "store-reco,UBER-PART,canceled,24.90,EUR,2026-06-01,compensation,10.00,2026-06-02",
            "store-reco,UBER-PAID,canceled,24.90,EUR,2026-06-01,,,",
            "store-reco,UBER-PAID,canceled,24.90,EUR,2026-06-01,compensation,24.90,2026-06-02",
        ]
    )
    upload_report(unauthenticated_client, owner_token, csv_text)

    response = unauthenticated_client.post("/v1/uber/reconciliation/run", headers=auth_headers(owner_token))

    assert response.status_code == 200
    statuses = {
        result.uber_order_id: result.status
        for result in db_session.scalars(select(UberReconciliationResult)).all()
    }
    assert statuses["UBER-NONE"] == "not_compensated"
    assert statuses["UBER-PART"] == "partially_compensated"
    assert statuses["UBER-PAID"] == "compensated"
    assert db_session.scalar(select(UberFinancialTransaction).where(UberFinancialTransaction.uber_order_id == "UBER-PAID"))


def test_create_claim_order_from_non_compensated_result_without_duplicate(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Claim")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-claim")
    upload_report(
        unauthenticated_client,
        owner_token,
        "\n".join(
            [
                "uber_store_id,uber_order_id,current_state,order_total_amount,currency,canceled_at",
                "store-claim,UBER-CLAIM-1,canceled,24.90,EUR,2026-06-01",
            ]
        ),
    )
    unauthenticated_client.post("/v1/uber/reconciliation/run", headers=auth_headers(owner_token))
    result = db_session.scalar(
        select(UberReconciliationResult).where(UberReconciliationResult.uber_order_id == "UBER-CLAIM-1")
    )
    assert result is not None

    first = unauthenticated_client.post(
        f"/v1/uber/reconciliation/results/{result.id}/claim-order",
        headers=auth_headers(owner_token),
    )
    second = unauthenticated_client.post(
        f"/v1/uber/reconciliation/results/{result.id}/claim-order",
        headers=auth_headers(owner_token),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert (
        db_session.scalar(
            select(ClaimOrder).where(
                ClaimOrder.restaurant_id == restaurant["id"],
                ClaimOrder.uber_order_number == "UBER-CLAIM-1",
            )
        )
        is not None
    )


def test_uber_endpoints_are_protected_and_staff_cannot_access_config(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/v1/uber/status").status_code == 401
    owner_token = bootstrap_owner(unauthenticated_client)
    staff = create_user(unauthenticated_client, owner_token, "staff@example.com", "staff")
    staff_token = login(unauthenticated_client, staff["email"])

    response = unauthenticated_client.get("/v1/uber/status", headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_owner_can_preview_orders_report_csv_with_normalization(unauthenticated_client: TestClient) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Preview")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-preview")

    preview = preview_report(
        unauthenticated_client,
        owner_token,
        "\n".join(
            [
                "store id,numero_commande,statut,date_commande,annulation,montant_commande,devise,unknown_column",
                "store-preview,UBER-PREVIEW-1,annulé,01/06/2026 20:15,01/06/2026 20:35,\"1 234,56\",EUR,ignored",
            ]
        ),
    )

    row = preview["rows_preview"][0]
    assert preview["valid_rows"] == 1
    assert preview["detected_columns"]
    assert row["normalized_data"]["order_total_amount"] == "1234.56"
    assert row["normalized_data"]["is_cancelled"] is True
    assert row["normalized_data"]["placed_at"].startswith("2026-06-01T20:15")


def test_preview_payments_adjustments_and_xlsx(unauthenticated_client: TestClient) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber XLSX")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-xlsx")
    payments = preview_report(
        unauthenticated_client,
        owner_token,
        "\n".join(
            [
                "store_uuid,order_uuid,payment_type,payment_date,payout_id,net_amount,currency",
                "store-xlsx,UBER-PAY-1,compensation,2026-06-02,PAYOUT-1,\"-12,50\",EUR",
            ]
        ),
        "payments_report",
    )
    assert payments["total_rows"] == 1

    workbook_payload = xlsx_bytes(
        ["store_uuid", "order_uuid", "adjustment_type", "date_transaction", "value", "currency"],
        [["store-xlsx", "UBER-ADJ-1", "refund", "02/06/2026", "-12,50", "EUR"]],
    )
    response = unauthenticated_client.post(
        "/v1/uber/reporting/preview?report_type=adjustments_report",
        files={"file": ("adjustments.xlsx", workbook_payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth_headers(owner_token),
    )
    assert response.status_code == 200, response.text
    row = response.json()["rows_preview"][0]
    assert row["normalized_data"]["amount"] == "-12.50"
    assert row["normalized_data"]["transaction_date"] == "2026-06-02"


def test_preview_rejects_forbidden_extension_and_reports_missing_columns(unauthenticated_client: TestClient) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    forbidden = unauthenticated_client.post(
        "/v1/uber/reporting/preview?report_type=orders_report",
        files={"file": ("report.txt", BytesIO(b"hello"), "text/plain")},
        headers=auth_headers(owner_token),
    )
    assert forbidden.status_code == 400

    preview = preview_report(
        unauthenticated_client,
        owner_token,
        "unknown_column\nvalue",
    )
    row = preview["rows_preview"][0]
    assert row["status"] == "invalid"
    assert "missing_uber_store_id" in row["errors"]


def test_unmapped_store_preview_and_owner_mapping(unauthenticated_client: TestClient) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Map Later")
    preview = preview_report(
        unauthenticated_client,
        owner_token,
        "\n".join(
            [
                "store_id,store_name,order_id,status,amount,currency",
                "store-later,Store Later,UBER-LATER-1,cancelled,10.00,EUR",
            ]
        ),
    )
    assert preview["unmapped_store_ids"] == ["store-later"]

    stores = unauthenticated_client.get("/v1/uber/reporting/unmapped-stores", headers=auth_headers(owner_token))
    assert stores.status_code == 200
    assert stores.json()[0]["uber_store_id"] == "store-later"

    mapped = unauthenticated_client.post(
        "/v1/uber/reporting/unmapped-stores/store-later/map",
        json={"restaurant_id": restaurant["id"]},
        headers=auth_headers(owner_token),
    )
    assert mapped.status_code == 200
    assert mapped.json()["restaurant_id"] == restaurant["id"]


def test_confirm_reporting_batch_creates_snapshot_and_no_snapshot_duplicate(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Confirm")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-confirm")
    preview = preview_report(
        unauthenticated_client,
        owner_token,
        "\n".join(
            [
                "store_id,order_id,status,amount,currency",
                "store-confirm,UBER-CONFIRM-1,cancelled,20.00,EUR",
            ]
        ),
    )

    first = unauthenticated_client.post(
        f"/v1/uber/reporting/batches/{preview['batch_id']}/confirm",
        headers=auth_headers(owner_token),
    )
    second = unauthenticated_client.post(
        f"/v1/uber/reporting/batches/{preview['batch_id']}/confirm",
        headers=auth_headers(owner_token),
    )

    assert first.status_code == 200
    assert first.json()["created_snapshots_count"] == 1
    assert second.status_code == 400
    snapshots = db_session.scalars(select(UberOrderSnapshot).where(UberOrderSnapshot.uber_order_id == "UBER-CONFIRM-1")).all()
    assert len(snapshots) == 1


def test_confirm_reporting_batch_creates_transaction_without_duplicate(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner_token, "Restaurant Uber Transaction")
    create_store_mapping(unauthenticated_client, owner_token, restaurant["id"], "store-tx")
    preview = preview_report(
        unauthenticated_client,
        owner_token,
        "\n".join(
            [
                "store_id,order_id,transaction_type,transaction_date,payout_reference,amount,currency",
                "store-tx,UBER-TX-1,compensation,2026-06-02,PAYOUT-1,10.00,EUR",
                "store-tx,UBER-TX-1,compensation,2026-06-02,PAYOUT-1,10.00,EUR",
            ]
        ),
        "payments_report",
    )
    assert preview["duplicate_rows"] == 1

    result = unauthenticated_client.post(
        f"/v1/uber/reporting/batches/{preview['batch_id']}/confirm",
        headers=auth_headers(owner_token),
    )

    assert result.status_code == 200
    assert result.json()["created_transactions_count"] == 1
    transactions = db_session.scalars(
        select(UberFinancialTransaction).where(UberFinancialTransaction.uber_order_id == "UBER-TX-1")
    ).all()
    assert len(transactions) == 1


def test_manager_non_assigned_and_staff_are_refused_for_reporting_preview(unauthenticated_client: TestClient) -> None:
    owner_token = bootstrap_owner(unauthenticated_client)
    manager = create_user(unauthenticated_client, owner_token, "manager@example.com", "manager")
    staff = create_user(unauthenticated_client, owner_token, "staff@example.com", "staff")
    manager_token = login(unauthenticated_client, manager["email"])
    staff_token = login(unauthenticated_client, staff["email"])

    manager_preview = preview_report(
        unauthenticated_client,
        manager_token,
        "store_id,order_id,status,amount\nunknown-store,UBER-DENIED,cancelled,10.00",
    )
    assert manager_preview["rows_preview"][0]["status"] == "warning"

    staff_response = unauthenticated_client.post(
        "/v1/uber/reporting/preview?report_type=orders_report",
        files={"file": ("uber-report.csv", BytesIO(b"store_id,order_id\nx,y"), "text/csv")},
        headers=auth_headers(staff_token),
    )
    assert staff_response.status_code == 403
