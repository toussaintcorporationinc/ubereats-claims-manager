from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models import AuditLog, EmailAccount, EmailDraft, EmailProviderDraft, User
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.services.email_provider import EmailConnectionStatus, EmailProviderError


def get_active_account(db: Session, user_id: int) -> EmailAccount | None:
    return db.scalar(
        select(EmailAccount).where(
            EmailAccount.user_id == user_id,
            EmailAccount.provider == "gmail",
            EmailAccount.disconnected_at.is_(None),
        )
    )


class FakeGmailEmailProvider:
    provider = "gmail"

    def __init__(self) -> None:
        self.last_include_evidence = False
        self.last_evidence_count = 0

    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        if not get_settings().email_provider_enabled:
            return EmailConnectionStatus(connected=False, provider=self.provider, email_address=None, enabled=False)
        account = get_active_account(db, user.id)
        return EmailConnectionStatus(
            connected=account is not None,
            provider=self.provider,
            email_address=account.email_address if account else None,
            enabled=True,
        )

    def disconnect(self, db: Session, user: User) -> None:
        account = get_active_account(db, user.id)
        if account:
            account.disconnected_at = utc_now()

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        if not get_settings().email_provider_enabled:
            raise EmailProviderError("Email provider is disabled", 503)
        if get_active_account(db, user.id) is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        self.last_include_evidence = include_evidence
        self.last_evidence_count = len([item for item in email_draft.order.evidence_files if item.deleted_at is None])
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            provider="gmail",
            provider_draft_id=f"fake-gmail-draft-{email_draft.id}",
            provider_thread_id=f"fake-thread-{email_draft.id}",
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        return provider_draft


@pytest.fixture()
def gmail_enabled(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/v1/email/gmail/oauth/callback")
    monkeypatch.setenv("GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.compose")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake_gmail_provider() -> Generator[FakeGmailEmailProvider, None, None]:
    provider = FakeGmailEmailProvider()
    app.dependency_overrides[get_gmail_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_gmail_provider, None)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_restaurant(client: TestClient, name: str = "Gmail Restaurant") -> dict:
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


def create_ready_order_and_draft(client: TestClient, restaurant_id: int, order_number: str = "UBER-GMAIL-1") -> dict:
    order_response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
        },
    )
    assert order_response.status_code == 201
    order = order_response.json()
    add_evidence(client, order["id"], "cancellation_proof")
    add_evidence(client, order["id"], "preparation_proof")
    validate_response = client.post(f"/v1/orders/{order['id']}/validate")
    assert validate_response.status_code == 200
    draft_response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "initial_claim"})
    assert draft_response.status_code == 201
    return draft_response.json()


def add_evidence(client: TestClient, order_id: int, evidence_type: str) -> None:
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


def get_user(db_session: Session, email: str) -> User:
    user = db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def connect_gmail_account(db_session: Session, user_id: int, email_address: str = "connected@example.com") -> None:
    db_session.add(
        EmailAccount(
            user_id=user_id,
            provider="gmail",
            email_address=email_address,
            access_token_encrypted="encrypted-access-token",
            refresh_token_encrypted="encrypted-refresh-token",
            scopes="https://www.googleapis.com/auth/gmail.compose",
        )
    )
    db_session.commit()


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_gmail_status_not_connected_returns_false(
    client: TestClient,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    response = client.get("/v1/email/gmail/status")

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["provider"] == "gmail"
    assert data["email_address"] is None


def test_oauth_start_refuses_if_provider_disabled(client: TestClient) -> None:
    response = client.get("/v1/email/gmail/oauth/start")

    assert response.status_code == 503


def test_oauth_start_returns_authorization_url_if_enabled(client: TestClient, gmail_enabled: None) -> None:
    response = client.get("/v1/email/gmail/oauth/start")

    assert response.status_code == 200
    authorization_url = response.json()["authorization_url"]
    assert authorization_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_secret" not in authorization_url
    assert "test-client-id" in authorization_url


def test_oauth_callback_refuses_invalid_state(unauthenticated_client: TestClient, gmail_enabled: None) -> None:
    response = unauthenticated_client.get("/v1/email/gmail/oauth/callback?code=test-code&state=invalid-state")

    assert response.status_code == 400


def test_staff_cannot_create_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-STAFF")
    staff = create_user(client, "staff-gmail@example.com", "staff")
    assign_restaurant(client, staff["id"], restaurant["id"])
    connect_gmail_account(db_session, staff["id"])
    staff_token = login(client, staff["email"])

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
        headers=auth_headers(staff_token),
    )

    assert response.status_code == 403


def test_manager_assigned_can_create_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-MANAGER")
    manager = create_user(client, "manager-gmail@example.com", "manager")
    assign_restaurant(client, manager["id"], restaurant["id"])
    connect_gmail_account(db_session, manager["id"])
    manager_token = login(client, manager["email"])

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
        headers=auth_headers(manager_token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "provider_draft_created"
    assert fake_gmail_provider.last_include_evidence is True


def test_manager_non_assigned_cannot_create_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-BLOCKED")
    manager = create_user(client, "manager-blocked@example.com", "manager")
    connect_gmail_account(db_session, manager["id"])
    manager_token = login(client, manager["email"])

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
        headers=auth_headers(manager_token),
    )

    assert response.status_code == 403


def test_owner_can_create_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-OWNER")

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": False},
    )

    assert response.status_code == 200
    assert response.json()["provider_draft_id"] == f"fake-gmail-draft-{draft['id']}"


def test_create_gmail_draft_refused_without_connected_account(
    client: TestClient,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-NOACCOUNT")

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
    )

    assert response.status_code == 409


def test_create_gmail_draft_requires_existing_internal_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)

    response = client.post(
        "/v1/drafts/9999/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
    )

    assert response.status_code == 404


def test_create_gmail_draft_includes_evidence_if_requested(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-EVIDENCE")

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
    )

    assert response.status_code == 200
    assert fake_gmail_provider.last_evidence_count == 2


def test_audit_log_created_after_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-AUDIT")

    response = client.post(
        f"/v1/drafts/{draft['id']}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": False},
    )

    assert response.status_code == 200
    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "email_provider_draft",
            AuditLog.action == "gmail_draft.created",
        )
    )
    assert audit_log is not None


def test_tokens_are_never_exposed_in_responses(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)

    status_response = client.get("/v1/email/gmail/status")

    assert status_response.status_code == 200
    payload = status_response.json()
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "access_token_encrypted" not in payload
    assert "refresh_token_encrypted" not in payload
