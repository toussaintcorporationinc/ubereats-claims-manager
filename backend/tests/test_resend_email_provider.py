from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuditLog, EmailProviderDraft, EmailThread
from app.routes.email import get_resend_provider
from app.services.email_draft_service import create_email_draft
from app.services.resend_email_provider import ResendEmailProvider
from app.main import app


class FakeResendProvider(ResendEmailProvider):
    sent_payloads: list[dict]

    def __init__(self) -> None:
        self.sent_payloads = []

    def send_resend_email(self, email_draft, to_email, attachments):  # type: ignore[no-untyped-def]
        self.sent_payloads.append(
            {
                "subject": email_draft.subject,
                "to_email": to_email,
                "attachments": len(attachments),
            }
        )
        return {"id": "resend-message-test"}


@pytest.fixture()
def resend_enabled(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("RESEND_ENABLED", "true")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "TENNET <notifications@mail.thetennet.com>")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake_resend_provider() -> Generator[FakeResendProvider, None, None]:
    provider = FakeResendProvider()
    app.dependency_overrides[get_resend_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_resend_provider, None)


def create_restaurant(client: TestClient) -> dict:
    response = client.post("/v1/restaurants", json={"name": "Resend Restaurant", "sender_email": "claims@example.com"})
    assert response.status_code == 201
    return response.json()


def create_ready_draft(client: TestClient, db_session: Session) -> int:
    restaurant = create_restaurant(client)
    order_response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant["id"],
            "uber_order_number": "RESEND-001",
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
        },
    )
    assert order_response.status_code == 201
    order = order_response.json()
    for evidence_type in ("cancellation_proof", "preparation_proof"):
        evidence_response = client.post(
            f"/v1/orders/{order['id']}/evidence",
            json={
                "evidence_type": evidence_type,
                "original_filename": f"{evidence_type}.txt",
                "storage_path": f"storage/evidence/{evidence_type}.txt",
                "mime_type": "text/plain",
                "file_size": 16,
            },
        )
        assert evidence_response.status_code == 201
    validate_response = client.post(f"/v1/orders/{order['id']}/validate")
    assert validate_response.status_code == 200
    draft = create_email_draft(db_session, order["id"], "initial_claim", user_id=1)
    db_session.commit()
    return draft.id


def test_resend_status_disabled_by_default(client: TestClient) -> None:
    response = client.get("/v1/email/resend/status")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "email_address": None, "provider": "resend", "enabled": False}


def test_resend_send_refuses_when_disabled(client: TestClient, db_session: Session) -> None:
    draft_id = create_ready_draft(client, db_session)

    response = client.post(f"/v1/drafts/{draft_id}/resend-send", json={"confirm_send": True})

    assert response.status_code == 503
    assert response.json()["detail"] == "Email provider is disabled"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.provider == "resend")) is None


def test_resend_send_requires_manual_confirmation(
    client: TestClient,
    db_session: Session,
    resend_enabled: None,
    fake_resend_provider: FakeResendProvider,
) -> None:
    draft_id = create_ready_draft(client, db_session)

    response = client.post(f"/v1/drafts/{draft_id}/resend-send", json={"confirm_send": False})

    assert response.status_code == 400
    assert response.json()["detail"] == "confirm_send must be true"
    assert fake_resend_provider.sent_payloads == []


def test_resend_manual_send_records_provider_draft_thread_and_audit(
    client: TestClient,
    db_session: Session,
    resend_enabled: None,
    fake_resend_provider: FakeResendProvider,
) -> None:
    draft_id = create_ready_draft(client, db_session)

    response = client.post(
        f"/v1/drafts/{draft_id}/resend-send",
        json={"confirm_send": True, "to_email": "merchants@uber.com", "include_evidence": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "resend"
    assert data["status"] == "sent"
    assert data["provider_message_id"] == "resend-message-test"
    assert fake_resend_provider.sent_payloads == [
        {"subject": data["subject"], "to_email": "merchants@uber.com", "attachments": 0}
    ]
    assert db_session.scalar(select(EmailThread).where(EmailThread.provider == "resend")) is not None
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "send_resend_email")) is not None
