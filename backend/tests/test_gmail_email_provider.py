import base64
from collections.abc import Generator
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.core.security import create_access_token
from app.models import (
    AuditLog,
    ClaimOrder,
    EmailAccount,
    EmailAccountRestaurantMapping,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    InboundEmailMessage,
    User,
)
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.services.autopilot_service import create_emergency_stop
from app.services.email_provider import EmailConnectionStatus, EmailProviderError, EmailSendResult
from app.services.gmail_email_provider import GmailEmailProvider


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
        self.fail_send = False
        self.send_count = 0

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
        account = get_active_account(db, user.id)
        if account is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        self.last_include_evidence = include_evidence
        self.last_evidence_count = len([item for item in email_draft.order.evidence_files if item.deleted_at is None])
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            email_account_id=account.id,
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

    def send_draft(self, db: Session, user: User, provider_draft: EmailProviderDraft) -> EmailSendResult:
        if not get_settings().email_provider_enabled:
            raise EmailProviderError("Email provider is disabled", 503)
        if get_active_account(db, user.id) is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        if self.fail_send:
            raise EmailProviderError("Fake Gmail send failed", 502)
        self.send_count += 1
        return EmailSendResult(
            provider_message_id=f"fake-message-{provider_draft.id}",
            provider_thread_id=f"fake-sent-thread-{provider_draft.id}",
            sent_at=utc_now(),
        )


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


def connect_gmail_account(db_session: Session, user_id: int, email_address: str = "connected@example.com") -> EmailAccount:
    account = EmailAccount(
        user_id=user_id,
        provider="gmail",
        email_address=email_address,
        access_token_encrypted="encrypted-access-token",
        refresh_token_encrypted="encrypted-refresh-token",
        scopes="https://www.googleapis.com/auth/gmail.compose",
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def gmail_text_payload(
    message_id: str,
    thread_id: str,
    subject: str,
    body: str,
    *,
    from_email: str,
    to_email: str,
    labels: list[str] | None = None,
) -> dict:
    encoded_body = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "id": message_id,
        "threadId": thread_id,
        "historyId": f"history-{message_id}",
        "labelIds": labels or [],
        "snippet": body[:120],
        "internalDate": "1781200000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_email},
                {"name": "To", "value": to_email},
                {"name": "Subject", "value": subject},
            ],
            "body": {"data": encoded_body},
        },
    }


def create_provider_draft_record(
    db_session: Session,
    draft_id: int,
    status: str = "provider_draft_created",
    created_by_user_id: int = 1,
    provider_draft_suffix: str = "",
) -> EmailProviderDraft:
    draft = db_session.get(EmailDraft, draft_id)
    assert draft is not None
    account = get_active_account(db_session, created_by_user_id)
    provider_draft = EmailProviderDraft(
        email_draft_id=draft_id,
        email_account_id=account.id if account is not None else None,
        provider="gmail",
        provider_draft_id=f"manual-gmail-draft-{draft_id}{provider_draft_suffix}",
        provider_thread_id=f"manual-thread-{draft_id}",
        to_email="merchants@uber.com",
        subject=draft.subject,
        status=status,
        created_by_user_id=created_by_user_id,
    )
    db_session.add(provider_draft)
    db_session.commit()
    db_session.refresh(provider_draft)
    return provider_draft


def create_gmail_provider_draft_via_api(
    client: TestClient,
    draft_id: int,
    token: str | None = None,
) -> dict:
    response = client.post(
        f"/v1/drafts/{draft_id}/gmail-draft",
        json={"to_email": "merchants@uber.com", "include_evidence": True},
        headers=auth_headers(token) if token else None,
    )
    assert response.status_code == 200
    return response.json()


def send_provider_draft(client: TestClient, provider_draft_id: str, token: str | None = None, confirm: bool = True):
    return client.post(
        f"/v1/email/gmail/provider-drafts/{provider_draft_id}/send",
        json={"confirm_send": confirm},
        headers=auth_headers(token) if token else None,
    )


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
    requested_scopes = parse_qs(urlparse(authorization_url).query)["scope"][0].split()
    assert "https://www.googleapis.com/auth/gmail.modify" in requested_scopes


def test_remove_message_label_requires_gmail_modify_scope(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_gmail_account(db_session, owner.id)
    provider = GmailEmailProvider()
    post_calls: list[tuple[str, dict, dict]] = []
    monkeypatch.setattr(provider, "post_json", lambda *args: post_calls.append(args))

    with pytest.raises(EmailProviderError) as exc_info:
        provider.remove_message_label_for_account(db_session, account, "message-1", "STARRED")

    assert exc_info.value.status_code == 409
    assert "gmail.modify" in exc_info.value.message
    assert post_calls == []


def test_gmail_accounts_report_modify_permission(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_gmail_account(db_session, owner.id)

    missing_response = client.get("/v1/email/gmail/accounts")

    assert missing_response.status_code == 200
    assert missing_response.json()[0]["gmail_modify_enabled"] is False

    account.scopes = (
        "https://www.googleapis.com/auth/gmail.compose "
        "https://www.googleapis.com/auth/gmail.modify"
    )
    db_session.commit()

    ready_response = client.get("/v1/email/gmail/accounts")

    assert ready_response.status_code == 200
    assert ready_response.json()[0]["gmail_modify_enabled"] is True


def test_oauth_callback_refuses_invalid_state(unauthenticated_client: TestClient, gmail_enabled: None) -> None:
    response = unauthenticated_client.get("/v1/email/gmail/oauth/callback?code=test-code&state=invalid-state")

    assert response.status_code == 400


def test_oauth_callback_keeps_multiple_gmail_accounts(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="multi-owner@example.com", full_name="Multi Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    provider = GmailEmailProvider()
    emails = iter(["restaurant-group-a@example.com", "restaurant-group-b@example.com"])

    monkeypatch.setattr(
        provider,
        "exchange_code_for_tokens",
        lambda code: {
            "access_token": f"access-{code}",
            "refresh_token": f"refresh-{code}",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.compose",
        },
    )
    monkeypatch.setattr(provider, "fetch_email_address", lambda access_token: next(emails))

    state = create_access_token(str(owner.id), {"purpose": "gmail_oauth_state", "provider": "gmail"})
    first = provider.handle_oauth_callback(db_session, state, "first-code")
    second = provider.handle_oauth_callback(db_session, state, "second-code")

    accounts = db_session.scalars(
        select(EmailAccount).where(EmailAccount.user_id == owner.id).order_by(EmailAccount.id)
    ).all()
    assert first.id != second.id
    assert [account.email_address for account in accounts] == [
        "restaurant-group-a@example.com",
        "restaurant-group-b@example.com",
    ]


def test_gmail_provider_uses_restaurant_mapped_account_for_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    default_account = connect_gmail_account(db_session, owner.id, "default-claims@example.com")
    mapped_account = connect_gmail_account(db_session, owner.id, "restaurant-group-a@example.com")
    restaurant = create_restaurant(client, "Mapped Gmail Restaurant")
    draft_payload = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-MAPPED")
    draft = db_session.get(EmailDraft, draft_payload["id"])
    assert draft is not None
    db_session.add(
        EmailAccountRestaurantMapping(
            restaurant_id=restaurant["id"],
            email_account_id=mapped_account.id,
            created_by_user_id=owner.id,
        )
    )
    db_session.commit()

    selected_account = GmailEmailProvider().get_account_for_draft(db_session, owner.id, draft)

    assert selected_account is not None
    assert selected_account.id == mapped_account.id
    assert selected_account.id != default_account.id


def test_gmail_provider_commits_refreshed_access_token(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="token-owner@example.com", full_name="Token Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    account = connect_gmail_account(db_session, owner.id, "token-refresh@example.com")
    account.token_expires_at = utc_now() - timedelta(minutes=5)
    db_session.commit()
    provider = GmailEmailProvider()
    commits: list[bool] = []
    original_commit = db_session.commit

    monkeypatch.setattr(provider.token_cipher, "decrypt", lambda value: "refresh-token" if value else "")
    monkeypatch.setattr(provider.token_cipher, "encrypt", lambda value: f"encrypted-{value}")
    monkeypatch.setattr(
        provider,
        "refresh_access_token",
        lambda refresh_token: {"access_token": "new-access-token", "expires_in": 3600},
    )

    def commit_spy() -> None:
        commits.append(True)
        original_commit()

    monkeypatch.setattr(db_session, "commit", commit_spy)

    token = provider.ensure_access_token(db_session, account)

    assert token == "new-access-token"
    assert commits
    assert account.access_token_encrypted == "encrypted-new-access-token"


def test_gmail_provider_lists_all_starred_pages(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="paged-owner@example.com", full_name="Paged Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    account = connect_gmail_account(db_session, owner.id, "paged-gmail@example.com")
    provider = GmailEmailProvider()
    requested_urls: list[str] = []

    monkeypatch.setattr(provider, "access_token_for_external_call", lambda db, account: "access-token")

    def fake_get_json(url: str, headers: dict[str, str]) -> dict:
        requested_urls.append(url)
        if "pageToken=page-2" in url:
            return {
                "messages": [{"id": "msg-3"}],
                "nextPageToken": "page-3",
            }
        if "pageToken=page-3" in url:
            return {"messages": [{"id": "msg-4"}]}
        return {
            "messages": [{"id": "msg-1"}, {"id": "msg-2"}],
            "nextPageToken": "page-2",
        }

    monkeypatch.setattr(provider, "get_json", fake_get_json)

    message_ids = provider.list_all_messages_for_account(
        db_session,
        account,
        query="is:starred",
        page_size=2,
        max_pages=0,
    )

    assert message_ids == ["msg-1", "msg-2", "msg-3", "msg-4"]
    assert len(requested_urls) == 3
    assert "pageToken=page-2" in requested_urls[1]
    assert "pageToken=page-3" in requested_urls[2]


def test_gmail_provider_enriches_starred_message_with_full_thread(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="thread-owner@example.com", full_name="Thread Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    account = connect_gmail_account(db_session, owner.id, "tiramisumaisonfrance@gmail.com")
    original_claim = gmail_text_payload(
        "msg-original-claim",
        "thread-starred-context",
        "Contestation de remboursement de commande",
        (
            "Bonjour je veux contester la demande de remboursement de Yoann O "
            "numéro de commande F93BA car sa commande a bien été préparée.\n\n"
            "Montant concerné : 24.99 EUR\n\n"
            "Frit Dodo"
        ),
        from_email="tiramisumaisonfrance@gmail.com",
        to_email="restaurantsfrance@uber.com",
        labels=["SENT"],
    )
    starred_refusal = gmail_text_payload(
        "msg-starred-refusal",
        "thread-starred-context",
        "Re: Contestation de remboursement de commande",
        "/// pas de remboursement possible pour ce dossier.",
        from_email="restaurantsfrance@uber.com",
        to_email="tiramisumaisonfrance@gmail.com",
        labels=["INBOX", "STARRED"],
    )
    provider = GmailEmailProvider()
    requested_urls: list[str] = []

    monkeypatch.setattr(provider, "access_token_for_external_call", lambda db, account: "access-token")

    def fake_get_json(url: str, headers: dict[str, str]) -> dict:
        requested_urls.append(url)
        if "/messages/msg-starred-refusal?format=full" in url:
            return starred_refusal
        if "/threads/thread-starred-context?format=full" in url:
            return {"id": "thread-starred-context", "messages": [original_claim, starred_refusal]}
        raise AssertionError(f"Unexpected Gmail URL: {url}")

    monkeypatch.setattr(provider, "get_json", fake_get_json)

    message = provider.get_message_for_account(db_session, account, "msg-starred-refusal")

    assert message.provider_message_id == "msg-starred-refusal"
    assert message.provider_thread_id == "thread-starred-context"
    assert "STARRED" in message.provider_labels
    assert message.body_text is not None
    assert "Yoann O" in message.body_text
    assert "F93BA" in message.body_text
    assert "Frit Dodo" in message.body_text
    assert "pas de remboursement" in message.body_text
    assert message.snippet is not None
    assert not message.snippet.startswith(" |")
    assert any("/threads/thread-starred-context?format=full" in url for url in requested_urls)


def test_gmail_provider_gets_latest_external_message_with_one_full_thread_request(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="latest-owner@example.com", full_name="Latest Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    account = connect_gmail_account(db_session, owner.id, "tiramisumaisonfrance@gmail.com")
    sent_claim = gmail_text_payload(
        "msg-sent-claim",
        "thread-latest-external",
        "Contestation F93BA",
        "Bonjour, je conteste la commande F93BA.",
        from_email=account.email_address,
        to_email="restaurantsfrance@uber.com",
        labels=["SENT"],
    )
    uber_reply = gmail_text_payload(
        "msg-latest-uber",
        "thread-latest-external",
        "Re: Contestation F93BA",
        "Nous maintenons le refus pour F93BA.",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        labels=["INBOX"],
    )
    provider = GmailEmailProvider()
    requested_urls: list[str] = []

    monkeypatch.setattr(provider, "access_token_for_external_call", lambda db, account: "access-token")

    def fake_get_json(url: str, headers: dict[str, str]) -> dict:
        requested_urls.append(url)
        return {"id": "thread-latest-external", "messages": [sent_claim, uber_reply]}

    monkeypatch.setattr(provider, "get_json", fake_get_json)

    latest = provider.get_latest_external_thread_message_for_account(
        db_session,
        account,
        "thread-latest-external",
    )

    assert latest is not None
    assert latest.provider_message_id == "msg-latest-uber"
    assert latest.body_text == "Nous maintenons le refus pour F93BA."
    assert requested_urls == [
        "https://gmail.googleapis.com/gmail/v1/users/me/threads/thread-latest-external?format=full"
    ]


def test_gmail_provider_disconnects_revoked_authorization(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="revoked-owner@example.com", full_name="Revoked Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    account = connect_gmail_account(db_session, owner.id, "revoked-token@example.com")
    account.token_expires_at = utc_now() - timedelta(minutes=5)
    db_session.commit()
    provider = GmailEmailProvider()

    monkeypatch.setattr(provider.token_cipher, "decrypt", lambda value: "refresh-token" if value else "")
    monkeypatch.setattr(
        provider,
        "refresh_access_token",
        lambda refresh_token: (_ for _ in ()).throw(
            EmailProviderError("Gmail API error: invalid_grant - Token has been expired or revoked.", 502)
        ),
    )

    with pytest.raises(EmailProviderError, match="Reconnect Gmail"):
        provider.ensure_access_token(db_session, account)

    db_session.refresh(account)
    assert account.disconnected_at is not None
    assert account.access_token_encrypted is None
    assert account.refresh_token_encrypted is None


def test_gmail_provider_commits_before_external_call_even_with_valid_token(
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(email="valid-token-owner@example.com", full_name="Valid Token Owner", role="owner", hashed_password="hash")
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)
    account = connect_gmail_account(db_session, owner.id, "valid-token@example.com")
    provider = GmailEmailProvider()
    commits: list[bool] = []
    original_commit = db_session.commit

    monkeypatch.setattr(provider, "ensure_access_token", lambda db, account: "valid-access-token")

    def commit_spy() -> None:
        commits.append(True)
        original_commit()

    monkeypatch.setattr(db_session, "commit", commit_spy)

    token = provider.access_token_for_external_call(db_session, account)

    assert token == "valid-access-token"
    assert commits


def test_owner_can_map_restaurant_to_connected_gmail_account(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_gmail_account(db_session, owner.id, "restaurant-group-a@example.com")
    restaurant = create_restaurant(client, "Tiramisu Mapping")

    response = client.put(
        f"/v1/email/gmail/restaurant-mappings/{restaurant['id']}",
        json={"email_account_id": account.id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["restaurant_id"] == restaurant["id"]
    assert data["email_account_id"] == account.id
    assert data["email_address"] == "restaurant-group-a@example.com"


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


def test_real_gmail_provider_replies_in_existing_uber_thread(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_gmail_account(db_session, owner.id, "claims-thread@example.com")
    restaurant = create_restaurant(client)
    draft_payload = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-THREAD")
    email_draft = db_session.get(EmailDraft, draft_payload["id"])
    assert email_draft is not None
    target_message = InboundEmailMessage(
        email_account_id=account.id,
        order_id=email_draft.order_id,
        provider="gmail",
        provider_message_id="gmail-msg-123",
        provider_thread_id="gmail-thread-urgent-123",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: contestation d'annulation de commande",
        body_text="Nous ne pouvons pas rembourser.",
        raw_headers_json={
            "message-id": "<uber-reply-123@mail.gmail.com>",
            "references": "<first-claim-123@mail.gmail.com>",
        },
        provider_labels_json=["STARRED"],
        match_status="linked",
        match_reason="thread_id_match",
        received_at=utc_now() - timedelta(hours=1),
    )
    db_session.add_all(
        [
            target_message,
            InboundEmailMessage(
                email_account_id=account.id,
                order_id=email_draft.order_id,
                provider="gmail",
                provider_message_id="gmail-msg-wrong-thread",
                provider_thread_id="gmail-thread-wrong-for-same-order",
                from_email="restaurantsfrance@uber.com",
                to_email=account.email_address,
                subject="Another starred thread for the same order",
                body_text="This newer thread must not receive the watched reply.",
                raw_headers_json={"message-id": "<wrong-thread@mail.gmail.com>"},
                provider_labels_json=["STARRED"],
                match_status="linked",
                match_reason="thread_id_match",
                received_at=utc_now(),
            ),
        ]
    )
    db_session.commit()
    captured: dict[str, str | None] = {}
    provider = GmailEmailProvider()

    monkeypatch.setattr(provider, "ensure_access_token", lambda db, account: "access-token")

    def fake_create_gmail_draft(access_token: str, raw_message: str, *, thread_id: str | None = None) -> dict:
        captured["raw_message"] = raw_message
        captured["thread_id"] = thread_id
        return {"id": "draft-threaded", "message": {"threadId": thread_id}}

    monkeypatch.setattr(provider, "create_gmail_draft", fake_create_gmail_draft)

    provider_draft = provider.create_draft_for_account_in_thread(
        db_session,
        owner,
        email_draft,
        to_email="restaurantsfrance@uber.com",
        include_evidence=False,
        account=account,
        thread_id="gmail-thread-urgent-123",
        reply_message=target_message,
    )

    assert provider_draft.provider_thread_id == "gmail-thread-urgent-123"
    assert provider_draft.subject == "Re: contestation d'annulation de commande"
    assert captured["thread_id"] == "gmail-thread-urgent-123"
    raw_message = str(captured["raw_message"])
    parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw_message))
    assert parsed["Subject"] == "Re: contestation d'annulation de commande"
    assert parsed["In-Reply-To"] == "<uber-reply-123@mail.gmail.com>"
    assert "<first-claim-123@mail.gmail.com>" in parsed["References"]
    assert "<uber-reply-123@mail.gmail.com>" in parsed["References"]


def test_real_gmail_provider_starts_new_message_when_reply_thread_is_missing(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_gmail_account(db_session, owner.id, "claims-fallback@example.com")
    restaurant = create_restaurant(client)
    draft_payload = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-FALLBACK")
    email_draft = db_session.get(EmailDraft, draft_payload["id"])
    assert email_draft is not None
    db_session.add(
        InboundEmailMessage(
            email_account_id=account.id,
            order_id=email_draft.order_id,
            provider="gmail",
            provider_message_id="gmail-msg-stale",
            provider_thread_id="gmail-thread-stale",
            from_email="restaurantsfrance@uber.com",
            to_email=account.email_address,
            subject="Re: contestation remboursement de commande",
            body_text="Nous ne pouvons pas rembourser cette commande.",
            raw_headers_json={"message-id": "<stale-reply@mail.gmail.com>"},
            provider_labels_json=["STARRED"],
            match_status="linked",
            match_reason="thread_id_match",
            received_at=utc_now(),
        )
    )
    db_session.commit()
    provider = GmailEmailProvider()
    calls: list[tuple[str | None, str]] = []

    monkeypatch.setattr(provider, "ensure_access_token", lambda db, account: "access-token")

    def fake_create_gmail_draft(access_token: str, raw_message: str, *, thread_id: str | None = None) -> dict:
        calls.append((thread_id, raw_message))
        if thread_id == "gmail-thread-stale":
            raise EmailProviderError("Gmail API error: NOT_FOUND - Requested entity was not found.", 502)
        return {"id": "draft-fallback", "message": {"threadId": "gmail-thread-new"}}

    monkeypatch.setattr(provider, "create_gmail_draft", fake_create_gmail_draft)

    provider_draft = provider.create_draft(
        db_session,
        owner,
        email_draft,
        to_email="restaurantsfrance@uber.com",
        include_evidence=False,
    )

    assert [thread_id for thread_id, _ in calls] == ["gmail-thread-stale", None]
    assert provider_draft.provider_draft_id == "draft-fallback"
    assert provider_draft.provider_thread_id == "gmail-thread-new"
    assert provider_draft.status == "provider_draft_created"
    fallback_message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(calls[1][1]))
    assert fallback_message["Subject"] == email_draft.subject
    assert fallback_message["In-Reply-To"] is None
    assert fallback_message["References"] is None


def test_real_gmail_provider_prefers_starred_thread_over_newer_unstarred_message(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    account = connect_gmail_account(db_session, owner.id, "claims-starred@example.com")
    restaurant = create_restaurant(client)
    draft_payload = create_ready_order_and_draft(client, restaurant["id"], "UBER-GMAIL-STARRED")
    email_draft = db_session.get(EmailDraft, draft_payload["id"])
    assert email_draft is not None
    db_session.add_all(
        [
            InboundEmailMessage(
                email_account_id=account.id,
                order_id=email_draft.order_id,
                provider="gmail",
                provider_message_id="gmail-msg-starred-refusal",
                provider_thread_id="gmail-thread-starred-refusal",
                from_email="restaurantsfrance@uber.com",
                to_email=account.email_address,
                subject="Re: contestation remboursement de commande",
                body_text="Nous ne pouvons pas rembourser cette commande.",
                raw_headers_json={
                    "message-id": "<starred-refusal@mail.gmail.com>",
                    "references": "<first-claim-starred@mail.gmail.com>",
                },
                provider_labels_json=["STARRED"],
                match_status="linked",
                match_reason="thread_id_match",
                received_at=utc_now() - timedelta(hours=2),
            ),
            InboundEmailMessage(
                email_account_id=account.id,
                order_id=email_draft.order_id,
                provider="gmail",
                provider_message_id="gmail-msg-newer-info",
                provider_thread_id="gmail-thread-newer-info",
                from_email="newsletter@example.com",
                to_email=account.email_address,
                subject="Information plus recente",
                body_text="Message non urgent.",
                raw_headers_json={"message-id": "<newer-info@mail.gmail.com>"},
                provider_labels_json=[],
                match_status="linked",
                match_reason="thread_id_match",
                received_at=utc_now(),
            ),
        ]
    )
    db_session.commit()

    context = GmailEmailProvider().find_reply_context(db_session, account, email_draft)

    assert context is not None
    assert context.thread_id == "gmail-thread-starred-refusal"
    assert context.subject == "Re: contestation remboursement de commande"
    assert context.message_id == "<starred-refusal@mail.gmail.com>"
    assert context.references == "<first-claim-starred@mail.gmail.com>"


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


def test_staff_cannot_send_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-STAFF")
    provider_draft = create_gmail_provider_draft_via_api(client, draft["id"])
    staff = create_user(client, "staff-send@example.com", "staff")
    assign_restaurant(client, staff["id"], restaurant["id"])
    connect_gmail_account(db_session, staff["id"])
    staff_token = login(client, staff["email"])

    response = send_provider_draft(client, provider_draft["provider_draft_id"], staff_token)

    assert response.status_code == 403


def test_manager_assigned_can_send_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-MANAGER")
    manager = create_user(client, "manager-send@example.com", "manager")
    assign_restaurant(client, manager["id"], restaurant["id"])
    connect_gmail_account(db_session, manager["id"])
    manager_token = login(client, manager["email"])
    provider_draft = create_gmail_provider_draft_via_api(client, draft["id"], manager_token)

    response = send_provider_draft(client, provider_draft["provider_draft_id"], manager_token)

    assert response.status_code == 200
    assert response.json()["status"] == "sent"


def test_manager_non_assigned_cannot_send_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-BLOCKED")
    provider_draft = create_gmail_provider_draft_via_api(client, draft["id"])
    manager = create_user(client, "manager-send-blocked@example.com", "manager")
    connect_gmail_account(db_session, manager["id"])
    manager_token = login(client, manager["email"])

    response = send_provider_draft(client, provider_draft["provider_draft_id"], manager_token)

    assert response.status_code == 403


def test_owner_can_send_gmail_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-OWNER")
    provider_draft = create_gmail_provider_draft_via_api(client, draft["id"])

    response = send_provider_draft(client, provider_draft["provider_draft_id"])

    assert response.status_code == 200
    assert response.json()["provider_message_id"] is not None


def test_send_gmail_draft_requires_confirmation(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-CONFIRM")
    provider_draft = create_provider_draft_record(db_session, draft["id"])

    response = send_provider_draft(client, provider_draft.provider_draft_id or "", confirm=False)

    assert response.status_code == 400


def test_send_gmail_draft_refused_if_provider_disabled(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-DISABLED")
    provider_draft = create_provider_draft_record(db_session, draft["id"])

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 503


def test_send_gmail_draft_refused_without_connected_account(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-NOACCOUNT")
    provider_draft = create_provider_draft_record(db_session, draft["id"])

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 409


def test_send_gmail_draft_refuses_unknown_provider_draft(
    client: TestClient,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    response = send_provider_draft(client, "unknown-provider-draft")

    assert response.status_code == 404


def test_send_gmail_draft_refuses_already_sent_provider_draft(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-ALREADY")
    provider_draft = create_provider_draft_record(db_session, draft["id"], status="sent")

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 409


@pytest.mark.parametrize("final_status", ["accepted", "payment_confirmed"])
def test_send_gmail_draft_refuses_final_order_status(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
    final_status: str,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], f"UBER-SEND-{final_status}")
    provider_draft = create_provider_draft_record(db_session, draft["id"])
    order = db_session.get(ClaimOrder, draft["order_id"])
    assert order is not None
    order.status = final_status
    db_session.commit()

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 409
    db_session.refresh(order)
    assert order.status == final_status


def test_send_gmail_draft_updates_tracking_order_thread_and_audit(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-TRACK")
    provider_draft = create_provider_draft_record(db_session, draft["id"])

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "sent"
    assert data["sent_at"] is not None
    assert data["provider_message_id"] == f"fake-message-{provider_draft.id}"

    db_session.refresh(provider_draft)
    assert provider_draft.status == "sent"
    assert provider_draft.sent_at is not None
    assert provider_draft.sent_by_user_id == owner.id
    assert provider_draft.provider_message_id == f"fake-message-{provider_draft.id}"

    order = db_session.get(ClaimOrder, draft["order_id"])
    assert order is not None
    assert order.status == "sent"

    email_thread = db_session.scalar(
        select(EmailThread).where(
            EmailThread.order_id == order.id,
            EmailThread.provider == "gmail",
            EmailThread.direction == "outbound",
        )
    )
    assert email_thread is not None
    assert email_thread.message_id == provider_draft.provider_message_id
    assert email_thread.sent_at is not None

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "email_provider_draft",
            AuditLog.entity_id == provider_draft.id,
            AuditLog.action == "send_gmail_draft",
        )
    )
    assert audit_log is not None


def test_send_gmail_draft_enforces_per_account_pacing(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    first_draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-PACING-1")
    second_draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-PACING-2")
    first_provider_draft = create_provider_draft_record(db_session, first_draft["id"], provider_draft_suffix="-first")
    second_provider_draft = create_provider_draft_record(db_session, second_draft["id"], provider_draft_suffix="-second")

    first_response = send_provider_draft(client, first_provider_draft.provider_draft_id or "")
    second_response = send_provider_draft(client, second_provider_draft.provider_draft_id or "")

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "gmail_account_send_pacing_active"
    assert fake_gmail_provider.send_count == 1
    db_session.refresh(second_provider_draft)
    assert second_provider_draft.status == "provider_draft_created"


def test_send_gmail_draft_rejects_duplicate_initial_claim(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-DUPLICATE")
    first_provider_draft = create_provider_draft_record(db_session, draft["id"], provider_draft_suffix="-first")
    second_provider_draft = create_provider_draft_record(db_session, draft["id"], provider_draft_suffix="-second")

    first_response = send_provider_draft(client, first_provider_draft.provider_draft_id or "")
    assert first_response.status_code == 200
    db_session.refresh(first_provider_draft)
    first_provider_draft.sent_at = utc_now() - timedelta(minutes=10)
    db_session.commit()

    second_response = send_provider_draft(client, second_provider_draft.provider_draft_id or "")

    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "gmail_initial_claim_already_sent"
    assert fake_gmail_provider.send_count == 1
    db_session.refresh(second_provider_draft)
    assert second_provider_draft.status == "provider_draft_created"


def test_send_gmail_draft_respects_emergency_stop(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-EMERGENCY-STOP")
    provider_draft = create_provider_draft_record(db_session, draft["id"])
    create_emergency_stop(db_session, owner)
    db_session.commit()

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 409
    assert response.json()["detail"] == "autopilot_emergency_stopped"
    assert fake_gmail_provider.send_count == 0
    db_session.refresh(provider_draft)
    assert provider_draft.status == "provider_draft_created"


def test_send_gmail_draft_provider_failure_sets_failed_status_and_audit(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    draft = create_ready_order_and_draft(client, restaurant["id"], "UBER-SEND-FAIL")
    provider_draft = create_provider_draft_record(db_session, draft["id"])
    fake_gmail_provider.fail_send = True

    response = send_provider_draft(client, provider_draft.provider_draft_id or "")

    assert response.status_code == 502
    db_session.refresh(provider_draft)
    assert provider_draft.status == "failed"
    assert provider_draft.last_error == "Fake Gmail send failed"
    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "email_provider_draft",
            AuditLog.entity_id == provider_draft.id,
            AuditLog.action == "send_gmail_draft_failed",
        )
    )
    assert audit_log is not None
