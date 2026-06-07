from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuditLog


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


@pytest.fixture()
def configured_unauthenticated_client(
    evidence_storage: Path,
    unauthenticated_client: TestClient,
) -> TestClient:
    return unauthenticated_client


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def owner_token(client: TestClient) -> str:
    return client.headers["Authorization"].replace("Bearer ", "")


def create_restaurant(client: TestClient, name: str = "Evidence Restaurant") -> dict:
    response = client.post(
        "/v1/restaurants",
        json={"name": name, "sender_email": "claims@example.com"},
    )
    assert response.status_code == 201
    return response.json()


def create_order(client: TestClient, restaurant_id: int, uber_order_number: str = "UBER-EVIDENCE-1") -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": uber_order_number,
            "order_amount": "24.50",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_staff_user(client: TestClient, email: str = "staff@example.com") -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "staff-password",
            "full_name": "Staff Evidence",
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


def upload_evidence(
    client: TestClient,
    order_id: int,
    evidence_type: str,
    filename: str = "preuve.png",
    content: bytes = b"image-content",
    mime_type: str = "image/png",
    token: str | None = None,
):
    return client.post(
        f"/v1/orders/{order_id}/evidence/upload",
        data={"evidence_type": evidence_type},
        files={"file": (filename, content, mime_type)},
        headers=auth_headers(token) if token else None,
    )


def test_health_public_works(configured_unauthenticated_client: TestClient) -> None:
    response = configured_unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_receipt_ok_owner(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    response = upload_evidence(configured_client, order["id"], "receipt", "ticket.pdf", b"%PDF-1.4", "application/pdf")

    assert response.status_code == 201
    data = response.json()
    assert data["evidence_type"] == "receipt"
    assert data["original_filename"] == "ticket.pdf"
    assert data["file_size"] == len(b"%PDF-1.4")
    assert data["checksum_sha256"]
    assert data["download_url"] == f"/v1/evidence/{data['id']}/download"
    assert not data["storage_path"].startswith("/")


def test_upload_cancellation_preparation_and_waste_ok_owner(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    cancellation = upload_evidence(configured_client, order["id"], "cancellation_proof")
    preparation = upload_evidence(configured_client, order["id"], "preparation_proof")
    waste = upload_evidence(configured_client, order["id"], "waste_photo")

    assert cancellation.status_code == 201
    assert preparation.status_code == 201
    assert waste.status_code == 201


def test_upload_empty_file_is_rejected(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    response = upload_evidence(configured_client, order["id"], "receipt", "empty.pdf", b"", "application/pdf")

    assert response.status_code == 400


def test_upload_forbidden_extension_is_rejected(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    response = upload_evidence(configured_client, order["id"], "receipt", "notes.txt", b"proof", "text/plain")

    assert response.status_code == 400


def test_upload_invalid_evidence_type_is_rejected(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    response = upload_evidence(configured_client, order["id"], "invoice")

    assert response.status_code == 422


def test_upload_unknown_order_is_rejected(configured_client: TestClient) -> None:
    response = upload_evidence(configured_client, 9999, "receipt")

    assert response.status_code == 404


def test_staff_assigned_can_upload(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    staff = create_staff_user(configured_client)
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = upload_evidence(configured_client, order["id"], "receipt", token=staff_token)

    assert response.status_code == 201
    assert response.json()["uploaded_by_user_id"] == staff["id"]


def test_staff_not_assigned_cannot_upload(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    staff = create_staff_user(configured_client, "unassigned@example.com")
    staff_token = login(configured_client, staff["email"])

    response = upload_evidence(configured_client, order["id"], "receipt", token=staff_token)

    assert response.status_code == 403


def test_download_owner_ok(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    upload = upload_evidence(configured_client, order["id"], "receipt", content=b"download-me")
    evidence_id = upload.json()["id"]

    response = configured_client.get(f"/v1/evidence/{evidence_id}/download")

    assert response.status_code == 200
    assert response.content == b"download-me"


def test_download_staff_assigned_ok(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    upload = upload_evidence(configured_client, order["id"], "receipt", content=b"staff-download")
    evidence_id = upload.json()["id"]
    staff = create_staff_user(configured_client)
    assign_restaurant(configured_client, staff["id"], restaurant["id"])
    staff_token = login(configured_client, staff["email"])

    response = configured_client.get(f"/v1/evidence/{evidence_id}/download", headers=auth_headers(staff_token))

    assert response.status_code == 200
    assert response.content == b"staff-download"


def test_download_staff_not_assigned_is_rejected(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    upload = upload_evidence(configured_client, order["id"], "receipt")
    evidence_id = upload.json()["id"]
    staff = create_staff_user(configured_client, "download-unassigned@example.com")
    staff_token = login(configured_client, staff["email"])

    response = configured_client.get(f"/v1/evidence/{evidence_id}/download", headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_list_evidence_returns_checksum(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    upload_evidence(configured_client, order["id"], "receipt")

    response = configured_client.get(f"/v1/orders/{order['id']}/evidence")

    assert response.status_code == 200
    assert response.json()[0]["checksum_sha256"]


def test_audit_log_created_after_upload(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])

    upload_evidence(configured_client, order["id"], "receipt")

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "evidence_file",
            AuditLog.action == "evidence_file.uploaded",
        )
    )
    assert audit_log is not None


def test_claim_validation_works_with_uploaded_evidence(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"])
    upload_evidence(configured_client, order["id"], "cancellation_proof")
    upload_evidence(configured_client, order["id"], "preparation_proof")

    response = configured_client.post(f"/v1/orders/{order['id']}/validate")

    assert response.status_code == 200
    assert response.json()["is_complete"] is True
    assert response.json()["new_status"] == "ready_to_send"
