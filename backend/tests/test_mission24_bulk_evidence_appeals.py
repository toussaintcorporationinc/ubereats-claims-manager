from __future__ import annotations

from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AppealAttempt,
    AppealWorkflow,
    AuditLog,
    CustomerRefundDisputeReview,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EvidenceFile,
    EvidenceImportBatch,
    EvidenceImportedFile,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    User,
)
from app.models.domain import utc_now


FORBIDDEN_UBER_VISIBLE_TERMS = [
    "TENNET",
    "Historique",
    "Mots cles",
    "generic_refusal",
    "dispute_type",
    "Raison detectee",
    "Extrait / notes",
]


def assert_clean_uber_email(subject: str, body: str) -> None:
    combined = f"{subject}\n{body}"
    for term in FORBIDDEN_UBER_VISIBLE_TERMS:
        assert term not in combined


@pytest.fixture()
def bulk_evidence_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    storage_dir = tmp_path / "evidence"
    monkeypatch.setenv("EVIDENCE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("BULK_EVIDENCE_MAX_FILE_SIZE_MB", "1")
    monkeypatch.setenv("BULK_EVIDENCE_MAX_ZIP_SIZE_MB", "1")
    monkeypatch.setenv("AI_EVIDENCE_ANALYSIS_ENABLED", "false")
    monkeypatch.setenv("AI_EVIDENCE_AUTO_ATTACH_ENABLED", "false")
    get_settings.cache_clear()
    yield storage_dir
    get_settings.cache_clear()


@pytest.fixture()
def configured_client(bulk_evidence_storage: Path, client: TestClient) -> TestClient:
    return client


def create_restaurant(client: TestClient, name: str = "Mission 24 Restaurant") -> dict:
    response = client.post("/v1/restaurants", json={"name": name, "sender_email": "claims@example.com"})
    assert response.status_code == 201
    return response.json()


def create_order(
    client: TestClient,
    restaurant_id: int,
    uber_order_number: str = "UBER-BULK-001",
    status: str = "response_received",
) -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": uber_order_number,
            "order_amount": "24.50",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
            "status": status,
        },
    )
    assert response.status_code == 201
    return response.json()


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for filename, content in entries.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


def post_refused_review(client: TestClient, order_id: int, refusal_reason: str = "Generic refusal") -> dict:
    response = client.post(
        f"/v1/orders/{order_id}/response-reviews",
        json={
            "review_type": "refused",
            "refusal_reason": refusal_reason,
            "notes": "Uber refused the claim.",
        },
    )
    assert response.status_code == 201
    return response.json()


def connect_owner_gmail_account(db_session: Session) -> None:
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    db_session.add(
        EmailAccount(
            user_id=owner.id,
            provider="gmail",
            email_address="owner@example.com",
            access_token_encrypted="fake-access-token",
            refresh_token_encrypted="fake-refresh-token",
            scopes="https://www.googleapis.com/auth/gmail.compose",
            connected_at=utc_now(),
        )
    )
    db_session.commit()


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_zip_valid_extracts_files(configured_client: TestClient) -> None:
    payload = make_zip({"receipt_UBER-BULK-001.pdf": b"receipt UBER-BULK-001 24.50"})

    response = configured_client.post(
        "/v1/evidence-imports/zip",
        files={"file": ("bulk.zip", payload, "application/zip")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "zip_upload"
    assert data["stored_files_count"] == 1
    assert data["status"] == "stored"


def test_multi_file_import_removes_exact_duplicate_after_checksum_analysis(
    configured_client: TestClient,
    bulk_evidence_storage: Path,
    db_session: Session,
) -> None:
    response = configured_client.post(
        "/v1/evidence-imports",
        files=[
            ("files", ("receipt-a.pdf", b"same receipt payload", "application/pdf")),
            ("files", ("receipt-copy.pdf", b"same receipt payload", "application/pdf")),
            ("files", ("receipt-b.pdf", b"different receipt payload", "application/pdf")),
        ],
    )

    assert response.status_code == 201
    data = response.json()
    assert data["total_files"] == 3
    assert data["stored_files_count"] == 2
    assert data["duplicate_files_count"] == 1
    assert data["failed_files_count"] == 0
    assert "duplicate_removed" in data["error_message"]

    batch = db_session.get(EvidenceImportBatch, data["id"])
    assert batch is not None
    assert batch.duplicate_files_count == 1
    assert len(batch.files) == 3
    assert len([file for file in batch.files if file.status == "ignored"]) == 1
    assert len(list((bulk_evidence_storage / "bulk_imports" / f"batch_{batch.id}").iterdir())) == 2
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "evidence_import_batch",
            AuditLog.entity_id == batch.id,
            AuditLog.action == "evidence_import_file.duplicate_removed",
        )
    )


def test_zip_import_removes_exact_duplicate_member(
    configured_client: TestClient,
    bulk_evidence_storage: Path,
    db_session: Session,
) -> None:
    payload = make_zip(
        {
            "receipt-a.pdf": b"same zip receipt payload",
            "copy/receipt-a.pdf": b"same zip receipt payload",
        }
    )

    response = configured_client.post(
        "/v1/evidence-imports/zip",
        files={"file": ("bulk.zip", payload, "application/zip")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["total_files"] == 2
    assert data["stored_files_count"] == 1
    assert data["duplicate_files_count"] == 1
    batch = db_session.get(EvidenceImportBatch, data["id"])
    assert batch is not None
    assert len(batch.files) == 2
    assert len([file for file in batch.files if file.status == "ignored"]) == 1
    assert len(list((bulk_evidence_storage / "bulk_imports" / f"batch_{batch.id}").iterdir())) == 1


def test_import_removes_duplicate_already_stored_for_same_restaurant(
    configured_client: TestClient,
    bulk_evidence_storage: Path,
    db_session: Session,
) -> None:
    restaurant = create_restaurant(configured_client)
    first = configured_client.post(
        "/v1/evidence-imports",
        files=[("files", ("receipt-master.pdf", b"restaurant duplicate payload", "application/pdf"))],
        data={"restaurant_id": str(restaurant["id"])},
    )
    assert first.status_code == 201

    second = configured_client.post(
        "/v1/evidence-imports",
        files=[("files", ("receipt-again.pdf", b"restaurant duplicate payload", "application/pdf"))],
        data={"restaurant_id": str(restaurant["id"])},
    )

    assert second.status_code == 201
    data = second.json()
    assert data["total_files"] == 1
    assert data["stored_files_count"] == 0
    assert data["duplicate_files_count"] == 1
    assert data["status"] == "analyzed"
    assert "duplicate_existing_import_checksum" in data["error_message"]

    batch = db_session.get(EvidenceImportBatch, data["id"])
    assert batch is not None
    assert len(batch.files) == 1
    duplicate_file = batch.files[0]
    assert duplicate_file.status == "ignored"
    assert duplicate_file.original_filename == "receipt-again.pdf"
    assert len(list((bulk_evidence_storage / "bulk_imports" / f"batch_{batch.id}").iterdir())) == 0
    assert db_session.scalar(select(EvidenceImportedFile).where(EvidenceImportedFile.batch_id == batch.id)) is not None


def test_zip_path_traversal_refused(configured_client: TestClient) -> None:
    payload = make_zip({"../evil.pdf": b"bad"})

    response = configured_client.post(
        "/v1/evidence-imports/zip",
        files={"file": ("bulk.zip", payload, "application/zip")},
    )

    assert response.status_code == 400
    assert "path traversal" in response.json()["detail"]


def test_fake_analysis_creates_result_and_exact_order_candidate(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    create_order(configured_client, restaurant["id"], "UBER-BULK-001")
    response = configured_client.post(
        "/v1/evidence-imports",
        files=[("files", ("receipt_UBER-BULK-001.pdf", b"receipt UBER-BULK-001 24.50", "application/pdf"))],
        data={"restaurant_id": str(restaurant["id"])},
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    analyze_response = configured_client.post(f"/v1/evidence-imports/{batch_id}/analyze", json={"provider": "fake", "limit": 10})

    assert analyze_response.status_code == 200
    files_response = configured_client.get(f"/v1/evidence-imports/{batch_id}/files")
    file_id = files_response.json()["files"][0]["id"]
    detail = configured_client.get(f"/v1/evidence-imported-files/{file_id}").json()
    assert detail["analysis_results"][0]["detected_evidence_type"] == "receipt"
    assert any(candidate["match_reason"] == "exact_order_number" for candidate in detail["candidates"])
    assert all(candidate["status"] != "auto_attached" for candidate in detail["candidates"])


def test_attach_completes_evidence_task_and_runs_validation(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order_data = create_order(configured_client, restaurant["id"], "UBER-BULK-TASK")
    task = EvidenceRequestTask(
        order_id=order_data["id"],
        restaurant_id=restaurant["id"],
        task_type="missing_receipt",
        required_evidence_type="receipt",
        status="pending",
        priority="normal",
        title="Ticket requis",
        reason="mission_24_test",
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    response = configured_client.post(
        "/v1/evidence-imports",
        files=[("files", ("receipt_UBER-BULK-TASK.pdf", b"receipt UBER-BULK-TASK 24.50", "application/pdf"))],
        data={"restaurant_id": str(restaurant["id"])},
    )
    batch_id = response.json()["id"]
    analyze_response = configured_client.post(f"/v1/evidence-imports/{batch_id}/analyze", json={"provider": "fake", "limit": 10})
    assert analyze_response.status_code == 200
    assert analyze_response.json()["auto_matched_count"] == 1
    file_id = configured_client.get(f"/v1/evidence-imports/{batch_id}/files").json()["files"][0]["id"]
    detail = configured_client.get(f"/v1/evidence-imported-files/{file_id}").json()

    db_session.refresh(task)
    assert task.status == "completed"
    assert db_session.scalar(select(EvidenceFile).where(EvidenceFile.order_id == order_data["id"])) is not None
    assert any(candidate["status"] == "auto_attached" for candidate in detail["candidates"])


def test_refused_claim_response_review_creates_appeal_workflow(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-001")

    post_refused_review(configured_client, order["id"], "Refus generique")

    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order["id"]))
    assert workflow is not None
    assert workflow.status == "appeal_needed"
    assert workflow.next_action_type == "create_appeal_draft"
    assert workflow.refusal_count == 1

    recovery = configured_client.get("/v1/recovery/summary").json()
    assert recovery["totals"]["active_appeals_count"] >= 1


def test_refused_customer_refund_review_creates_appeal_workflow(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    dispute = UberCustomerRefundDispute(
        restaurant_id=restaurant["id"],
        dispute_type="customer_refund",
        reason="unknown_reason",
        status="sent",
        customer_refund_amount="12.50",
        currency="EUR",
        evidence_required=True,
        evidence_status="complete",
    )
    db_session.add(dispute)
    db_session.commit()
    db_session.refresh(dispute)

    response = configured_client.post(
        f"/v1/customer-refunds/{dispute.id}/reviews",
        json={"review_type": "refused", "refusal_reason": "Refus remboursement client"},
    )

    assert response.status_code == 201
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.customer_refund_dispute_id == dispute.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"
    assert db_session.scalar(select(CustomerRefundDisputeReview).where(CustomerRefundDisputeReview.dispute_id == dispute.id)) is not None


def test_appeal_gmail_draft_refuses_when_provider_disabled(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-GMAIL-OFF")
    post_refused_review(configured_client, order["id"], "Merci de fournir une preuve")
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order["id"]))
    assert workflow is not None

    draft_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-draft", json={"appeal_type": "evidence_reply"})
    assert draft_response.status_code == 201
    attempt = db_session.scalar(select(AppealAttempt).where(AppealAttempt.workflow_id == workflow.id))
    assert attempt is not None
    before_status = workflow.status
    before_attempt_status = attempt.status

    gmail_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-gmail-draft")

    assert gmail_response.status_code == 503
    assert gmail_response.json()["detail"] == "email_provider_disabled"
    db_session.refresh(workflow)
    db_session.refresh(attempt)
    assert workflow.status == before_status
    assert attempt.status == before_attempt_status
    assert attempt.provider_draft_id is None
    assert db_session.scalar(select(EmailProviderDraft)) is None


def test_appeal_gmail_draft_refuses_without_connected_account(
    configured_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    get_settings.cache_clear()
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-NO-GMAIL")
    post_refused_review(configured_client, order["id"], "Merci de fournir une preuve")
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order["id"]))
    assert workflow is not None
    draft_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-draft", json={"appeal_type": "evidence_reply"})
    assert draft_response.status_code == 201
    attempt = db_session.scalar(select(AppealAttempt).where(AppealAttempt.workflow_id == workflow.id))
    assert attempt is not None

    gmail_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-gmail-draft")

    assert gmail_response.status_code == 409
    assert gmail_response.json()["detail"] == "gmail_account_not_connected"
    db_session.refresh(attempt)
    assert attempt.status == "draft_created"
    assert attempt.provider_draft_id is None
    assert db_session.scalar(select(EmailProviderDraft)) is None
    get_settings.cache_clear()


def test_appeal_draft_gmail_draft_and_mark_sent_are_controlled(
    configured_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    get_settings.cache_clear()
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-DRAFT")
    post_refused_review(configured_client, order["id"], "Merci de fournir une preuve")
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order["id"]))
    assert workflow is not None
    connect_owner_gmail_account(db_session)

    draft_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-draft", json={"appeal_type": "evidence_reply"})
    assert draft_response.status_code == 201
    draft_payload = draft_response.json()
    email_draft = db_session.get(EmailDraft, draft_payload["email_draft_id"])
    assert email_draft is not None
    assert "Reexamen" in email_draft.subject or "Preuves complementaires" in email_draft.subject
    assert "Merci d'indiquer precisement les pieces attendues" in email_draft.body
    assert_clean_uber_email(email_draft.subject, email_draft.body)
    gmail_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-gmail-draft")
    assert gmail_response.status_code == 201
    sent_response = configured_client.post(f"/v1/appeals/{workflow.id}/mark-sent")
    assert sent_response.status_code == 200

    db_session.refresh(workflow)
    assert workflow.appeal_attempt_count == 1
    attempt = db_session.scalar(select(AppealAttempt).where(AppealAttempt.workflow_id == workflow.id))
    assert attempt is not None
    assert attempt.status == "sent"

    duplicate_response = configured_client.post(f"/v1/appeals/{workflow.id}/create-draft", json={"appeal_type": "evidence_reply"})
    assert duplicate_response.status_code == 409
    get_settings.cache_clear()


def test_payment_confirmed_syncs_workflow_to_terminal(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-PAID")
    post_refused_review(configured_client, order["id"])
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order["id"]))
    assert workflow is not None

    response = configured_client.post(
        f"/v1/orders/{order['id']}/response-reviews",
        json={"review_type": "payment_confirmed", "recovered_amount": "24.50"},
    )

    assert response.status_code == 201
    db_session.refresh(workflow)
    assert workflow.status == "payment_confirmed"


def test_appeal_audit_logs_created(configured_client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-AUDIT")
    post_refused_review(configured_client, order["id"])
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order["id"]))
    assert workflow is not None

    assert (
        db_session.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "appeal_workflow",
                AuditLog.entity_id == workflow.id,
            )
        )
        is not None
    )


def test_staff_cannot_create_appeal_draft(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    order = create_order(configured_client, restaurant["id"], "UBER-APPEAL-STAFF")
    post_refused_review(configured_client, order["id"])
    workflow_id = configured_client.get("/v1/appeals").json()["workflows"][0]["id"]
    staff_response = configured_client.post(
        "/v1/users",
        json={
            "email": "staff-appeal@example.com",
            "password": "staff-password",
            "full_name": "Staff Appeal",
            "role": "staff",
            "active": True,
        },
    )
    assert staff_response.status_code == 201
    assign_response = configured_client.post(f"/v1/users/{staff_response.json()['id']}/restaurants", json={"restaurant_id": restaurant["id"]})
    assert assign_response.status_code == 201
    login_response = configured_client.post("/v1/auth/login", json={"email": "staff-appeal@example.com", "password": "staff-password"})
    staff_token = login_response.json()["access_token"]

    response = configured_client.post(
        f"/v1/appeals/{workflow_id}/create-draft",
        json={"appeal_type": "first_appeal"},
        headers={"Authorization": f"Bearer {staff_token}"},
    )

    assert response.status_code == 403


def test_no_openai_real_call_when_disabled(configured_client: TestClient) -> None:
    restaurant = create_restaurant(configured_client)
    response = configured_client.post(
        "/v1/evidence-imports",
        files=[("files", ("receipt.pdf", b"receipt UBER-NO-OPENAI 10.00", "application/pdf"))],
        data={"restaurant_id": str(restaurant["id"])},
    )
    batch_id = response.json()["id"]

    analyze_response = configured_client.post(f"/v1/evidence-imports/{batch_id}/analyze", json={"provider": "openai_vision", "limit": 1})

    assert analyze_response.status_code == 503
