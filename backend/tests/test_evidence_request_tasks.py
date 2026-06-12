from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuditLog, EvidenceRequestTask, EvidenceUploadLink, UberReconciliationResult
from app.models.domain import utc_now


@pytest.fixture()
def evidence_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    storage_dir = tmp_path / "evidence"
    monkeypatch.setenv("EVIDENCE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("MAX_EVIDENCE_FILE_SIZE_MB", "1")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    get_settings.cache_clear()
    yield storage_dir
    get_settings.cache_clear()


@pytest.fixture()
def configured_client(evidence_storage: Path, client: TestClient) -> TestClient:
    return client


@pytest.fixture()
def configured_unauthenticated_client(
    evidence_storage: Path,
    unauthenticated_client: TestClient,
) -> TestClient:
    return unauthenticated_client


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_restaurant(client: TestClient, name: str = "Evidence Task Restaurant") -> dict:
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


def create_order(
    client: TestClient,
    restaurant_id: int,
    order_number: str = "UBER-EVIDENCE-TASK-1",
    *,
    amount: str = "24.90",
    loss_type: str | None = "gaspillage alimentaire",
) -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": amount,
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
            "loss_type": loss_type,
        },
    )
    assert response.status_code == 201
    return response.json()


def add_metadata_evidence(client: TestClient, order_id: int, evidence_type: str) -> None:
    response = client.post(
        f"/v1/orders/{order_id}/evidence",
        json={
            "evidence_type": evidence_type,
            "original_filename": f"{evidence_type}.png",
            "storage_path": f"storage/evidence/{evidence_type}.png",
            "mime_type": "image/png",
            "file_size": 1024,
        },
    )
    assert response.status_code == 201


def recalculate(client: TestClient, token: str | None = None) -> dict:
    response = client.post("/v1/evidence-tasks/recalculate", json={}, headers=auth_headers(token) if token else None)
    assert response.status_code == 200
    return response.json()


def upload_task_file(client: TestClient, task_id: int, token: str | None = None):
    return client.post(
        f"/v1/evidence-tasks/{task_id}/upload",
        files={"file": ("preuve.png", b"image-content", "image/png")},
        headers=auth_headers(token) if token else None,
    )


def test_health_public_works(configured_unauthenticated_client: TestClient) -> None:
    response = configured_unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recalculate_creates_missing_evidence_tasks(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    result = recalculate(configured_client)

    assert result["created_tasks"] == 2
    tasks = db_session.scalars(select(EvidenceRequestTask).where(EvidenceRequestTask.order_id == order["id"])).all()
    assert {task.required_evidence_type for task in tasks} == {"cancellation_proof", "waste_photo"}
    assert {task.task_type for task in tasks} == {"missing_cancellation_proof", "missing_waste_photo"}
    assert {task.restaurant_id for task in tasks} == {restaurant["id"]}
    assert {task.status for task in tasks} == {"pending"}
    assert all(task.title for task in tasks)


def test_recalculate_does_not_create_duplicate_tasks(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])

    assert recalculate(configured_client)["created_tasks"] == 2
    second = recalculate(configured_client)

    assert second["created_tasks"] == 0
    assert second["existing_tasks"] == 2
    assert len(db_session.scalars(select(EvidenceRequestTask)).all()) == 2


def test_manager_assigned_can_list_tasks(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    manager = create_user(configured_client, "manager-evidence@example.com", "manager")
    assign_restaurant(configured_client, manager["id"], restaurant["id"])
    manager_token = login(configured_client, manager["email"])

    response = configured_client.get("/v1/evidence-tasks", headers=auth_headers(manager_token))

    assert response.status_code == 200
    assert len(response.json()["tasks"]) == 2


def test_manager_non_assigned_cannot_list_other_tasks(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    other = create_restaurant(configured_client, "Other")
    recalculate(configured_client)
    manager = create_user(configured_client, "manager-no-evidence@example.com", "manager")
    assign_restaurant(configured_client, manager["id"], other["id"])
    manager_token = login(configured_client, manager["email"])

    response = configured_client.get("/v1/evidence-tasks", headers=auth_headers(manager_token))

    assert response.status_code == 200
    assert response.json()["tasks"] == []


def test_staff_cannot_recalculate(configured_client: TestClient) -> None:
    staff = create_user(configured_client, "staff-no-recalc@example.com", "staff")
    staff_token = login(configured_client, staff["email"])

    response = configured_client.post("/v1/evidence-tasks/recalculate", json={}, headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_staff_assigned_can_upload_task(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.required_evidence_type == "cancellation_proof"))
    assert task is not None
    staff = create_user(configured_client, "staff-evidence@example.com", "staff")
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = upload_task_file(configured_client, task.id, staff_token)

    assert response.status_code == 201
    data = response.json()
    assert data["task"]["status"] == "completed"
    assert data["evidence_file"]["uploaded_by_user_id"] == staff["id"]
    assert data["evidence_file"]["evidence_type"] == "cancellation_proof"


def test_staff_non_assigned_cannot_upload_task(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    staff = create_user(configured_client, "staff-unassigned-evidence@example.com", "staff")
    staff_token = login(configured_client, staff["email"])

    response = upload_task_file(configured_client, task.id, staff_token)

    assert response.status_code == 403


def test_task_upload_validates_order_when_all_proofs_present(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], loss_type=None)
    add_metadata_evidence(configured_client, order["id"], "preparation_proof")
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.required_evidence_type == "cancellation_proof"))
    assert task is not None

    response = upload_task_file(configured_client, task.id)

    assert response.status_code == 201
    assert response.json()["validation"]["is_complete"] is True
    assert response.json()["validation"]["new_status"] == "ready_to_send"


def test_create_upload_link_returns_token_once_and_stores_hash(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None

    response = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={})

    assert response.status_code == 201
    data = response.json()
    assert data["token"]
    assert data["upload_url"].endswith(data["token"])
    link = db_session.get(EvidenceUploadLink, data["id"])
    assert link is not None
    assert link.token_hash != data["token"]
    assert len(link.token_hash) == 64


def test_print_ticket_creates_single_use_upload_link_with_qr(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None

    response = configured_client.post(f"/v1/evidence-tasks/{task.id}/print-ticket", json={})

    assert response.status_code == 201
    data = response.json()
    assert data["task_id"] == task.id
    assert data["restaurant_name"] == restaurant["name"]
    assert data["required_evidence_label"]
    assert data["ticket_reference"].startswith(f"TENNET-{task.id}-")
    assert "/evidence-upload/" in data["upload_url"]
    assert "<svg" in data["qr_svg"]
    assert data["upload_url"] in data["print_html"]
    assert "Ticket preuve terrain" in data["print_html"]
    upload_link = db_session.get(EvidenceUploadLink, data["upload_link"]["id"])
    assert upload_link is not None
    assert upload_link.max_uses == 1
    assert upload_link.token_hash not in data["print_html"]
    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "evidence_upload_link.created" in actions
    assert "evidence_print_ticket.created" in actions


def test_staff_assigned_can_create_print_ticket(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    staff = create_user(configured_client, "staff-print-ticket@example.com", "staff")
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = configured_client.post(
        f"/v1/evidence-tasks/{task.id}/print-ticket",
        json={},
        headers=auth_headers(staff_token),
    )

    assert response.status_code == 201
    assert response.json()["upload_link"]["max_uses"] == 1


def test_live_evidence_station_returns_prioritized_active_tasks(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    urgent_task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.required_evidence_type == "waste_photo"))
    normal_task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.required_evidence_type == "cancellation_proof"))
    assert urgent_task is not None
    assert normal_task is not None
    urgent_task.priority = "urgent"
    normal_task.priority = "normal"
    db_session.commit()

    response = configured_client.get("/v1/live-evidence/station")

    assert response.status_code == 200
    data = response.json()
    assert data["total_active_tasks"] == 2
    assert data["urgent_count"] == 1
    assert data["recommended_task_id"] == urgent_task.id
    assert [task["id"] for task in data["tasks"]][0] == urgent_task.id
    assert data["printer_mode"] == "browser_print"
    assert data["bluetooth_supported"] is True
    assert data["native_print_modes"] == ["android_bluetooth_escpos"]
    assert data["native_print_contract_version"] == "2026-06-12.android-escpos.v1"
    assert data["camera_capture_supported"] is True
    assert data["native_printer_bridge_ready"] is True
    assert "print-ticket" in data["native_printer_bridge_contract"]
    assert any("Ne jamais lire" in rule for rule in data["safe_capture_rules"])
    assert "storage_path" not in str(data)


def test_live_evidence_station_respects_staff_restaurant_access(configured_client: TestClient) -> None:
    visible_restaurant = create_restaurant(configured_client, "Visible Station")
    create_order(configured_client, visible_restaurant["id"], "UBER-STATION-VISIBLE")
    hidden_restaurant = create_restaurant(configured_client, "Hidden Station")
    create_order(configured_client, hidden_restaurant["id"], "UBER-STATION-HIDDEN")
    recalculate(configured_client)
    staff = create_user(configured_client, "staff-live-station@example.com", "staff")
    assign_restaurant(configured_client, staff["id"], visible_restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = configured_client.get("/v1/live-evidence/station", headers=auth_headers(staff_token))

    assert response.status_code == 200
    order_numbers = {task["uber_order_number"] for task in response.json()["tasks"]}
    assert order_numbers == {"UBER-STATION-VISIBLE"}


def test_live_evidence_station_rejects_unassigned_restaurant_filter(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    other_restaurant = create_restaurant(configured_client, "Other Station")
    staff = create_user(configured_client, "staff-live-station-denied@example.com", "staff")
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = configured_client.get(
        f"/v1/live-evidence/station?restaurant_id={other_restaurant['id']}",
        headers=auth_headers(staff_token),
    )

    assert response.status_code == 403


def test_staff_non_assigned_cannot_create_print_ticket(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    staff = create_user(configured_client, "staff-print-ticket-denied@example.com", "staff")
    staff_token = login(configured_client, staff["email"])

    response = configured_client.post(
        f"/v1/evidence-tasks/{task.id}/print-ticket",
        json={},
        headers=auth_headers(staff_token),
    )

    assert response.status_code == 403


def test_upload_link_refuses_staff(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    staff = create_user(configured_client, "staff-no-link@example.com", "staff")
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={}, headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_public_upload_link_metadata_is_available(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task_id = configured_client.get("/v1/evidence-tasks").json()["tasks"][0]["id"]
    token = configured_client.post(f"/v1/evidence-tasks/{task_id}/upload-link", json={}).json()["token"]

    response = configured_client.get(f"/v1/evidence-upload-links/{token}", headers={})

    assert response.status_code == 200
    data = response.json()
    assert data["required_evidence_type"]
    assert data["uber_order_number"].startswith("UBER...")
    assert data["title"]


def test_public_upload_link_upload_completes_task(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    token = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={}).json()["token"]

    response = configured_client.post(
        f"/v1/evidence-upload-links/{token}/upload",
        files={"file": ("preuve.png", b"image-content", "image/png")},
        headers={},
    )

    assert response.status_code == 201
    assert response.json()["task"]["status"] == "completed"
    link = db_session.scalar(select(EvidenceUploadLink))
    assert link is not None
    assert link.use_count == 1


def test_public_upload_link_refuses_second_use(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    token = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={}).json()["token"]
    first = configured_client.post(
        f"/v1/evidence-upload-links/{token}/upload",
        files={"file": ("preuve.png", b"image-content", "image/png")},
        headers={},
    )
    assert first.status_code == 201

    second = configured_client.post(
        f"/v1/evidence-upload-links/{token}/upload",
        files={"file": ("preuve.png", b"image-content", "image/png")},
        headers={},
    )

    assert second.status_code in {409, 410}


def test_revoke_upload_link_blocks_public_access(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    link_data = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={}).json()

    revoke_response = configured_client.post(f"/v1/evidence-upload-links/{link_data['id']}/revoke")
    public_response = configured_client.get(f"/v1/evidence-upload-links/{link_data['token']}", headers={})

    assert revoke_response.status_code == 200
    assert public_response.status_code == 410


def test_expired_upload_link_is_rejected(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    token = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={}).json()["token"]
    link = db_session.scalar(select(EvidenceUploadLink))
    assert link is not None
    link.expires_at = utc_now().replace(tzinfo=None)
    db_session.commit()

    response = configured_client.get(f"/v1/evidence-upload-links/{token}", headers={})

    assert response.status_code == 410


def test_skip_and_complete_task(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    tasks = db_session.scalars(select(EvidenceRequestTask).order_by(EvidenceRequestTask.id)).all()
    assert len(tasks) == 2

    skip_response = configured_client.post(
        f"/v1/evidence-tasks/{tasks[0].id}/skip",
        json={"skip_reason": "Preuve impossible a fournir"},
    )
    complete_response = configured_client.post(f"/v1/evidence-tasks/{tasks[1].id}/complete")

    assert skip_response.status_code == 200
    assert skip_response.json()["status"] == "skipped"
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"


def test_reconciliation_result_sets_priority(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], amount="140.00")
    result = UberReconciliationResult(
        restaurant_id=restaurant["id"],
        uber_order_id=order["uber_order_number"],
        claim_order_id=order["id"],
        status="not_compensated",
        reason="canceled_no_payment_found",
        order_amount="140.00",
        paid_amount="0",
        refunded_amount="0",
        missing_amount="140.00",
        currency="EUR",
        evidence_required=True,
    )
    db_session.add(result)
    db_session.commit()

    recalculate(configured_client)

    task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.reconciliation_result_id == result.id))
    assert task is not None
    assert task.priority == "urgent"


def test_audit_logs_created_for_recalculate_upload_link_and_upload(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"])
    recalculate(configured_client)
    task = db_session.scalar(select(EvidenceRequestTask))
    assert task is not None
    token = configured_client.post(f"/v1/evidence-tasks/{task.id}/upload-link", json={}).json()["token"]

    configured_client.post(
        f"/v1/evidence-upload-links/{token}/upload",
        files={"file": ("preuve.png", b"image-content", "image/png")},
        headers={},
    )

    actions = set(db_session.scalars(select(AuditLog.action)).all())
    assert "evidence_task.recalculate" in actions
    assert "evidence_upload_link.created" in actions
    assert "evidence_file.uploaded_from_task" in actions
    assert "evidence_task.completed_by_upload" in actions
