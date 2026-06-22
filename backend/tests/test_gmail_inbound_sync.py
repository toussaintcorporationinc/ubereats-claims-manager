import json
from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models import (
    AuditLog,
    AppealWorkflow,
    AutopilotAction,
    AutopilotRun,
    ClaimOrder,
    ClaimResponseReview,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    GmailSyncState,
    GmailResponseAnalysis,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.services.email_provider import (
    EmailConnectionStatus,
    EmailProviderError,
    EmailSendResult,
    InboundEmailAttachment,
    InboundEmailPayload,
)
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncService
from app.services.gmail_inbound_sync_service import GmailInboundSyncResult, GmailInboundSyncService
from app.services.openai_structured_analysis_service import (
    AIGmailClassification,
    AIProofExtraction,
    OpenAIStructuredAnalysisService,
)
import app.services.gmail_response_intelligence_service as gmail_intelligence_service


class FakeInboundGmailProvider:
    provider = "gmail"

    def __init__(self) -> None:
        self.messages: list[InboundEmailPayload] = []
        self.queries: list[str] = []
        self.query_limits: list[tuple[str, int]] = []
        self.all_queries: list[str] = []
        self.all_query_options: list[tuple[str, int, int]] = []
        self.removed_labels: list[tuple[int, str, str]] = []

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
        if account is not None:
            account.disconnected_at = utc_now()

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            provider="gmail",
            provider_draft_id=f"fake-inbound-autopilot-{email_draft.id}-{utc_now().timestamp()}",
            provider_thread_id=f"fake-inbound-thread-{email_draft.id}",
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        return provider_draft

    def send_draft(self, db: Session, user: User, provider_draft: EmailProviderDraft) -> EmailSendResult:
        return EmailSendResult(
            provider_message_id=f"fake-inbound-message-{provider_draft.id}",
            provider_thread_id=provider_draft.provider_thread_id or f"fake-inbound-thread-{provider_draft.id}",
            sent_at=utc_now(),
        )

    def list_messages(self, db: Session, user: User, query: str, max_results: int) -> list[str]:
        self.queries.append(query)
        self.query_limits.append((query, max_results))
        return self.filtered_message_ids(query)[:max_results]

    def filtered_message_ids(self, query: str) -> list[str]:
        messages = self.messages
        if "is:starred" in query:
            messages = [message for message in messages if "STARRED" in message.provider_labels]
        if "has:attachment" in query:
            messages = [message for message in messages if message.attachments]
        return [message.provider_message_id for message in messages]

    def get_message(self, db: Session, user: User, message_id: str) -> InboundEmailPayload:
        for message in self.messages:
            if message.provider_message_id == message_id:
                return message
        raise EmailProviderError("Fake message not found", 404)

    def remove_message_label_for_account(
        self,
        db: Session,
        account: EmailAccount,
        message_id: str,
        label_id: str,
    ) -> None:
        self.removed_labels.append((account.id, message_id, label_id))
        for message in self.messages:
            if message.provider_message_id == message_id and label_id in message.provider_labels:
                message.provider_labels.remove(label_id)
                return

    def get_thread(self, db: Session, user: User, thread_id: str) -> dict:
        return {"id": thread_id}

    def sync_inbound_replies(
        self,
        db: Session,
        user: User,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        return [self.get_message(db, user, message_id) for message_id in self.list_messages(db, user, query, max_results)]

    def sync_all_inbound_replies_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        page_size: int = 500,
        max_pages: int = 0,
    ) -> list[InboundEmailPayload]:
        self.all_queries.append(query)
        self.all_query_options.append((query, page_size, max_pages))
        message_ids = self.filtered_message_ids(query)
        if max_pages > 0:
            message_ids = message_ids[: page_size * max_pages]
        user = db.get(User, account.user_id)
        assert user is not None
        return [self.get_message(db, user, message_id) for message_id in message_ids]


@pytest.fixture()
def gmail_provider_enabled(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GMAIL_OAUTH_REDIRECT_URI", "http://localhost:8000/v1/email/gmail/oauth/callback")
    monkeypatch.setenv(
        "GMAIL_SCOPES",
        "https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.readonly",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def gmail_inbound_enabled(
    monkeypatch: pytest.MonkeyPatch,
    gmail_provider_enabled: None,
) -> Generator[None, None, None]:
    monkeypatch.setenv("GMAIL_INBOUND_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_SYNC_LOOKBACK_DAYS", "30")
    monkeypatch.setenv("GMAIL_INBOUND_MAX_MESSAGES_PER_SYNC", "100")
    monkeypatch.setenv("GMAIL_SUPPORT_SENDER_FILTER", "uber.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def gmail_autopilot_enabled(
    monkeypatch: pytest.MonkeyPatch,
    gmail_inbound_enabled: None,
) -> Generator[None, None, None]:
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_INITIAL_CLAIMS_ENABLED", "false")
    monkeypatch.setenv("AUTOPILOT_FOLLOWUPS_ENABLED", "false")
    monkeypatch.setenv("AUTOPILOT_DAILY_SEND_LIMIT", "50")
    monkeypatch.setenv("AUTOPILOT_PER_RESTAURANT_DAILY_LIMIT", "20")
    monkeypatch.setenv("AUTOPILOT_COOLDOWN_HOURS", "48")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake_gmail_provider() -> Generator[FakeInboundGmailProvider, None, None]:
    provider = FakeInboundGmailProvider()
    app.dependency_overrides[get_gmail_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_gmail_provider, None)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def get_active_account(db: Session, user_id: int) -> EmailAccount | None:
    return db.scalar(
        select(EmailAccount).where(
            EmailAccount.user_id == user_id,
            EmailAccount.provider == "gmail",
            EmailAccount.disconnected_at.is_(None),
        )
    )


def get_user(db_session: Session, email: str) -> User:
    user = db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def connect_gmail_account(db_session: Session, user_id: int, email_address: str = "claims-owner@example.com") -> None:
    db_session.add(
        EmailAccount(
            user_id=user_id,
            provider="gmail",
            email_address=email_address,
            access_token_encrypted="encrypted-access-token",
            refresh_token_encrypted="encrypted-refresh-token",
            scopes="https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.readonly",
        )
    )
    db_session.commit()


def create_restaurant(client: TestClient, name: str = "Inbound Restaurant", token: str | None = None) -> dict:
    response = client.post(
        "/v1/restaurants",
        json={
            "name": name,
            "address": "108 Avenue du Marechal Foch, Meaux, 77100",
            "phone_number": "0605807385",
            "sender_email": "claims@example.com",
        },
        headers=auth_headers(token) if token else None,
    )
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


def create_order(client: TestClient, restaurant_id: int, order_number: str, token: str | None = None) -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
        },
        headers=auth_headers(token) if token else None,
    )
    assert response.status_code == 201
    return response.json()


def create_sent_email_context(
    db_session: Session,
    client: TestClient,
    *,
    restaurant_id: int,
    order_number: str,
    thread_id: str,
    order_status: str = "sent",
) -> ClaimOrder:
    order_data = create_order(client, restaurant_id, order_number)
    order = db_session.get(ClaimOrder, order_data["id"])
    assert order is not None
    order.customer_name = "Client Test"
    order.order_date = utc_now().date()
    order.status = order_status
    draft = EmailDraft(
        order_id=order.id,
        draft_type="initial_claim",
        subject=f"Réclamation Uber Eats {order_number}",
        body=f"Bonjour, merci d'étudier la commande {order_number}.",
        status="draft",
    )
    db_session.add(draft)
    db_session.flush()
    provider_draft = EmailProviderDraft(
        email_draft_id=draft.id,
        provider="gmail",
        provider_draft_id=f"gmail-draft-{order_number}",
        provider_thread_id=thread_id,
        provider_message_id=f"outbound-message-{order_number}",
        to_email="merchants@uber.com",
        subject=draft.subject,
        status="sent",
        created_by_user_id=1,
        sent_by_user_id=1,
        sent_at=utc_now(),
    )
    db_session.add(provider_draft)
    db_session.add(
        EmailThread(
            order_id=order.id,
            provider="gmail",
            thread_id=thread_id,
            message_id=provider_draft.provider_message_id,
            direction="outbound",
            subject=draft.subject,
            body=draft.body,
            sent_at=provider_draft.sent_at,
        )
    )
    db_session.commit()
    db_session.refresh(order)
    return order


def inbound_payload(
    message_id: str,
    *,
    thread_id: str | None = None,
    from_email: str = "support@uber.com",
    to_email: str = "claims-owner@example.com",
    subject: str = "Re: réclamation Uber Eats",
    body_text: str = "Nous revenons vers vous.",
    provider_labels: list[str] | None = None,
    attachments: list[InboundEmailAttachment] | None = None,
) -> InboundEmailPayload:
    return InboundEmailPayload(
        provider_message_id=message_id,
        provider_thread_id=thread_id,
        gmail_history_id=f"history-{message_id}",
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        snippet=body_text[:80],
        body_text=body_text,
        received_at=utc_now(),
        raw_headers={"from": from_email, "to": to_email, "subject": subject},
        provider_labels=provider_labels or [],
        attachments=attachments or [],
    )


def sync_inbound(client: TestClient, token: str | None = None, payload: dict | None = None):
    return client.post(
        "/v1/email/gmail/inbound/sync",
        json=payload or {"lookback_days": 30, "max_messages": 100},
        headers=auth_headers(token) if token else None,
    )


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_inbound_status_connected_and_not_connected(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    not_connected_response = client.get("/v1/email/gmail/inbound/status")
    assert not_connected_response.status_code == 200
    not_connected_payload = not_connected_response.json()
    assert not_connected_payload["enabled"] is True
    assert not_connected_payload["connected"] is False
    assert not_connected_payload["auto_sync_enabled"] is False
    assert not_connected_payload["auto_sync_interval_seconds"] == 30
    assert not_connected_payload["auto_sync_run_autopilot"] is True
    assert not_connected_payload["auto_sync_run_workspace_machine"] is True
    assert not_connected_payload["autopilot_enabled"] is False
    assert not_connected_payload["autopilot_followups_enabled"] is False
    assert not_connected_payload["autopilot_appeals_enabled"] is False
    assert not_connected_payload["ai_gmail_analysis_enabled"] is True

    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)

    connected_response = client.get("/v1/email/gmail/inbound/status")
    assert connected_response.status_code == 200
    assert connected_response.json()["connected"] is True


def test_inbound_status_exposes_last_auto_worker_cycle(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_INTERVAL_SECONDS", "300")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_FOLLOWUPS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()

    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, email_address="first@example.com")
    connect_gmail_account(db_session, owner.id, email_address="second@example.com")
    account = get_active_account(db_session, owner.id)
    assert account is not None
    db_session.add(
        GmailSyncState(
            email_account_id=account.id,
            status="idle",
            last_sync_at=utc_now(),
            last_success_at=utc_now(),
        )
    )
    db_session.add(
        AuditLog(
            user_id=None,
            entity_type="gmail_auto_sync",
            entity_id=0,
            action="cycle_completed",
            new_value=json.dumps(
                {
                    "accounts_checked": 2,
                    "accounts_synced": 2,
                    "accounts_skipped": 0,
                    "synced_messages": 42,
                    "applied_reviews": 4,
                    "negative_responses_detected": 3,
                    "autopilot_sent_count": 2,
                    "autopilot_skipped_count": 1,
                    "autopilot_failed_count": 0,
                    "workspace_machine_runs": 1,
                    "errors": [],
                }
            ),
        )
    )
    restaurant = Restaurant(
        name="Gmail Worker Blocked Restaurant",
        legal_name="Gmail Worker Blocked Restaurant",
        sender_email="worker-blocked@example.com",
    )
    db_session.add(restaurant)
    db_session.flush()
    run = AutopilotRun(status="completed", mode="all", total_candidates=2, sent_count=0, skipped_count=2, failed_count=0)
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            AutopilotAction(
                run_id=run.id,
                case_type="appeal_workflow",
                case_id=11,
                restaurant_id=restaurant.id,
                action_type="send_appeal",
                status="skipped",
                reason="skipped",
                skipped_reason="missing_customer_name",
            ),
            AutopilotAction(
                run_id=run.id,
                case_type="claim_order",
                case_id=12,
                restaurant_id=restaurant.id,
                action_type="send_initial_claim",
                status="skipped",
                reason="skipped",
                skipped_reason="initial_claims_disabled",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/v1/email/gmail/inbound/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["worker_state"] == "active"
    assert payload["connected_accounts_count"] == 2
    assert payload["auto_sync_enabled"] is True
    assert payload["autopilot_enabled"] is True
    assert payload["autopilot_followups_enabled"] is True
    assert payload["autopilot_appeals_enabled"] is True
    assert payload["last_cycle"]["accounts_checked"] == 2
    assert payload["last_cycle"]["synced_messages"] == 42
    assert payload["last_cycle"]["negative_responses_detected"] == 3
    assert payload["last_cycle"]["autopilot_sent_count"] == 2
    assert payload["last_autopilot_blockers"] == [
        {"action_type": "send_appeal", "skipped_reason": "missing_customer_name", "count": 1},
        {"action_type": "send_initial_claim", "skipped_reason": "initial_claims_disabled", "count": 1},
    ]
    assert payload["seconds_until_next_sync"] is not None


def test_sync_refused_if_email_provider_disabled(
    client: TestClient,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    response = sync_inbound(client)

    assert response.status_code == 503


def test_sync_refused_if_inbound_disabled(
    client: TestClient,
    db_session: Session,
    gmail_provider_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)

    response = sync_inbound(client)

    assert response.status_code == 503


def test_sync_refused_without_connected_account(
    client: TestClient,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    response = sync_inbound(client)

    assert response.status_code == 409


def test_staff_cannot_launch_sync(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    staff = create_user(client, "staff-inbound@example.com", "staff")
    connect_gmail_account(db_session, staff["id"], "staff-inbound@example.com")
    staff_token = login(client, staff["email"])

    response = sync_inbound(client, staff_token)

    assert response.status_code == 403


def test_manager_can_launch_sync_for_own_account(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    manager = create_user(client, "manager-inbound@example.com", "manager")
    assign_restaurant(client, manager["id"], restaurant["id"])
    connect_gmail_account(db_session, manager["id"], "manager-inbound@example.com")
    manager_token = login(client, manager["email"])

    response = sync_inbound(client, manager_token)

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_sync_deduplicates_provider_message_id(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    fake_gmail_provider.messages = [inbound_payload("msg-dedup")]

    first_response = sync_inbound(client)
    second_response = sync_inbound(client)

    assert first_response.status_code == 200
    assert first_response.json()["synced_messages"] == 1
    assert second_response.status_code == 200
    assert second_response.json()["synced_messages"] == 0
    assert db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-dedup"))


def test_sync_truncates_long_gmail_subject(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    long_subject = "Contestation Uber " + ("commande preparee " * 40)
    fake_gmail_provider.messages = [inbound_payload("msg-long-subject", subject=long_subject)]

    response = sync_inbound(client)

    assert response.status_code == 200
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-long-subject")
    )
    assert inbound_message is not None
    assert inbound_message.subject is not None
    assert len(inbound_message.subject) == 255
    assert inbound_message.body_text == "Nous revenons vers vous."


def test_reprocess_unreviewed_messages_respects_max_messages(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    account = get_active_account(db_session, owner.id)
    assert account is not None
    for index in range(3):
        db_session.add(
            InboundEmailMessage(
                email_account_id=account.id,
                provider="gmail",
                provider_message_id=f"msg-existing-{index}",
                from_email="support@uber.com",
                subject=f"Réponse Uber {index}",
                body_text="Nous revenons vers vous.",
                match_status="unlinked",
                match_reason="no_match",
                review_status="unreviewed",
                received_at=utc_now(),
            )
        )
    db_session.commit()

    result = GmailInboundSyncResult(status="success")
    GmailInboundSyncService(fake_gmail_provider).reprocess_unreviewed_messages(
        db_session,
        owner,
        account,
        result,
        apply_reviews=False,
        max_messages=2,
        exclude_message_ids=set(),
    )

    assert result.manual_review_messages == 2
    assert db_session.scalar(select(func.count(GmailResponseAnalysis.id))) == 2


def test_message_with_known_thread_id_is_linked_and_audited(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-THREAD",
        thread_id="thread-known",
    )
    fake_gmail_provider.messages = [inbound_payload("msg-thread", thread_id="thread-known")]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["linked_messages"] == 1
    inbound_message = db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-thread"))
    assert inbound_message is not None
    assert inbound_message.order_id == order.id
    assert inbound_message.match_status == "linked"
    assert inbound_message.match_reason == "thread_id_match"
    db_session.refresh(order)
    assert order.status == "response_received"
    inbound_thread = db_session.scalar(
        select(EmailThread).where(
            EmailThread.order_id == order.id,
            EmailThread.direction == "inbound",
            EmailThread.message_id == "msg-thread",
        )
    )
    assert inbound_thread is not None
    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "inbound_email_message",
            AuditLog.entity_id == inbound_message.id,
            AuditLog.action == "gmail_inbound_message.linked",
        )
    )
    assert audit_log is not None


def test_sync_refused_response_creates_review_and_appeal(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-REFUSED",
        thread_id="thread-refused",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-refused",
            thread_id="thread-refused",
            body_text="We are unable to reimburse this order. It is not eligible for compensation.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["applied_reviews"] == 1
    db_session.refresh(order)
    assert order.status == "refused"
    review = db_session.scalar(select(ClaimResponseReview).where(ClaimResponseReview.order_id == order.id))
    assert review is not None
    assert review.review_type == "refused"
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"
    assert analysis.status == "applied"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"


def test_sync_starred_gmail_message_is_urgent_refusal_to_follow_up(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-STARRED",
        thread_id="thread-starred",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-starred",
            thread_id="thread-starred",
            body_text="Nous revenons vers vous.",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert "is:starred" in fake_gmail_provider.all_queries
    payload = response.json()
    assert payload["applied_reviews"] == 1
    assert payload["negative_responses_detected"] == 1
    db_session.refresh(order)
    assert order.status == "refused"
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-starred")
    )
    assert inbound_message is not None
    assert inbound_message.provider_labels_json == ["STARRED"]
    assert fake_gmail_provider.removed_labels == []
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "gmail_starred_urgent_followup"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"


def test_sync_starred_gmail_query_reads_full_history_by_default(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_STARRED_MAX_MESSAGES_PER_SYNC", "1000")
    monkeypatch.setenv("GMAIL_STARRED_FULL_HISTORY_ENABLED", "true")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    fake_gmail_provider.messages = [
        inbound_payload(f"msg-starred-limit-{index}", provider_labels=["STARRED"])
        for index in range(5)
    ]

    response = sync_inbound(client, payload={"lookback_days": 30, "max_messages": 2})

    assert response.status_code == 200
    assert response.json()["synced_messages"] == 5
    assert "is:starred has:attachment" in fake_gmail_provider.all_queries
    assert "is:starred" in fake_gmail_provider.all_queries
    assert all(limit == 2 for query, limit in fake_gmail_provider.query_limits if query.startswith("newer_than:"))
    assert not [query for query, _ in fake_gmail_provider.query_limits if "is:starred" in query]
    get_settings.cache_clear()


def test_sync_starred_gmail_query_can_be_limited_when_full_history_disabled(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_STARRED_FULL_HISTORY_ENABLED", "false")
    monkeypatch.setenv("GMAIL_STARRED_MAX_MESSAGES_PER_SYNC", "4")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    fake_gmail_provider.messages = [
        inbound_payload(f"msg-starred-limited-mode-{index}", provider_labels=["STARRED"])
        for index in range(5)
    ]

    response = sync_inbound(client, payload={"lookback_days": 30, "max_messages": 2})

    assert response.status_code == 200
    starred_limits = {query: limit for query, limit in fake_gmail_provider.query_limits if "is:starred" in query}
    assert starred_limits["is:starred has:attachment"] == 4
    assert starred_limits["is:starred"] == 4
    assert fake_gmail_provider.all_queries == []
    get_settings.cache_clear()


def test_sync_existing_gmail_message_marked_starred_is_reprocessed_as_urgent_refusal(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-STARRED-LATER",
        thread_id="thread-starred-later",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-starred-later",
            thread_id="thread-starred-later",
            body_text="Nous revenons vers vous.",
        )
    ]

    first_response = sync_inbound(client)

    assert first_response.status_code == 200
    assert first_response.json()["applied_reviews"] == 0
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-starred-later")
    )
    assert inbound_message is not None
    assert inbound_message.provider_labels_json == []

    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-starred-later",
            thread_id="thread-starred-later",
            body_text="Nous revenons vers vous.",
            provider_labels=["STARRED"],
        )
    ]

    second_response = sync_inbound(client)

    assert second_response.status_code == 200
    payload = second_response.json()
    assert payload["applied_reviews"] == 1
    assert payload["negative_responses_detected"] == 1
    db_session.refresh(order)
    db_session.refresh(inbound_message)
    assert order.status == "refused"
    assert inbound_message.provider_labels_json == ["STARRED"]
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.reason == "gmail_starred_urgent_followup"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"


def test_sync_refused_response_can_run_autopilot_appeal(
    client: TestClient,
    db_session: Session,
    gmail_autopilot_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client, "Inbound AutoPilot Restaurant")
    restaurant_record = db_session.get(Restaurant, restaurant["id"])
    assert restaurant_record is not None
    restaurant_record.autopilot_enabled = True
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-AUTO-APPEAL",
        thread_id="thread-auto-appeal",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-auto-appeal",
            thread_id="thread-auto-appeal",
            body_text="We cannot reimburse this order. No compensation is available.",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["negative_responses_detected"] == 1
    assert payload["autopilot_run_id"] is not None
    assert payload["autopilot_sent_count"] == 1
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_sent"
    assert workflow.appeal_attempt_count == 1
    sent_draft = db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent"))
    assert sent_draft is not None
    assert sent_draft.to_email == "merchants@uber.com"


def test_sync_autopilot_blocks_recipient_outside_support_filter(
    client: TestClient,
    db_session: Session,
    gmail_autopilot_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_UBER_EATS_SUPPORT_EMAIL", "support@example.invalid")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client, "Inbound AutoPilot Recipient Guard")
    restaurant_record = db_session.get(Restaurant, restaurant["id"])
    assert restaurant_record is not None
    restaurant_record.autopilot_enabled = True
    create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-BAD-RECIPIENT",
        thread_id="thread-bad-recipient",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-bad-recipient",
            thread_id="thread-bad-recipient",
            body_text="This order is not eligible and we cannot reimburse it.",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["negative_responses_detected"] == 1
    assert payload["autopilot_sent_count"] == 0
    assert payload["autopilot_skipped_count"] == 1
    action = db_session.scalar(select(AutopilotAction).where(AutopilotAction.action_type == "send_appeal"))
    assert action is not None
    assert action.skipped_reason == "recipient_not_matching_support_filter"
    assert action.provider_draft_id is None
    get_settings.cache_clear()


def test_auto_sync_service_is_disabled_by_default(
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    result = GmailInboundAutoSyncService(fake_gmail_provider).sync_due_accounts(db_session)

    assert result.status == "disabled"
    assert result.accounts_checked == 0


def test_auto_sync_recovers_stale_running_state(
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_CONTINUOUS_ENABLED", "false")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_INTERVAL_SECONDS", "300")
    get_settings.cache_clear()
    service = GmailInboundAutoSyncService(fake_gmail_provider)
    now = utc_now()

    recent_running = GmailSyncState(status="running", last_sync_at=now - timedelta(seconds=600))
    stale_running = GmailSyncState(status="running", last_sync_at=now - timedelta(seconds=1201))

    assert service.account_is_due(recent_running, now) is False
    assert service.account_is_due(stale_running, now) is True
    get_settings.cache_clear()


def test_auto_sync_continuous_mode_keeps_accounts_due(
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_CONTINUOUS_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_IDLE_SLEEP_SECONDS", "1")
    get_settings.cache_clear()
    service = GmailInboundAutoSyncService(fake_gmail_provider)
    now = utc_now()

    recently_synced = GmailSyncState(status="success", last_sync_at=now - timedelta(seconds=1))

    assert service.account_is_due(recently_synced, now) is True
    assert service.effective_interval_seconds() == 1
    get_settings.cache_clear()


def test_auto_sync_continuous_mode_recovers_running_state_quickly(
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_CONTINUOUS_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_IDLE_SLEEP_SECONDS", "1")
    get_settings.cache_clear()
    service = GmailInboundAutoSyncService(fake_gmail_provider)
    now = utc_now()

    recent_running = GmailSyncState(status="running", last_sync_at=now - timedelta(seconds=30))
    stale_running = GmailSyncState(status="running", last_sync_at=now - timedelta(seconds=61))

    assert service.account_is_due(recent_running, now) is False
    assert service.account_is_due(stale_running, now) is True
    get_settings.cache_clear()


def test_auto_sync_marks_unexpected_sync_failure_failed(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenGmailProvider(FakeInboundGmailProvider):
        def list_messages(self, db: Session, user: User, query: str, max_results: int) -> list[str]:
            raise RuntimeError("gmail worker exploded")

    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)

    result = GmailInboundAutoSyncService(BrokenGmailProvider()).sync_due_accounts(db_session)

    sync_state = db_session.scalar(select(GmailSyncState))
    assert sync_state is not None
    assert result.status == "failed"
    assert result.accounts_checked == 1
    assert result.errors == ["email_account:1:gmail worker exploded"]
    assert sync_state.status == "failed"
    assert sync_state.last_error == "gmail worker exploded"
    get_settings.cache_clear()


def test_auto_sync_limits_existing_reprocess_backlog(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_EXISTING_REPROCESS_LIMIT", "3")
    monkeypatch.setenv("GMAIL_STARRED_FULL_HISTORY_ENABLED", "false")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    recorded_limits: list[int] = []
    recorded_starred_limits: list[int] = []
    original_reprocess = GmailInboundSyncService.reprocess_unreviewed_messages
    original_starred_reprocess = GmailInboundSyncService.reprocess_starred_backlog

    def spy_reprocess(self, db, user, account, result, *, apply_reviews, max_messages, exclude_message_ids):
        recorded_limits.append(max_messages)
        return original_reprocess(
            self,
            db,
            user,
            account,
            result,
            apply_reviews=apply_reviews,
            max_messages=max_messages,
            exclude_message_ids=exclude_message_ids,
        )

    def spy_starred_reprocess(self, db, user, account, result, *, apply_reviews, max_messages, exclude_message_ids):
        recorded_starred_limits.append(max_messages)
        return original_starred_reprocess(
            self,
            db,
            user,
            account,
            result,
            apply_reviews=apply_reviews,
            max_messages=max_messages,
            exclude_message_ids=exclude_message_ids,
        )

    monkeypatch.setattr(GmailInboundSyncService, "reprocess_unreviewed_messages", spy_reprocess)
    monkeypatch.setattr(GmailInboundSyncService, "reprocess_starred_backlog", spy_starred_reprocess)

    result = GmailInboundAutoSyncService(fake_gmail_provider).sync_due_accounts(db_session)

    assert result.status == "success"
    assert result.accounts_checked == 1
    assert recorded_limits == [3]
    assert recorded_starred_limits == [3]
    get_settings.cache_clear()


def test_auto_sync_reprocesses_full_existing_starred_backlog_by_default(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_EXISTING_REPROCESS_LIMIT", "3")
    monkeypatch.setenv("GMAIL_STARRED_FULL_HISTORY_ENABLED", "true")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    account = get_active_account(db_session, owner.id)
    assert account is not None
    recorded_starred_limits: list[int | None] = []
    original_starred_reprocess = GmailInboundSyncService.reprocess_starred_backlog

    def spy_starred_reprocess(self, db, user, account, result, *, apply_reviews, max_messages, exclude_message_ids):
        recorded_starred_limits.append(max_messages)
        return original_starred_reprocess(
            self,
            db,
            user,
            account,
            result,
            apply_reviews=apply_reviews,
            max_messages=max_messages,
            exclude_message_ids=exclude_message_ids,
        )

    for index in range(5):
        db_session.add(
            InboundEmailMessage(
                email_account_id=account.id,
                provider="gmail",
                provider_message_id=f"existing-starred-full-{index}",
                provider_thread_id=f"thread-existing-starred-full-{index}",
                from_email="restaurants@uber.com",
                to_email=account.email_address,
                subject=f"Refus commande TEST-FULL-{index}",
                body_text=f"Pas de remboursement pour TEST-FULL-{index}",
                provider_labels_json=["STARRED"],
                match_status="unlinked",
                match_reason="no_match",
            )
        )
    db_session.flush()

    monkeypatch.setattr(GmailInboundSyncService, "reprocess_starred_backlog", spy_starred_reprocess)

    result = GmailInboundAutoSyncService(fake_gmail_provider).sync_due_accounts(db_session)

    assert result.status == "success"
    assert recorded_starred_limits == [None]
    get_settings.cache_clear()


def test_auto_sync_service_processes_refusals_and_runs_autopilot(
    client: TestClient,
    db_session: Session,
    gmail_autopilot_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client, "Auto Sync AutoPilot Restaurant")
    restaurant_record = db_session.get(Restaurant, restaurant["id"])
    assert restaurant_record is not None
    restaurant_record.autopilot_enabled = True
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-AUTO-SYNC-REFUSED",
        thread_id="thread-auto-sync-refused",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-auto-sync-refused",
            thread_id="thread-auto-sync-refused",
            body_text="We are unable to reimburse this order. No compensation is available.",
            provider_labels=["STARRED"],
        )
    ]

    result = GmailInboundAutoSyncService(fake_gmail_provider).sync_due_accounts(db_session)

    assert result.status == "success"
    assert result.accounts_checked == 1
    assert result.accounts_synced == 1
    assert result.negative_responses_detected == 1
    assert result.autopilot_sent_count == 1
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_sent"
    get_settings.cache_clear()


def test_auto_sync_runs_autopilot_for_existing_linked_starred_thread(
    client: TestClient,
    db_session: Session,
    gmail_autopilot_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    account = get_active_account(db_session, owner.id)
    assert account is not None
    restaurant = create_restaurant(client, "Auto Sync Existing Starred Restaurant")
    restaurant_record = db_session.get(Restaurant, restaurant["id"])
    assert restaurant_record is not None
    restaurant_record.autopilot_enabled = True
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-AUTO-SYNC-OLD-STARRED",
        thread_id="thread-auto-sync-old-starred",
    )
    order.status = "refused"
    db_session.add(
        InboundEmailMessage(
            email_account_id=account.id,
            order_id=order.id,
            provider="gmail",
            provider_message_id="msg-auto-sync-old-starred",
            provider_thread_id="thread-auto-sync-old-starred",
            from_email="restaurants@uber.com",
            to_email=account.email_address,
            subject="Re: Contestation remboursement UBER-AUTO-SYNC-OLD-STARRED",
            body_text="Pas de remboursement pour cette commande.",
            provider_labels_json=["STARRED"],
            match_status="linked",
            match_reason="thread_id_match",
            review_status="reviewed",
            reviewed_at=utc_now(),
            reviewed_by_user_id=owner.id,
        )
    )
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=restaurant["id"],
        claim_order_id=order.id,
        status="appeal_needed",
        current_level=0,
        refusal_count=1,
        appeal_attempt_count=0,
        last_refusal_at=utc_now(),
        next_action_at=utc_now() - timedelta(minutes=1),
        next_action_type="create_gmail_draft",
        opened_by_user_id=owner.id,
    )
    db_session.add(workflow)
    db_session.commit()

    result = GmailInboundAutoSyncService(fake_gmail_provider).sync_due_accounts(db_session)

    assert result.status == "success"
    assert result.accounts_checked == 1
    assert result.starred_messages_seen == 1
    assert result.negative_responses_detected == 0
    assert result.autopilot_sent_count == 1
    db_session.refresh(workflow)
    assert workflow.status == "appeal_sent"
    sent_draft = db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent"))
    assert sent_draft is not None
    assert sent_draft.provider_thread_id is not None
    get_settings.cache_clear()


def test_sync_payment_confirmed_response_updates_recovered_amount(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-PAID",
        thread_id="thread-paid",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-paid",
            thread_id="thread-paid",
            body_text="Payment has been issued for 24,90 EUR and credited to your account.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["applied_reviews"] == 1
    db_session.refresh(order)
    assert order.status == "payment_confirmed"
    assert str(order.recovered_amount) == "24.90"
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "payment_confirmed"
    assert str(analysis.detected_amount) == "24.90"


def test_sync_payment_signal_wins_over_starred_gmail_label(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-STARRED-PAID",
        thread_id="thread-starred-paid",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-starred-paid",
            thread_id="thread-starred-paid",
            body_text="Payment has been issued for 19,99 EUR and credited to your account.",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_reviews"] == 1
    assert payload["negative_responses_detected"] == 0
    db_session.refresh(order)
    assert order.status == "payment_confirmed"
    assert str(order.recovered_amount) == "19.99"
    account = get_active_account(db_session, owner.id)
    assert account is not None
    assert fake_gmail_provider.removed_labels == [(account.id, "msg-starred-paid", "STARRED")]
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-starred-paid")
    )
    assert inbound_message is not None
    assert inbound_message.provider_labels_json == []
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "payment_confirmed"
    assert analysis.reason == "payment_confirmed_with_amount"


def test_sync_payment_without_amount_requires_verification(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-PAYMENT-VERIFY",
        thread_id="thread-payment-verify",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-payment-verify",
            thread_id="thread-payment-verify",
            body_text="Payment has been issued and will appear in your next payout.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.status == "payment_to_verify"
    assert order.recovered_amount is None
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "payment_to_verify"


def test_sync_evidence_request_marks_manual_review(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-EVIDENCE",
        thread_id="thread-evidence",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-evidence",
            thread_id="thread-evidence",
            body_text="Please provide proof, receipt and screenshot for this order.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.status == "manual_review"
    review = db_session.scalar(select(ClaimResponseReview).where(ClaimResponseReview.order_id == order.id))
    assert review is not None
    assert review.review_type == "evidence_requested"
    assert review.evidence_requested is True


def test_sync_unknown_response_does_not_invent_decision(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-UNKNOWN",
        thread_id="thread-unknown-decision",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-unknown-decision",
            thread_id="thread-unknown-decision",
            body_text="Hello, thank you for contacting us about this order.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["manual_review_messages"] == 1
    db_session.refresh(order)
    assert order.status == "response_received"
    assert db_session.scalar(select(ClaimResponseReview).where(ClaimResponseReview.order_id == order.id)) is None
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "manual_review"
    assert analysis.status == "manual_review"


def test_analyze_endpoint_can_preview_without_applying_review(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-PREVIEW",
        thread_id="thread-preview",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-preview",
            thread_id="thread-preview",
            body_text="Claim approved. You will receive this amount in your next payout.",
        )
    ]
    sync_response = client.post(
        "/v1/email/gmail/inbound/sync",
        json={"lookback_days": 30, "max_messages": 100, "analyze_responses": False},
    )
    assert sync_response.status_code == 200

    response = client.post(
        "/v1/email/gmail/inbound/analyze",
        json={"apply_reviews": False, "only_unreviewed": True},
    )

    assert response.status_code == 200
    assert response.json()["analyzed_messages"] == 1
    db_session.refresh(order)
    assert order.status == "response_received"
    assert db_session.scalar(select(ClaimResponseReview).where(ClaimResponseReview.order_id == order.id)) is None
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "payment_to_verify"
    assert analysis.status == "analyzed"


def test_message_with_order_number_in_subject_is_linked(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-SUBJECT",
        thread_id="thread-subject",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-subject",
            thread_id="thread-unknown",
            subject="Réponse Uber UBER-INBOUND-SUBJECT",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    inbound_message = db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-subject"))
    assert inbound_message is not None
    assert inbound_message.order_id == order.id
    assert inbound_message.match_reason == "subject_match"


def test_message_with_visible_internal_reference_is_linked(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="9f34dabf-15b6-45f9-9495-8f60330aef87",
        thread_id="thread-visible-ref",
    )
    order.internal_reference = "#AEF87"
    db_session.commit()
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-visible-ref",
            thread_id="thread-unknown-visible-ref",
            subject="Re: Contestation d'annulation de commande #AEF87",
            body_text="Nous ne pouvons pas rembourser la commande #AEF87.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-visible-ref")
    )
    assert inbound_message is not None
    assert inbound_message.order_id == order.id
    assert inbound_message.match_reason == "subject_match"
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"


def test_message_without_match_stays_unlinked(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    fake_gmail_provider.messages = [inbound_payload("msg-unlinked", subject="Réponse Uber sans numéro")]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["unlinked_messages"] == 1
    inbound_message = db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-unlinked"))
    assert inbound_message is not None
    assert inbound_message.order_id is None
    assert inbound_message.match_status == "unlinked"
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == inbound_message.id)
    )
    assert analysis is not None
    assert analysis.status == "manual_review"
    assert analysis.reason.startswith("message_not_linked_to_order")


def test_starred_message_without_match_is_visible_manual_review(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-starred-unlinked",
            subject="Re: refus Uber sans numero commande",
            body_text="Nous revenons vers vous.",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["unlinked_messages"] == 1
    assert payload["manual_review_messages"] == 1
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-starred-unlinked")
    )
    assert inbound_message is not None
    assert inbound_message.order_id is None
    assert inbound_message.provider_labels_json == ["STARRED"]
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == inbound_message.id)
    )
    assert analysis is not None
    assert analysis.status == "manual_review"
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "message_not_linked_to_order:gmail_starred_urgent_followup"


def test_ai_gmail_analysis_applies_ambiguous_negative_response(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-AI-NEGATIVE",
        thread_id="thread-ai-negative",
    )

    def fake_ai_gmail(*_args, **_kwargs):
        return AIGmailClassification(
            review_type="refused",
            confidence=Decimal("0.91"),
            reason="policy_denial_without_keyword",
            detected_amount=None,
            evidence_requested=False,
            notes="Uber refuse la regularisation selon sa politique.",
        )

    monkeypatch.setattr(
        gmail_intelligence_service.OpenAIStructuredAnalysisService,
        "analyze_gmail_message",
        fake_ai_gmail,
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-ai-negative",
            thread_id="thread-ai-negative",
            body_text="After another review, this request does not meet our internal adjustment policy.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.status == "refused"
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.status == "applied"
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "ai:policy_denial_without_keyword"
    get_settings.cache_clear()


def test_ai_gmail_payment_confirmed_requires_amount(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-AI-PAYMENT",
        thread_id="thread-ai-payment",
    )

    def fake_ai_gmail(*_args, **_kwargs):
        return AIGmailClassification(
            review_type="payment_confirmed",
            confidence=Decimal("0.92"),
            reason="payment_signal_without_amount",
            detected_amount=None,
            evidence_requested=False,
            notes="Paiement annonce mais montant absent.",
        )

    monkeypatch.setattr(
        gmail_intelligence_service.OpenAIStructuredAnalysisService,
        "analyze_gmail_message",
        fake_ai_gmail,
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-ai-payment",
            thread_id="thread-ai-payment",
            body_text="The accounting team has reviewed this thread and left a positive note for the merchant.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.status == "payment_to_verify"
    assert order.recovered_amount is None
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.status == "applied"
    assert analysis.recommended_review_type == "payment_to_verify"
    assert analysis.reason == "ai_payment_without_amount"
    get_settings.cache_clear()


def test_ai_gmail_long_unlinked_reason_is_truncated(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    long_reason = "mixed_signals_requiring_manual_review_" + ("very_long_reason_" * 10)

    def fake_ai_gmail(*_args, **_kwargs):
        return AIGmailClassification(
            review_type="manual_review",
            confidence=Decimal("0.91"),
            reason=long_reason,
            detected_amount=None,
            evidence_requested=False,
            notes="Message ambigu a verifier.",
        )

    monkeypatch.setattr(
        gmail_intelligence_service.OpenAIStructuredAnalysisService,
        "analyze_gmail_message",
        fake_ai_gmail,
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-ai-unlinked-long-reason",
            thread_id="thread-ai-unlinked-long-reason",
            body_text="After another review, the context is unclear and needs a merchant review.",
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-ai-unlinked-long-reason")
    )
    assert inbound_message is not None
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == inbound_message.id)
    )
    assert analysis is not None
    assert analysis.status == "manual_review"
    assert analysis.reason is not None
    assert analysis.reason.startswith("message_not_linked_to_order:ai:mixed_signals")
    assert len(analysis.reason) == 100
    get_settings.cache_clear()


def test_existing_unlinked_uber_message_is_relinked_on_next_sync(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-EXISTING-RELINK",
        thread_id="thread-existing-relink",
    )
    order.internal_reference = "#4B8A2"
    account = db_session.scalar(select(EmailAccount).where(EmailAccount.user_id == owner.id))
    assert account is not None
    message = InboundEmailMessage(
        email_account_id=account.id,
        provider="gmail",
        provider_message_id="msg-existing-unlinked",
        provider_thread_id="thread-not-known-yet",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation commande #4B8A2",
        snippet="We cannot reimburse order #4B8A2.",
        body_text="We cannot reimburse order #4B8A2. No compensation is available.",
        received_at=utc_now(),
        raw_headers_json={},
        match_status="unlinked",
        match_reason="no_match",
    )
    db_session.add(message)
    db_session.commit()
    fake_gmail_provider.messages = []

    response = sync_inbound(client)

    assert response.status_code == 200
    db_session.refresh(message)
    assert message.order_id == order.id
    assert message.match_status == "linked"
    assert message.match_reason in {"subject_match", "order_number_match"}
    analysis = db_session.scalar(select(GmailResponseAnalysis).where(GmailResponseAnalysis.order_id == order.id))
    assert analysis is not None
    assert analysis.status == "applied"
    assert analysis.recommended_review_type == "refused"


def test_message_from_own_gmail_account_is_ignored(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "claims-owner@example.com")
    fake_gmail_provider.messages = [inbound_payload("msg-own", from_email="claims-owner@example.com")]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["ignored_messages"] == 1
    inbound_message = db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-own"))
    assert inbound_message is not None
    assert inbound_message.match_status == "ignored"
    assert inbound_message.match_reason == "ignored_sender"


def test_starred_message_from_own_gmail_account_marks_known_thread_urgent_for_reply(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "claims-owner@example.com")
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-OWN-STARRED",
        thread_id="thread-own-starred",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-own-starred",
            thread_id="thread-own-starred",
            from_email="claims-owner@example.com",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["linked_messages"] == 1
    assert response.json()["ignored_messages"] == 0
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-own-starred")
    )
    assert inbound_message is not None
    assert inbound_message.order_id == order.id
    assert inbound_message.match_status == "linked"
    assert inbound_message.match_reason == "thread_id_match"
    assert inbound_message.provider_labels_json == ["STARRED"]
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == inbound_message.id)
    )
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "gmail_starred_urgent_followup"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"


def test_starred_gmail_attachment_repairs_missing_order_identity(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "claims-owner@example.com")
    restaurant = create_restaurant(client, name="Frit Dodo")
    order_data = create_order(client, restaurant["id"], "AUTO-GMAIL-ATTACHMENT")
    order = db_session.get(ClaimOrder, order_data["id"])
    assert order is not None
    order.customer_name = None
    order.order_date = None
    order.internal_reference = None
    db_session.add(
        EmailThread(
            order_id=order.id,
            provider="gmail",
            thread_id="thread-proof-attachment",
            message_id="outbound-proof-attachment",
            direction="outbound",
            subject="Contestation remboursement de commande",
            body="Bonjour, contestation de commande avec preuve.",
            sent_at=utc_now(),
        )
    )
    db_session.commit()

    def fake_analyze_proof(self, **kwargs) -> AIProofExtraction:
        assert kwargs["filename"] == "preuve-ticket.jpg"
        assert kwargs["image_bytes"] == b"fake-ticket-image"
        return AIProofExtraction(
            detected_evidence_type="ticket_agraphe",
            case_type="refund",
            restaurant_name="Frit Dodo",
            customer_name="Yoann O",
            order_number="F93BA",
            display_id="F93BA",
            order_date=date(2026, 6, 18),
            order_amount=Decimal("24.99"),
            currency="EUR",
            confidence=Decimal("0.94"),
            missing_fields=[],
            notes="ticket lisible",
        )

    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_proof", fake_analyze_proof)
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-own-starred-proof",
            thread_id="thread-proof-attachment",
            from_email="claims-owner@example.com",
            provider_labels=["STARRED"],
            attachments=[
                InboundEmailAttachment(
                    filename="preuve-ticket.jpg",
                    mime_type="image/jpeg",
                    content=b"fake-ticket-image",
                )
            ],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["identity_repaired_messages"] == 1
    db_session.refresh(order)
    assert order.customer_name == "Yoann O"
    assert order.order_date == date(2026, 6, 18)
    assert order.internal_reference == "F93BA"
    assert db_session.scalar(
        select(AuditLog).where(AuditLog.action == "autopilot.identity_repaired_from_gmail_attachment")
    ) is not None
    get_settings.cache_clear()


def test_starred_gmail_attachment_creates_order_when_thread_is_not_linked(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "claims-owner@example.com")
    restaurant = create_restaurant(client, name="Frit Dodo")

    def fake_analyze_proof(self, **kwargs) -> AIProofExtraction:
        assert "Bonjour je veux contester cette commande." in kwargs["extracted_text"]
        return AIProofExtraction(
            detected_evidence_type="ticket_agraphe",
            case_type="refund",
            restaurant_name="Frit Dodo",
            customer_name="Inaki A",
            order_number="BAEF7",
            display_id="BAEF7",
            order_date=date(2026, 6, 18),
            order_amount=Decimal("19.99"),
            currency="EUR",
            confidence=Decimal("0.95"),
            missing_fields=[],
            notes="ticket lisible",
        )

    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_proof", fake_analyze_proof)
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-unlinked-starred-proof",
            thread_id="thread-unlinked-proof",
            from_email="claims-owner@example.com",
            subject="Contestation remboursement de commande",
            body_text="Bonjour je veux contester cette commande.",
            provider_labels=["STARRED"],
            attachments=[
                InboundEmailAttachment(
                    filename="preuve-annulation.jpg",
                    mime_type="image/jpeg",
                    content=b"fake-ticket-image",
                )
            ],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert "is:starred has:attachment" in fake_gmail_provider.all_queries
    assert payload["linked_messages"] == 1
    assert payload["identity_repaired_messages"] == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "BAEF7"))
    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.customer_name == "Inaki A"
    assert order.order_date == date(2026, 6, 18)
    assert order.order_amount == Decimal("19.99")
    assert order.status == "refused"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"
    message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-unlinked-starred-proof")
    )
    assert message is not None
    assert message.order_id == order.id
    assert message.match_status == "linked"
    assert message.match_reason == "order_number_match"
    get_settings.cache_clear()


def test_starred_gmail_text_creates_order_when_thread_is_not_linked(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "tiramisumaisonfrance@gmail.com")
    restaurant = create_restaurant(client, name="Frit Dodo")
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-unlinked-starred-text",
            thread_id="thread-unlinked-starred-text",
            from_email="tiramisumaisonfrance@gmail.com",
            to_email="restaurantsfrance@uber.com",
            subject="Contestation de remboursement de commande",
            body_text=(
                "Bonjour je veux contester la demande de remboursement de Yoann O "
                "numéro de commande F93BA, du 18/06/2026, car sa commande a bien ete preparee.\n\n"
                "Montant concerne : 24.99 EUR\n\n"
                "Frit Dodo\n"
                "108 Avenue du Marechal Foch, Meaux, 77100\n"
                "0605807385\n"
                "tiramisumaisonfrance@gmail.com"
            ),
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["linked_messages"] == 1
    assert payload["identity_repaired_messages"] == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "F93BA"))
    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.customer_name == "Yoann O"
    assert order.order_date == date(2026, 6, 18)
    assert order.order_amount == Decimal("24.99")
    assert order.loss_type == "customer_refund"
    assert order.status == "refused"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"
    message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-unlinked-starred-text")
    )
    assert message is not None
    assert message.order_id == order.id
    assert message.match_status == "linked"
    assert message.match_reason == "order_number_match"
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == message.id)
    )
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "gmail_starred_urgent_followup"
    get_settings.cache_clear()


def test_starred_gmail_text_creates_cancellation_order_when_thread_is_not_linked(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "tiramisumaisonfrance@gmail.com")
    restaurant = create_restaurant(client, name="Frit Dodo")
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-unlinked-starred-cancellation-text",
            thread_id="thread-unlinked-starred-cancellation-text",
            from_email="tiramisumaisonfrance@gmail.com",
            to_email="restaurantsfrance@uber.com",
            subject="contestation d'annulation de commande",
            body_text=(
                "Bonsoir je veux contester l'annulation de commande de Inaki A "
                "numéro de commande BAEF7 car nous l'avons préparé et le client a annulé.\n\n"
                "Montant concerné : 19.99 EUR\n\n"
                "Frit Dodo\n"
                "108 Avenue du Marechal Foch, Meaux, 77100\n"
                "0605807385\n"
                "tiramisumaisonfrance@gmail.com"
            ),
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["linked_messages"] == 1
    assert payload["identity_repaired_messages"] == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "BAEF7"))
    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.customer_name == "Inaki A"
    assert order.order_amount == Decimal("19.99")
    assert order.loss_type == "cancellation"
    assert order.status == "refused"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"
    message = db_session.scalar(
        select(InboundEmailMessage).where(
            InboundEmailMessage.provider_message_id == "msg-unlinked-starred-cancellation-text"
        )
    )
    assert message is not None
    assert message.order_id == order.id
    assert message.match_status == "linked"
    assert message.match_reason == "order_number_match"
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == message.id)
    )
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "gmail_starred_urgent_followup"
    get_settings.cache_clear()


def test_starred_gmail_text_creates_order_without_amount_or_date(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "tiramisumaisonfrance@gmail.com")
    restaurant = create_restaurant(client, name="Big Chicken Burger")
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-unlinked-starred-text-no-amount",
            thread_id="thread-unlinked-starred-text-no-amount",
            from_email="tiramisumaisonfrance@gmail.com",
            to_email="restaurantsfrance@uber.com",
            subject="Contestation de remboursement de commande",
            body_text=(
                "Bonjour je veux contester la demande de remboursement de Yanis M "
                "numero de commande 09891 car sa commande a bien ete preparee.\n\n"
                "Big Chicken Burger\n"
                "0605807385\n"
                "tiramisumaisonfrance@gmail.com"
            ),
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["linked_messages"] == 1
    assert payload["identity_repaired_messages"] == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "09891"))
    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.customer_name == "Yanis M"
    assert order.order_amount is None
    assert order.order_date is None
    assert order.status == "refused"
    message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-unlinked-starred-text-no-amount")
    )
    assert message is not None
    assert message.order_id == order.id
    assert message.match_status == "linked"
    get_settings.cache_clear()


def test_starred_gmail_text_uses_ai_to_create_order_when_local_text_is_sparse(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "tiramisumaisonfrance@gmail.com")
    restaurant = create_restaurant(client, name="Frit Dodo")

    def fake_analyze_order_identity_text(self, **kwargs) -> AIProofExtraction:
        assert kwargs["order_context"]["source"] == "starred_gmail_unlinked_thread"
        assert "relance urgente" in kwargs["text"]
        return AIProofExtraction(
            detected_evidence_type="gmail_thread",
            case_type="cancellation",
            restaurant_name="Frit Dodo",
            customer_name="Inaki A",
            order_number="BAEF7",
            display_id="BAEF7",
            order_date=date(2026, 6, 18),
            order_amount=Decimal("19.99"),
            currency="EUR",
            confidence=Decimal("0.91"),
            missing_fields=[],
            notes="fil gmail etoile exploitable",
        )

    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_order_identity_text", fake_analyze_order_identity_text)
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-unlinked-starred-ai-text",
            thread_id="thread-unlinked-starred-ai-text",
            from_email="tiramisumaisonfrance@gmail.com",
            to_email="restaurantsfrance@uber.com",
            subject="contestation d'annulation de commande",
            body_text="relance urgente sur ce refus Uber, voir le fil complet et la preuve deja envoyee",
            provider_labels=["STARRED"],
        )
    ]

    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["identity_repaired_messages"] == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "BAEF7"))
    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.customer_name == "Inaki A"
    assert order.order_date == date(2026, 6, 18)
    assert order.order_amount == Decimal("19.99")
    assert order.loss_type == "cancellation"
    message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-unlinked-starred-ai-text")
    )
    assert message is not None
    assert message.order_id == order.id
    get_settings.cache_clear()


def test_starred_backlog_reprocess_fetches_attachment_and_creates_order(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    get_settings.cache_clear()
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "claims-owner@example.com")
    account = get_active_account(db_session, owner.id)
    assert account is not None
    restaurant = create_restaurant(client, name="Frit Dodo")
    payload = inbound_payload(
        "msg-existing-starred-proof",
        thread_id="thread-existing-proof",
        from_email="claims-owner@example.com",
        subject="Contestation remboursement de commande",
        body_text="Bonjour je veux contester cette commande.",
        provider_labels=["STARRED"],
        attachments=[
            InboundEmailAttachment(
                filename="preuve-ticket.jpg",
                mime_type="image/jpeg",
                content=b"fake-ticket-image",
            )
        ],
    )
    db_session.add(
        InboundEmailMessage(
            email_account_id=account.id,
            provider="gmail",
            provider_message_id=payload.provider_message_id,
            provider_thread_id=payload.provider_thread_id,
            from_email=payload.from_email,
            to_email=payload.to_email,
            subject=payload.subject,
            snippet=payload.snippet,
            body_text=payload.body_text,
            received_at=payload.received_at,
            raw_headers_json=payload.raw_headers,
            provider_labels_json=["STARRED"],
            match_status="ignored",
            match_reason="ignored_sender",
        )
    )
    db_session.commit()
    fake_gmail_provider.messages = [payload]

    def fake_analyze_proof(self, **kwargs) -> AIProofExtraction:
        assert "Bonjour je veux contester cette commande." in kwargs["extracted_text"]
        return AIProofExtraction(
            detected_evidence_type="ticket_agraphe",
            case_type="refund",
            restaurant_name="Frit Dodo",
            customer_name="Yoann O",
            order_number="F93BA",
            display_id="F93BA",
            order_date=date(2026, 6, 18),
            order_amount=Decimal("24.99"),
            currency="EUR",
            confidence=Decimal("0.95"),
            missing_fields=[],
            notes="ticket lisible",
        )

    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_proof", fake_analyze_proof)

    result = GmailInboundSyncResult(status="success")
    GmailInboundSyncService(fake_gmail_provider).reprocess_starred_backlog(
        db_session,
        owner,
        account,
        result,
        apply_reviews=True,
        max_messages=1,
        exclude_message_ids=set(),
    )
    db_session.commit()

    assert result.linked_messages == 1
    assert result.identity_repaired_messages == 1
    order = db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "F93BA"))
    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.customer_name == "Yoann O"
    message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-existing-starred-proof")
    )
    assert message is not None
    assert message.order_id == order.id
    assert message.match_status == "linked"
    assert message.match_reason == "order_number_match"
    get_settings.cache_clear()


def test_existing_ignored_own_gmail_message_is_linked_when_starred_later(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id, "claims-owner@example.com")
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-OWN-STARRED-LATER",
        thread_id="thread-own-starred-later",
    )
    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-own-starred-later",
            thread_id="thread-own-starred-later",
            from_email="claims-owner@example.com",
        )
    ]
    assert sync_inbound(client).status_code == 200
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-own-starred-later")
    )
    assert inbound_message is not None
    assert inbound_message.match_status == "ignored"

    fake_gmail_provider.messages = [
        inbound_payload(
            "msg-own-starred-later",
            thread_id="thread-own-starred-later",
            from_email="claims-owner@example.com",
            provider_labels=["STARRED"],
        )
    ]
    response = sync_inbound(client)

    assert response.status_code == 200
    assert response.json()["linked_messages"] == 1
    db_session.refresh(inbound_message)
    assert inbound_message.order_id == order.id
    assert inbound_message.match_status == "linked"
    assert inbound_message.match_reason == "thread_id_match"
    assert inbound_message.provider_labels_json == ["STARRED"]
    analysis = db_session.scalar(
        select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == inbound_message.id)
    )
    assert analysis is not None
    assert analysis.recommended_review_type == "refused"
    assert analysis.reason == "gmail_starred_urgent_followup"
    workflow = db_session.scalar(select(AppealWorkflow).where(AppealWorkflow.claim_order_id == order.id))
    assert workflow is not None
    assert workflow.status == "appeal_needed"


@pytest.mark.parametrize("final_status", ["accepted", "payment_confirmed"])
def test_linked_inbound_does_not_modify_final_order_status(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
    final_status: str,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number=f"UBER-INBOUND-{final_status}",
        thread_id=f"thread-{final_status}",
        order_status=final_status,
    )
    fake_gmail_provider.messages = [inbound_payload(f"msg-{final_status}", thread_id=f"thread-{final_status}")]

    response = sync_inbound(client)

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.status == final_status


def test_order_email_messages_returns_outbound_and_inbound(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-HISTORY",
        thread_id="thread-history",
    )
    fake_gmail_provider.messages = [inbound_payload("msg-history", thread_id="thread-history")]
    assert sync_inbound(client).status_code == 200

    response = client.get(f"/v1/orders/{order.id}/email-messages")

    assert response.status_code == 200
    data = response.json()
    assert any(thread["direction"] == "outbound" for thread in data["threads"])
    assert any(thread["direction"] == "inbound" for thread in data["threads"])
    assert data["inbound_messages"][0]["provider_message_id"] == "msg-history"


def test_manager_non_assigned_cannot_see_other_restaurant_messages(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-HIDDEN",
        thread_id="thread-hidden",
    )
    fake_gmail_provider.messages = [inbound_payload("msg-hidden", thread_id="thread-hidden")]
    assert sync_inbound(client).status_code == 200
    manager = create_user(client, "manager-hidden@example.com", "manager")
    connect_gmail_account(db_session, manager["id"], "manager-hidden@example.com")
    manager_token = login(client, manager["email"])

    response = client.get("/v1/email/inbound-messages", headers=auth_headers(manager_token))

    assert response.status_code == 200
    assert response.json()["messages"] == []


def test_owner_can_manually_link_unlinked_message(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-MANUAL",
        thread_id="thread-manual",
    )
    fake_gmail_provider.messages = [inbound_payload("msg-manual", subject="Réponse Uber à rattacher")]
    assert sync_inbound(client).status_code == 200
    inbound_message = db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-manual"))
    assert inbound_message is not None

    response = client.post(f"/v1/email/inbound-messages/{inbound_message.id}/link", json={"order_id": order.id})

    assert response.status_code == 200
    assert response.json()["order_id"] == order.id
    assert response.json()["match_reason"] == "manual_link"


def test_staff_cannot_manually_link_message(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-STAFF",
        thread_id="thread-staff",
    )
    fake_gmail_provider.messages = [inbound_payload("msg-staff", subject="Réponse Uber à rattacher")]
    assert sync_inbound(client).status_code == 200
    inbound_message = db_session.scalar(select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-staff"))
    staff = create_user(client, "staff-link@example.com", "staff")
    assign_restaurant(client, staff["id"], restaurant["id"])
    staff_token = login(client, staff["email"])

    response = client.post(
        f"/v1/email/inbound-messages/{inbound_message.id}/link",
        json={"order_id": order.id},
        headers=auth_headers(staff_token),
    )

    assert response.status_code == 403


def test_manager_non_assigned_cannot_manually_link_message(
    client: TestClient,
    db_session: Session,
    gmail_inbound_enabled: None,
    fake_gmail_provider: FakeInboundGmailProvider,
) -> None:
    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)
    restaurant = create_restaurant(client)
    order = create_sent_email_context(
        db_session,
        client,
        restaurant_id=restaurant["id"],
        order_number="UBER-INBOUND-MANAGER-BLOCKED",
        thread_id="thread-manager-blocked",
    )
    fake_gmail_provider.messages = [inbound_payload("msg-manager-blocked", subject="Réponse Uber à rattacher")]
    assert sync_inbound(client).status_code == 200
    inbound_message = db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "msg-manager-blocked")
    )
    manager = create_user(client, "manager-link-blocked@example.com", "manager")
    connect_gmail_account(db_session, manager["id"], "manager-link-blocked@example.com")
    manager_token = login(client, manager["email"])

    response = client.post(
        f"/v1/email/inbound-messages/{inbound_message.id}/link",
        json={"order_id": order.id},
        headers=auth_headers(manager_token),
    )

    assert response.status_code == 403
