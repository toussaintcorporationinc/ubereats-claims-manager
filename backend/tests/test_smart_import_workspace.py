from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    ClaimOrder,
    EvidenceImportBatch,
    EvidenceImportedFile,
    EvidenceRequestTask,
    SmartImportPreviewBatch,
    UberReportingImportBatch,
    UberReportingImportRow,
    Restaurant,
    User,
)
from app.models.domain import utc_now


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200


def test_smart_import_detects_uber_report_without_filename(client: TestClient) -> None:
    csv_content = (
        "Store id,Nom du restaurant,Id. de la commande,Date de la commande,Statut de la commande,Ventes (TVA incluse),Devise\n"
        "store-1,Restaurant Test TENNET,UBER-SMART-001,2026-05-01,canceled,24.90,EUR\n"
    )
    response = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("download.csv", csv_content.encode("utf-8"), "text/csv"))],
    )

    assert response.status_code == 201
    file_preview = response.json()["files"][0]
    assert file_preview["detected_category"] == "uber_reporting"
    assert file_preview["recommended_action"] == "import_uber_reporting"


def test_smart_import_detects_two_line_uber_header_and_restaurant_period(client: TestClient) -> None:
    csv_content = (
        "Descriptions longues Uber Eats Manager,,,,,,\n"
        "Id. du restaurant,Nom du restaurant,Id. de la commande,Date de la commande,Statut de la commande,Ventes (TVA incluse),Devise\n"
        "store-2,Restaurant Test Header,UBER-SMART-002,01/05/2026,annule,31,EUR\n"
        "store-2,Restaurant Test Header,UBER-SMART-003,03/05/2026,canceled,18.50,EUR\n"
    )
    response = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("897e7ee9-f500.csv", csv_content.encode("utf-8"), "text/csv"))],
    )

    assert response.status_code == 201
    file_preview = response.json()["files"][0]
    assert file_preview["header_row_number"] == 2
    assert file_preview["skipped_preamble_rows"] == 1
    assert file_preview["detected_restaurant_name"] == "Restaurant Test Header"
    assert file_preview["detected_date_from"] == "2026-05-01"
    assert file_preview["detected_date_to"] == "2026-05-03"


def test_smart_import_detects_xlsx_two_line_header(client: TestClient) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Descriptions longues Uber"])
    sheet.append(["Id. du restaurant", "Nom du restaurant", "Id. de la commande", "Date de la commande", "Montant total"])
    sheet.append(["store-3", "Restaurant XLSX", "UBER-XLSX-001", "2026-05-10", "12,50"])
    buffer = BytesIO()
    workbook.save(buffer)

    response = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("export.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
    )

    assert response.status_code == 201
    file_preview = response.json()["files"][0]
    assert file_preview["detected_category"] == "uber_reporting"
    assert file_preview["header_row_number"] == 2


def test_smart_import_detects_zip_and_evidence_image(client: TestClient) -> None:
    response = client.post(
        "/v1/smart-import/preview",
        files=[
            ("files", ("preuve.zip", b"PK\x03\x04", "application/zip")),
            ("files", ("IMG_1234.jpg", b"fake-image", "image/jpeg")),
        ],
    )

    assert response.status_code == 201
    files = response.json()["files"]
    assert files[0]["detected_category"] == "zip"
    assert files[0]["recommended_action"] == "import_evidence_bulk"
    assert files[1]["detected_category"] == "evidence"


def test_smart_import_unknown_becomes_manual_review(client: TestClient) -> None:
    response = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("export.csv", b"foo,bar\nbaz,qux\n", "text/csv"))],
    )

    assert response.status_code == 201
    file_preview = response.json()["files"][0]
    assert file_preview["detected_category"] == "unknown"
    assert file_preview["recommended_action"] == "manual_review"


def test_smart_confirm_routes_uber_report_to_reporting_batch(client: TestClient, db_session: Session) -> None:
    csv_content = (
        "Descriptions longues Uber Eats Manager,,,,,,\n"
        "Id. du restaurant,Nom du restaurant,Id. de la commande,Date de la commande,Statut de la commande,Ventes (TVA incluse),Devise\n"
        "store-route,Restaurant Route,UBER-ROUTE-001,01/05/2026,canceled,31,EUR\n"
    )
    preview = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("download.csv", csv_content.encode("utf-8"), "text/csv"))],
    ).json()

    response = client.post(
        "/v1/smart-import/confirm",
        json={
            "batch_preview_id": preview["batch_preview_id"],
            "files": [{"file_id": preview["files"][0]["id"], "action": "import_uber_reporting", "report_type": "orders_report"}],
        },
    )

    assert response.status_code == 200
    routed = response.json()["routed_files"][0]
    assert routed["destination_type"] == "uber_reporting_batch"
    assert routed["destination_url"] == f"/uber/reporting/{routed['destination_id']}"
    batch = db_session.get(UberReportingImportBatch, routed["destination_id"])
    assert batch is not None
    assert batch.status == "parsed"
    assert batch.report_type == "orders_report"
    rows = db_session.scalars(select(UberReportingImportRow).where(UberReportingImportRow.batch_id == batch.id)).all()
    assert rows
    assert all(row.status != "created" for row in rows)


def test_smart_import_preview_marks_exact_duplicate_by_checksum(client: TestClient, db_session: Session) -> None:
    csv_content = (
        "Id. du restaurant,Nom du restaurant,Id. de la commande,Date de la commande,Statut de la commande,Ventes (TVA incluse),Devise\n"
        "store-dup,Restaurant Dup,UBER-DUP-001,01/05/2026,canceled,31,EUR\n"
    )

    response = client.post(
        "/v1/smart-import/preview",
        files=[
            ("files", ("download (1).csv", csv_content.encode("utf-8"), "text/csv")),
            ("files", ("download.csv", csv_content.encode("utf-8"), "text/csv")),
        ],
    )

    assert response.status_code == 201
    files = sorted(response.json()["files"], key=lambda item: item["original_filename"])
    canonical = next(item for item in files if item["original_filename"] == "download.csv")
    duplicate = next(item for item in files if item["original_filename"] == "download (1).csv")
    assert canonical["recommended_action"] == "import_uber_reporting"
    assert duplicate["recommended_action"] == "ignore"
    assert duplicate["status"] == "ignored"
    assert duplicate["destination_type"] == "duplicate_ignored"
    assert duplicate["destination_id"] == canonical["id"]
    assert "exact_duplicate_ignored" in duplicate["warnings"]

    duplicate_audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "smart_import_preview_file",
            AuditLog.action == "smart_import_file.duplicate_ignored",
            AuditLog.entity_id == duplicate["id"],
        )
    )
    assert duplicate_audit is not None


def test_smart_confirm_does_not_route_exact_duplicate_even_if_forced(client: TestClient, db_session: Session) -> None:
    csv_content = (
        "Id. du restaurant,Nom du restaurant,Id. de la commande,Date de la commande,Statut de la commande,Ventes (TVA incluse),Devise\n"
        "store-dup-force,Restaurant Dup Force,UBER-DUP-FORCE-001,01/05/2026,canceled,31,EUR\n"
    )
    preview = client.post(
        "/v1/smart-import/preview",
        files=[
            ("files", ("copy.csv", csv_content.encode("utf-8"), "text/csv")),
            ("files", ("copy-again.csv", csv_content.encode("utf-8"), "text/csv")),
        ],
    ).json()

    response = client.post(
        "/v1/smart-import/confirm",
        json={
            "batch_preview_id": preview["batch_preview_id"],
            "files": [
                {"file_id": preview["files"][0]["id"], "action": "import_uber_reporting", "report_type": "orders_report"},
                {"file_id": preview["files"][1]["id"], "action": "import_uber_reporting", "report_type": "orders_report"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["routed_files"]) == 1
    assert len(payload["ignored_files"]) == 1
    assert payload["ignored_files"][0]["destination_type"] == "duplicate_ignored"
    reporting_batches = db_session.scalars(select(UberReportingImportBatch)).all()
    assert len(reporting_batches) == 1
    batch = db_session.get(SmartImportPreviewBatch, preview["batch_preview_id"])
    assert batch is not None
    assert len([file for file in batch.files if file.status == "routed"]) == 1
    assert len([file for file in batch.files if file.status == "ignored"]) == 1


def test_smart_confirm_routes_evidence_file_to_evidence_import(client: TestClient, db_session: Session) -> None:
    preview = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("ticket-test.jpg", b"fake image bytes", "image/jpeg"))],
    ).json()

    response = client.post(
        "/v1/smart-import/confirm",
        json={
            "batch_preview_id": preview["batch_preview_id"],
            "files": [{"file_id": preview["files"][0]["id"], "action": "import_evidence_bulk"}],
        },
    )

    assert response.status_code == 200
    routed = response.json()["routed_files"][0]
    assert routed["destination_type"] == "evidence_import_batch"
    assert routed["destination_url"] == f"/evidence-imports/{routed['destination_id']}"
    batch = db_session.get(EvidenceImportBatch, routed["destination_id"])
    assert batch is not None
    assert batch.status == "stored"
    assert batch.stored_files_count == 1


def test_smart_confirm_duplicate_evidence_creates_visible_ignored_file(client: TestClient, db_session: Session) -> None:
    first = client.post(
        "/v1/evidence-imports",
        files=[("files", ("ticket-original.jpg", b"same smart evidence bytes", "image/jpeg"))],
    )
    assert first.status_code == 201

    preview = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("ticket-again.jpg", b"same smart evidence bytes", "image/jpeg"))],
    ).json()

    response = client.post(
        "/v1/smart-import/confirm",
        json={
            "batch_preview_id": preview["batch_preview_id"],
            "files": [{"file_id": preview["files"][0]["id"], "action": "import_evidence_bulk"}],
        },
    )

    assert response.status_code == 200
    routed = response.json()["routed_files"][0]
    batch = db_session.get(EvidenceImportBatch, routed["destination_id"])
    assert batch is not None
    assert batch.status == "analyzed"
    assert batch.stored_files_count == 0
    assert batch.duplicate_files_count == 1
    imported_files = db_session.scalars(select(EvidenceImportedFile).where(EvidenceImportedFile.batch_id == batch.id)).all()
    assert len(imported_files) == 1
    assert imported_files[0].status == "ignored"
    assert imported_files[0].original_filename == "ticket-again.jpg"


def test_smart_confirm_routes_zip_to_evidence_import(client: TestClient, db_session: Session) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("ticket-a.jpg", b"fake image")
    preview = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("preuve.zip", archive.getvalue(), "application/zip"))],
    ).json()

    response = client.post(
        "/v1/smart-import/confirm",
        json={
            "batch_preview_id": preview["batch_preview_id"],
            "files": [{"file_id": preview["files"][0]["id"], "action": "import_evidence_bulk"}],
        },
    )

    assert response.status_code == 200
    routed = response.json()["routed_files"][0]
    batch = db_session.get(EvidenceImportBatch, routed["destination_id"])
    assert batch is not None
    assert batch.source_type == "zip_upload"
    assert batch.stored_files_count == 1


def test_smart_confirm_manual_review_and_ignore_keep_audit_state(client: TestClient, db_session: Session) -> None:
    preview = client.post(
        "/v1/smart-import/preview",
        files=[
            ("files", ("unknown.csv", b"foo,bar\nbaz,qux\n", "text/csv")),
            ("files", ("ignore.jpg", b"fake image bytes", "image/jpeg")),
        ],
    ).json()

    response = client.post(
        "/v1/smart-import/confirm",
        json={
            "batch_preview_id": preview["batch_preview_id"],
            "files": [
                {"file_id": preview["files"][0]["id"], "action": "manual_review"},
                {"file_id": preview["files"][1]["id"], "action": "ignore"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["manual_review_files"][0]["destination_type"] == "manual_review"
    assert payload["ignored_files"][0]["destination_type"] == "ignored"
    batch = db_session.get(SmartImportPreviewBatch, preview["batch_preview_id"])
    assert batch is not None
    assert {file.status for file in batch.files} == {"manual_review", "ignored"}


def test_smart_confirm_expired_preview_refused(client: TestClient, db_session: Session) -> None:
    preview = client.post(
        "/v1/smart-import/preview",
        files=[("files", ("ticket-test.jpg", b"fake image bytes", "image/jpeg"))],
    ).json()
    batch = db_session.get(SmartImportPreviewBatch, preview["batch_preview_id"])
    assert batch is not None
    batch.expires_at = utc_now() - timedelta(hours=1)
    db_session.commit()

    response = client.post(
        "/v1/smart-import/confirm",
        json={"batch_preview_id": preview["batch_preview_id"]},
    )

    assert response.status_code == 410


def test_workspace_next_actions_returns_priorities_for_owner(client: TestClient, db_session: Session) -> None:
    restaurant, order = create_restaurant_order_and_task(db_session)

    response = client.get("/v1/workspace/next-actions")

    assert response.status_code == 200
    payload = response.json()
    urgent_titles = [item["title"] for item in payload["urgent"]]
    all_urls = [item["action_url"] for bucket in payload.values() for item in bucket]
    assert any("Ticket" in title or "preuve" in title.lower() for title in urgent_titles)
    assert "/smart-import" in all_urls
    assert "/recovery" in all_urls
    assert "/reports" in all_urls
    assert "/autopilot" in all_urls
    assert restaurant.id == order.restaurant_id


def test_staff_next_actions_limited_to_evidence(client: TestClient, db_session: Session) -> None:
    restaurant, _order = create_restaurant_order_and_task(db_session)
    staff = client.post(
        "/v1/users",
        json={
            "email": "staff-next-actions@example.com",
            "password": "staff-password",
            "full_name": "Staff Next Actions",
            "role": "staff",
            "active": True,
        },
    ).json()
    assign_response = client.post(f"/v1/users/{staff['id']}/restaurants", json={"restaurant_id": restaurant.id})
    assert assign_response.status_code == 201
    login_response = client.post("/v1/auth/login", json={"email": "staff-next-actions@example.com", "password": "staff-password"})
    token = login_response.json()["access_token"]

    response = client.get("/v1/workspace/next-actions", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    actions = [item for bucket in response.json().values() for item in bucket]
    assert actions
    assert {item["action_type"] for item in actions} == {"upload_evidence"}


def create_restaurant_order_and_task(db: Session) -> tuple[Restaurant, ClaimOrder]:
    owner = db.scalar(select(User).where(User.email == "owner@example.com"))
    restaurant = Restaurant(name="Restaurant Next Actions", sender_email="claims@example.com")
    db.add(restaurant)
    db.flush()
    order = ClaimOrder(
        restaurant_id=restaurant.id,
        uber_order_number="UBER-NEXT-001",
        customer_name="Client Test",
        order_amount=Decimal("125.00"),
        currency="EUR",
        notes="Annulation test",
        status="missing_evidence",
    )
    db.add(order)
    db.flush()
    db.add(
        EvidenceRequestTask(
            order_id=order.id,
            restaurant_id=restaurant.id,
            task_type="missing_receipt",
            required_evidence_type="receipt",
            status="pending",
            priority="urgent",
            title="Ticket a fournir",
            description="Ticket fictif requis",
            due_at=datetime.now(timezone.utc),
            reason="missing_receipt",
            created_by_user_id=owner.id if owner else None,
        )
    )
    db.commit()
    db.refresh(restaurant)
    db.refresh(order)
    return restaurant, order
