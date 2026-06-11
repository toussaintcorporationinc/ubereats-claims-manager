from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models import (
    AuditLog,
    AppealWorkflow,
    ClaimOrder,
    ClaimResponseReview,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    GmailResponseAnalysis,
    InboundEmailMessage,
    User,
)
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.services.email_provider import EmailConnectionStatus, EmailProviderError, EmailSendResult, InboundEmailPayload


class FakeInboundGmailProvider:
    provider = "gmail"

    def __init__(self) -> None:
        self.messages: list[InboundEmailPayload] = []

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
        raise EmailProviderError("Draft creation is not used by inbound sync tests", 500)

    def send_draft(self, db: Session, user: User, provider_draft: EmailProviderDraft) -> EmailSendResult:
        raise EmailProviderError("Draft sending is not used by inbound sync tests", 500)

    def list_messages(self, db: Session, user: User, query: str, max_results: int) -> list[str]:
        return [message.provider_message_id for message in self.messages[:max_results]]

    def get_message(self, db: Session, user: User, message_id: str) -> InboundEmailPayload:
        for message in self.messages:
            if message.provider_message_id == message_id:
                return message
        raise EmailProviderError("Fake message not found", 404)

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
        json={"name": name, "sender_email": "claims@example.com"},
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
    subject: str = "Re: réclamation Uber Eats",
    body_text: str = "Nous revenons vers vous.",
) -> InboundEmailPayload:
    return InboundEmailPayload(
        provider_message_id=message_id,
        provider_thread_id=thread_id,
        gmail_history_id=f"history-{message_id}",
        from_email=from_email,
        to_email="claims-owner@example.com",
        subject=subject,
        snippet=body_text[:80],
        body_text=body_text,
        received_at=utc_now(),
        raw_headers={"from": from_email, "to": "claims-owner@example.com", "subject": subject},
    )


def sync_inbound(client: TestClient, token: str | None = None):
    return client.post(
        "/v1/email/gmail/inbound/sync",
        json={"lookback_days": 30, "max_messages": 100},
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
    assert not_connected_response.json()["enabled"] is True
    assert not_connected_response.json()["connected"] is False

    owner = get_user(db_session, "owner@example.com")
    connect_gmail_account(db_session, owner.id)

    connected_response = client.get("/v1/email/gmail/inbound/status")
    assert connected_response.status_code == 200
    assert connected_response.json()["connected"] is True


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
