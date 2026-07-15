from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Generator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AppealAttempt,
    AppealWorkflow,
    ClaimOrder,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EvidenceFile,
    EvidenceRequestTask,
    GmailResponseAnalysis,
    GmailStarredWorkItem,
    GmailWatchedThread,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.services.appeal_workflow_service import AppealWorkflowError
from app.services.email_provider import EmailProviderError, EmailSendResult, InboundEmailPayload
from app.services import autopilot_identity_repair_service as identity_repair_service
from app.services.gmail_inbound_sync_service import (
    GMAIL_STARRED_URGENT_QUERIES,
    GMAIL_STARRED_URGENT_QUERY,
    GmailInboundSyncResult,
    GmailInboundSyncService,
)
from app.services.gmail_watched_thread_monitor_service import (
    FAST_CLASSIFICATION_BODY_HEAD_CHARS,
    FAST_CLASSIFICATION_BODY_TAIL_CHARS,
    GmailWatchedThreadMonitorResult,
    GmailWatchedThreadMonitorService,
    bounded_fast_classification_body,
    classify_unlinked_watched_message,
)
from app.services.order_identity_resolution_service import ResolvedOrderIdentity


class FakeWatchedGmailProvider:
    provider = "gmail"

    def __init__(self) -> None:
        self.starred_payloads: list[InboundEmailPayload] = []
        self.starred_payloads_by_query: dict[str, list[InboundEmailPayload]] = {}
        self.thread_payloads: dict[str, list[InboundEmailPayload]] = {}
        self.removed_labels: list[tuple[str, str]] = []
        self.full_history_calls: list[str] = []
        self.thread_include_attachments_calls: list[bool] = []
        self.created_drafts: list[int] = []
        self.created_draft_account_ids: list[int] = []
        self.created_draft_thread_ids: list[str] = []
        self.sent_drafts: list[int] = []
        self.provider_thread_id_for_drafts = "thread-f93ba"

    def sync_inbound_replies_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        if self.starred_payloads_by_query:
            return self.starred_payloads_by_query.get(query, [])[:max_results]
        if query != GMAIL_STARRED_URGENT_QUERY:
            return []
        return self.starred_payloads[:max_results]

    def sync_all_inbound_replies_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        page_size: int,
        max_pages: int,
    ) -> list[InboundEmailPayload]:
        self.full_history_calls.append(query)
        if self.starred_payloads_by_query:
            return self.starred_payloads_by_query.get(query, [])
        if query != GMAIL_STARRED_URGENT_QUERY:
            return []
        return self.starred_payloads

    def get_thread_messages_for_account(
        self,
        db: Session,
        account: EmailAccount,
        thread_id: str,
        *,
        include_attachments: bool = True,
    ) -> list[InboundEmailPayload]:
        self.thread_include_attachments_calls.append(include_attachments)
        return self.thread_payloads.get(thread_id, [])

    def remove_message_label_for_account(
        self,
        db: Session,
        account: EmailAccount,
        provider_message_id: str,
        label: str,
    ) -> None:
        self.removed_labels.append((provider_message_id, label))

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,  # noqa: ARG002
    ) -> EmailProviderDraft:
        account = db.scalar(
            select(EmailAccount)
            .where(EmailAccount.user_id == user.id, EmailAccount.provider == "gmail")
            .order_by(EmailAccount.id.asc())
            .limit(1)
        )
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            email_account_id=account.id if account else None,
            provider=self.provider,
            provider_draft_id=f"draft-{email_draft.id}",
            provider_thread_id=self.provider_thread_id_for_drafts,
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        self.created_drafts.append(provider_draft.id)
        return provider_draft

    def create_draft_for_account(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,  # noqa: ARG002
        account: EmailAccount,
    ) -> EmailProviderDraft:
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            email_account_id=account.id,
            provider=self.provider,
            provider_draft_id=f"draft-{email_draft.id}",
            provider_thread_id=self.provider_thread_id_for_drafts,
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        self.created_drafts.append(provider_draft.id)
        self.created_draft_account_ids.append(account.id)
        return provider_draft

    def create_draft_for_account_in_thread(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,  # noqa: ARG002
        account: EmailAccount,
        thread_id: str,
        reply_message: InboundEmailMessage,
    ) -> EmailProviderDraft:
        assert reply_message.provider_thread_id == thread_id
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            email_account_id=account.id,
            provider=self.provider,
            provider_draft_id=f"draft-{email_draft.id}",
            provider_thread_id=thread_id,
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        self.created_drafts.append(provider_draft.id)
        self.created_draft_account_ids.append(account.id)
        self.created_draft_thread_ids.append(thread_id)
        return provider_draft

    def send_draft(
        self,
        db: Session,  # noqa: ARG002
        user: User,  # noqa: ARG002
        provider_draft: EmailProviderDraft,
    ) -> EmailSendResult:
        self.sent_drafts.append(provider_draft.id)
        return EmailSendResult(
            provider_message_id=f"sent-{provider_draft.id}",
            provider_thread_id=provider_draft.provider_thread_id,
            sent_at=utc_now(),
        )


class FakeLightweightWatchedGmailProvider(FakeWatchedGmailProvider):
    def __init__(self) -> None:
        super().__init__()
        self.starred_refs_by_query: dict[str, list[dict[str, str]]] = {}
        self.ref_queries: list[str] = []

    def list_message_refs_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        max_results: int,
    ) -> list[dict[str, str]]:
        self.ref_queries.append(query)
        return self.starred_refs_by_query.get(query, [])[:max_results]


class FakeFastWatchedGmailProvider(FakeWatchedGmailProvider):
    def __init__(self) -> None:
        super().__init__()
        self.latest_payloads: dict[str, InboundEmailPayload | None] = {}
        self.latest_calls: list[str] = []

    def get_latest_external_thread_message_for_account(
        self,
        db: Session,
        account: EmailAccount,
        thread_id: str,
    ) -> InboundEmailPayload | None:
        self.latest_calls.append(thread_id)
        return self.latest_payloads.get(thread_id)


@pytest.fixture()
def watched_gmail_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_WATCHED_THREADS_ENABLED", "true")
    monkeypatch.setenv("GMAIL_WATCHED_THREADS_MAX_PER_CYCLE", "5000")
    monkeypatch.setenv("AI_GMAIL_ANALYSIS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def gmail_case(db_session: Session, client, watched_gmail_settings: None):
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    restaurant = Restaurant(
        name="Frit Dodo",
        address="108 Avenue du Marechal Foch, Meaux, 77100",
        phone_number="0605807385",
        sender_email="tiramisumaisonfrance@gmail.com",
        autopilot_enabled=True,
    )
    db_session.add(restaurant)
    db_session.flush()
    order = ClaimOrder(
        restaurant_id=restaurant.id,
        uber_order_number="F93BA",
        customer_name="Yoann O.",
        order_date=date(2026, 6, 18),
        order_amount=Decimal("24.99"),
        currency="EUR",
        status="refused",
    )
    db_session.add(order)
    account = EmailAccount(
        user_id=owner.id,
        provider="gmail",
        email_address="tiramisumaisonfrance@gmail.com",
        connected_at=utc_now(),
    )
    db_session.add(account)
    db_session.commit()
    return owner, account, order


def payload(
    provider_message_id: str,
    *,
    thread_id: str = "thread-f93ba",
    body: str = "Uber refuse la demande pour la commande F93BA.",
    subject: str = "Re: Contestation de remboursement de commande F93BA",
    from_email: str = "restaurantsfrance@uber.com",
    to_email: str = "tiramisumaisonfrance@gmail.com",
    starred: bool = False,
) -> InboundEmailPayload:
    labels = ["INBOX"]
    if starred:
        labels.append("STARRED")
    return InboundEmailPayload(
        provider_message_id=provider_message_id,
        provider_thread_id=thread_id,
        gmail_history_id=f"history-{provider_message_id}",
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        snippet=body[:120],
        body_text=body,
        received_at=utc_now(),
        raw_headers={
            "from": from_email,
            "to": to_email,
            "subject": subject,
        },
        provider_labels=labels,
    )


def install_fake_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_reprocess(
        self: GmailInboundSyncService,
        db: Session,
        user: User,
        account: EmailAccount,
        message: InboundEmailMessage,
        result: GmailInboundSyncResult,
        *,
        apply_reviews: bool,
        payload: InboundEmailPayload | None = None,
    ) -> None:
        body = (message.body_text or "").lower()
        if "paiement" in body or "accorde" in body:
            review_type = "payment_confirmed"
            reason = "payment_positive"
        elif "preuve" in body:
            review_type = "evidence_requested"
            reason = "evidence_requested"
        elif "refus" in body or "refuse" in body:
            review_type = "refused"
            reason = "refused_response"
            result.negative_responses_detected += 1
        else:
            review_type = "manual_review"
            reason = "manual_review_required"

        analysis = message.response_analysis
        if analysis is None:
            analysis = GmailResponseAnalysis(
                inbound_message_id=message.id,
                order_id=message.order_id,
                recommended_review_type=review_type,
                status="applied",
                confidence_score=Decimal("0.96"),
                reason=reason,
            )
            db.add(analysis)
        else:
            analysis.recommended_review_type = review_type
            analysis.reason = reason
        message.review_status = "reviewed"
        db.flush()

    monkeypatch.setattr(GmailInboundSyncService, "reprocess_existing_message", fake_reprocess)


def test_fast_unlinked_classification_bounds_long_gmail_threads() -> None:
    body = (
        "ancienne conversation sans decision " * 5000
        + " " * 5000
        + "Nous maintenons le refus, pas de remboursement."
    )
    message = InboundEmailMessage(
        from_email="restaurantsfrance@uber.com",
        subject="Re: Contestation de remboursement",
        snippet="/// Please enter your reply above this line",
        body_text=body,
        match_status="unlinked",
    )

    bounded = bounded_fast_classification_body(body)
    review_type, reason, confidence = classify_unlinked_watched_message(message)

    assert len(bounded) <= FAST_CLASSIFICATION_BODY_HEAD_CHARS + FAST_CLASSIFICATION_BODY_TAIL_CHARS + 1
    assert review_type == "refused"
    assert reason == "fast_unlinked_uber_refusal"
    assert confidence == Decimal("0.82")


def test_fast_unlinked_positive_payment_wins_over_old_refusal_text() -> None:
    message = InboundEmailMessage(
        from_email="restaurantsfrance@uber.com",
        subject="Re: Contestation de remboursement",
        snippet="Paiement accorde",
        body_text="Un paiement de 24,90 EUR a ete accorde. Ancien message cite: nous maintenons le refus.",
        match_status="unlinked",
    )

    review_type, reason, confidence = classify_unlinked_watched_message(message)

    assert review_type == "payment_confirmed"
    assert reason == "fast_unlinked_payment_positive"
    assert confidence == Decimal("0.84")


def test_starred_message_creates_watched_thread_and_work_item(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=False,
    )

    watched = db_session.scalar(select(GmailWatchedThread))
    assert watched is not None
    assert watched.gmail_thread_id == "thread-f93ba"
    assert watched.first_starred_message_id == "star-1"
    assert watched.star_active is True
    assert result.watched_threads_created == 1
    assert db_session.scalar(select(func.count(GmailStarredWorkItem.id))) == 1


def test_starred_discovery_ignores_non_uber_payloads(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [
        payload(
            "star-noise",
            thread_id="thread-noise",
            from_email="newsletter@example.com",
            body="Nous maintenons le refus pour F93BA.",
            starred=True,
        )
    ]
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=False,
    )

    assert result.watched_threads_created == 0
    assert result.work_items_created == 0
    assert db_session.scalar(select(func.count(GmailWatchedThread.id))) == 0
    assert db_session.scalar(select(func.count(GmailStarredWorkItem.id))) == 0


def test_lightweight_starred_discovery_creates_watched_thread_without_payload_fetch(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeLightweightWatchedGmailProvider()
    starred_uber_query = f"{GMAIL_STARRED_URGENT_QUERY} from:uber.com"
    provider.starred_refs_by_query = {
        starred_uber_query: [{"id": "star-ref-1", "threadId": "thread-ref-1"}]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=False,
    )

    assert provider.ref_queries == [starred_uber_query]
    assert provider.full_history_calls == []
    assert db_session.scalar(select(func.count(InboundEmailMessage.id))) == 0
    watched = db_session.scalar(select(GmailWatchedThread))
    assert watched is not None
    assert watched.gmail_thread_id == "thread-ref-1"
    assert watched.first_starred_message_id == "star-ref-1"
    work_item = db_session.scalar(select(GmailStarredWorkItem))
    assert work_item is not None
    assert work_item.inbound_message_id is None
    assert work_item.provider_message_id == "star-ref-1"
    assert result.watched_threads_created == 1
    assert result.work_items_created == 1


def test_starred_identity_repair_reuses_existing_order_after_duplicate_race(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _account, order = gmail_case
    original_find_existing = identity_repair_service.find_existing_order_for_identity
    calls = 0

    def miss_once_then_find(db: Session, restaurant_id: int, identity: ResolvedOrderIdentity) -> ClaimOrder | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_find_existing(db, restaurant_id, identity)

    monkeypatch.setattr(identity_repair_service, "find_existing_order_for_identity", miss_once_then_find)

    linked = identity_repair_service.create_or_update_order_from_identity(
        db_session,
        owner,
        order.restaurant,
        ResolvedOrderIdentity(
            order_number="F93BA",
            display_id="F93BA",
            customer_name="Yoann O.",
            order_date=date(2026, 6, 18),
            order_amount=Decimal("24.99"),
            currency="EUR",
            source="test",
        ),
        source="test",
        case_type="refund",
    )

    assert linked is not None
    assert linked.id == order.id
    assert calls >= 2
    assert (
        db_session.scalar(
            select(func.count(ClaimOrder.id)).where(
                ClaimOrder.restaurant_id == order.restaurant_id,
                ClaimOrder.uber_order_number == "F93BA",
            )
        )
        == 1
    )


def test_starred_discovery_uses_full_history_not_cycle_limit(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    monkeypatch.setenv("GMAIL_STARRED_FULL_HISTORY_ENABLED", "true")
    monkeypatch.setenv("GMAIL_STARRED_MAX_MESSAGES_PER_SYNC", "2")
    monkeypatch.setenv("GMAIL_WATCHED_THREADS_MAX_PER_CYCLE", "2")
    get_settings.cache_clear()
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [
        payload(f"star-{index}", thread_id=f"thread-{index}", starred=True)
        for index in range(5)
    ]
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=False,
    )

    assert provider.full_history_calls == [GMAIL_STARRED_URGENT_QUERY]
    assert result.watched_threads_created == 5
    assert db_session.scalar(select(func.count(GmailWatchedThread.id))) == 5


def test_starred_discovery_falls_back_to_label_starred_query(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    monkeypatch.setenv("GMAIL_STARRED_FULL_HISTORY_ENABLED", "true")
    get_settings.cache_clear()
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads_by_query = {
        "in:anywhere label:starred": [payload("star-fallback", starred=True)]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=False,
    )

    assert provider.full_history_calls[:2] == list(GMAIL_STARRED_URGENT_QUERIES[:2])
    assert result.watched_threads_created == 1
    watched = db_session.scalar(select(GmailWatchedThread))
    assert watched is not None
    assert watched.first_starred_message_id == "star-fallback"


def test_existing_refused_watched_thread_sends_same_thread_reply_without_global_autopilot(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="star-1",
        provider_thread_id="thread-f93ba",
        gmail_history_id="history-star-1",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation de remboursement de commande F93BA",
        snippet="Uber refuse la demande pour la commande F93BA.",
        body_text="Uber refuse la demande pour la commande F93BA.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        first_starred_message_id="star-1",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    db_session.add(
        GmailStarredWorkItem(
            watched_thread_id=watched.id,
            email_account_id=account.id,
            gmail_thread_id="thread-f93ba",
            provider_message_id="star-1",
            inbound_message_id=inbound.id,
            status="refused",
            reason="uber_refusal",
            processed_at=utc_now(),
        )
    )
    db_session.commit()
    provider = FakeWatchedGmailProvider()
    provider.provider_thread_id_for_drafts = "wrong-thread-for-same-order"

    def fail_global_autopilot(self, db, user, result):  # noqa: ANN001, ARG001
        raise AssertionError("watched Gmail worker must not run the global autopilot scan")

    monkeypatch.setattr(
        GmailInboundSyncService,
        "run_autopilot_for_negative_responses",
        fail_global_autopilot,
    )

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    assert result.actionable_refused_threads == 1
    assert result.autopilot_sent_count == 1
    assert result.autopilot_skipped_count == 0
    assert result.autopilot_failed_count == 0
    assert len(provider.created_drafts) == 1
    assert provider.created_draft_thread_ids == ["thread-f93ba"]
    assert len(provider.sent_drafts) == 1
    attempt = db_session.scalar(select(AppealAttempt))
    assert attempt is not None
    assert attempt.status == "sent"
    assert attempt.based_on_refusal_message_id == inbound.id
    provider_draft = attempt.provider_draft
    assert provider_draft is not None
    assert provider_draft.status == "sent"
    assert provider_draft.provider_thread_id == "thread-f93ba"
    work_item = db_session.scalar(select(GmailStarredWorkItem))
    assert work_item is not None
    assert work_item.status == "processed"
    assert work_item.reason == "gmail_reply_sent"


def test_refused_reply_already_sent_workflow_after_provider_send_counts_as_success(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="reply-refused-workflow-already-sent",
        provider_thread_id="thread-f93ba",
        gmail_history_id="history-reply-refused-workflow-already-sent",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation de remboursement de commande F93BA",
        snippet="Nous maintenons le refus.",
        body_text="Nous maintenons le refus pour la commande F93BA.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        first_starred_message_id="star-1",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        provider_message_id="reply-refused-workflow-already-sent",
        inbound_message_id=inbound.id,
        status="refused",
        reason="uber_refusal",
        processed_at=utc_now(),
    )
    db_session.add(item)
    db_session.commit()

    def raise_already_sent(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AppealWorkflowError("Appeal attempt is already marked as sent", 409)

    monkeypatch.setattr(
        "app.services.gmail_watched_thread_monitor_service.mark_appeal_sent",
        raise_already_sent,
    )

    provider = FakeWatchedGmailProvider()
    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    db_session.refresh(item)
    assert result.autopilot_sent_count == 1
    assert result.autopilot_failed_count == 0
    assert provider.created_draft_account_ids == [account.id]
    assert item.status == "processed"
    assert item.reason == "gmail_reply_sent"


def test_refused_work_items_are_sent_before_older_evidence_requests(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    old_evidence_message = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="reply-proof-older",
        provider_thread_id="thread-proof-older",
        gmail_history_id="history-proof-older",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Preuve commande F93BA",
        snippet="Merci de fournir une preuve.",
        body_text="Merci de fournir une preuve pour cette commande.",
        received_at=utc_now() - timedelta(days=2),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    refusal_message = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="reply-refused-newer",
        provider_thread_id="thread-refused-newer",
        gmail_history_id="history-refused-newer",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Refus commande F93BA",
        snippet="Nous maintenons le refus.",
        body_text="Nous maintenons le refus pour la commande F93BA.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add_all([old_evidence_message, refusal_message])
    db_session.flush()
    old_evidence_thread = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-proof-older",
        first_starred_message_id="reply-proof-older",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    refusal_thread = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-refused-newer",
        first_starred_message_id="reply-refused-newer",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add_all([old_evidence_thread, refusal_thread])
    db_session.flush()
    evidence_item = GmailStarredWorkItem(
        watched_thread_id=old_evidence_thread.id,
        email_account_id=account.id,
        gmail_thread_id="thread-proof-older",
        provider_message_id="reply-proof-older",
        inbound_message_id=old_evidence_message.id,
        status="evidence_needed",
        reason="evidence_requested",
        processed_at=utc_now() - timedelta(days=2),
    )
    refused_item = GmailStarredWorkItem(
        watched_thread_id=refusal_thread.id,
        email_account_id=account.id,
        gmail_thread_id="thread-refused-newer",
        provider_message_id="reply-refused-newer",
        inbound_message_id=refusal_message.id,
        status="refused",
        reason="uber_refusal",
        processed_at=utc_now(),
    )
    db_session.add_all([evidence_item, refused_item])
    db_session.commit()

    result = GmailWatchedThreadMonitorResult()
    GmailWatchedThreadMonitorService(FakeWatchedGmailProvider()).send_pending_actionable_replies(
        db_session,
        owner,
        account,
        result=result,
        max_items=1,
    )

    db_session.refresh(evidence_item)
    db_session.refresh(refused_item)
    assert result.autopilot_sent_count == 1
    assert refused_item.status == "processed"
    assert refused_item.reason == "gmail_reply_sent"
    assert evidence_item.status == "evidence_needed"


def test_refused_watched_thread_repairs_missing_order_from_thread_text_before_reply(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    thread_body = (
        "Bonjour, je veux contester la demande de remboursement de Yoann O. "
        "numero de commande F93BA pour le restaurant Frit Dodo. "
        "Montant concerne : 24.99 EUR. Date commande : 18/06/2026. "
        "Uber refuse la demande."
    )
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=None,
        provider="gmail",
        provider_message_id="star-unlinked-f93ba",
        provider_thread_id="thread-unlinked-f93ba",
        gmail_history_id="history-star-unlinked-f93ba",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation de remboursement de commande F93BA",
        snippet="Uber refuse la demande pour la commande F93BA.",
        body_text=thread_body,
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="unlinked",
        match_reason="no_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-unlinked-f93ba",
        first_starred_message_id="star-unlinked-f93ba",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    db_session.add(
        GmailStarredWorkItem(
            watched_thread_id=watched.id,
            email_account_id=account.id,
            gmail_thread_id="thread-unlinked-f93ba",
            provider_message_id="star-unlinked-f93ba",
            inbound_message_id=inbound.id,
            status="refused",
            reason="uber_refusal",
            processed_at=utc_now(),
        )
    )
    db_session.commit()
    provider = FakeFastWatchedGmailProvider()
    provider.provider_thread_id_for_drafts = "thread-unlinked-f93ba"
    provider.latest_payloads = {
        "thread-unlinked-f93ba": payload(
            "latest-refusal-only",
            thread_id="thread-unlinked-f93ba",
            subject="Re: Contestation de remboursement de commande",
            body="Bonjour, nous refusons la demande.",
            starred=False,
        )
    }
    provider.thread_payloads = {
        "thread-unlinked-f93ba": [
            payload(
                "star-unlinked-f93ba",
                thread_id="thread-unlinked-f93ba",
                subject="Re: Contestation de remboursement de commande F93BA",
                body=thread_body,
                starred=True,
            )
        ]
    }

    def fail_global_autopilot(self, db, user, result):  # noqa: ANN001, ARG001
        raise AssertionError("watched Gmail worker must not run the global autopilot scan")

    monkeypatch.setattr(
        GmailInboundSyncService,
        "run_autopilot_for_negative_responses",
        fail_global_autopilot,
    )

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    assert result.actionable_refused_threads == 1
    assert result.autopilot_sent_count == 1
    assert result.autopilot_skipped_count == 1
    assert len(provider.sent_drafts) == 1
    db_session.refresh(inbound)
    db_session.refresh(watched)
    assert inbound.order_id == order.id
    assert watched.claim_order_id == order.id
    assert watched.linked_case_type == "claim_order"
    assert watched.linked_case_id == order.id
    attempt = db_session.scalar(select(AppealAttempt))
    assert attempt is not None
    assert attempt.status == "sent"
    assert attempt.based_on_refusal_message_id == inbound.id
    provider_draft = attempt.provider_draft
    assert provider_draft is not None
    assert provider_draft.status == "sent"
    assert provider_draft.provider_thread_id == "thread-unlinked-f93ba"
    work_item_reasons = {
        reason
        for reason, in db_session.execute(
            select(GmailStarredWorkItem.reason).where(
                GmailStarredWorkItem.gmail_thread_id == "thread-unlinked-f93ba",
            )
        )
    }
    assert "gmail_reply_sent" in work_item_reasons
    assert "uber_refusal" in work_item_reasons


def test_already_replied_refusal_leaves_actionable_queue(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="reply-refused-already-sent",
        provider_thread_id="thread-f93ba",
        gmail_history_id="history-reply-refused-already-sent",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation de remboursement de commande F93BA",
        snippet="Nous maintenons le refus.",
        body_text="Nous maintenons le refus pour la commande F93BA.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        first_starred_message_id="star-1",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    draft = EmailDraft(
        order_id=order.id,
        draft_type="appeal_generic_refusal",
        subject="Re: Contestation de remboursement de commande F93BA",
        body="Bonjour, je conteste.",
        status="created",
    )
    db_session.add(draft)
    db_session.flush()
    provider_draft = EmailProviderDraft(
        email_draft_id=draft.id,
        email_account_id=account.id,
        provider="gmail",
        provider_draft_id="draft-already-sent",
        provider_thread_id="thread-f93ba",
        provider_message_id="sent-already",
        to_email="restaurantsfrance@uber.com",
        subject=draft.subject,
        status="sent",
        sent_at=utc_now(),
        created_by_user_id=owner.id,
    )
    db_session.add(provider_draft)
    db_session.flush()
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_sent",
        next_action_type="send_manual_appeal",
    )
    db_session.add(workflow)
    db_session.flush()
    db_session.add(
        AppealAttempt(
            workflow_id=workflow.id,
            attempt_number=1,
            appeal_type="first_appeal",
            status="sent",
            based_on_refusal_message_id=inbound.id,
            email_draft_id=draft.id,
            provider_draft_id=provider_draft.id,
            created_by_user_id=owner.id,
        )
    )
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        provider_message_id="reply-refused-already-sent",
        inbound_message_id=inbound.id,
        status="refused",
        reason="uber_refusal",
        processed_at=utc_now(),
    )
    db_session.add(item)
    db_session.commit()

    result = GmailWatchedThreadMonitorService(FakeWatchedGmailProvider()).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    db_session.refresh(item)
    assert result.autopilot_sent_count == 0
    assert result.autopilot_skipped_count == 1
    assert item.status == "skipped"
    assert item.reason == "already_replied_to_refusal"


def test_failed_refusal_provider_draft_is_recreated_before_autopilot_send(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="reply-refused-failed-draft",
        provider_thread_id="thread-failed-draft",
        gmail_history_id="history-reply-refused-failed-draft",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation de remboursement de commande F93BA",
        snippet="Nous maintenons le refus.",
        body_text="Nous maintenons le refus pour la commande F93BA.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-failed-draft",
        first_starred_message_id="star-failed-draft",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    draft = EmailDraft(
        order_id=order.id,
        draft_type="appeal_generic_refusal",
        subject="Re: Contestation de remboursement de commande F93BA",
        body="Bonjour, je conteste.",
        status="created",
    )
    db_session.add(draft)
    db_session.flush()
    provider_draft = EmailProviderDraft(
        email_draft_id=draft.id,
        email_account_id=account.id,
        provider="gmail",
        provider_draft_id="draft-failed",
        provider_thread_id="thread-failed-draft",
        to_email="restaurantsfrance@uber.com",
        subject=draft.subject,
        status="failed",
        last_error="previous send failed",
        created_by_user_id=owner.id,
    )
    db_session.add(provider_draft)
    db_session.flush()
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        next_action_type="send_manual_appeal",
    )
    db_session.add(workflow)
    db_session.flush()
    failed_attempt = AppealAttempt(
        workflow_id=workflow.id,
        attempt_number=1,
        appeal_type="first_appeal",
        status="gmail_draft_created",
        based_on_refusal_message_id=inbound.id,
        email_draft_id=draft.id,
        provider_draft_id=provider_draft.id,
        created_by_user_id=owner.id,
    )
    db_session.add(failed_attempt)
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        gmail_thread_id="thread-failed-draft",
        provider_message_id="reply-refused-failed-draft",
        inbound_message_id=inbound.id,
        status="refused",
        reason="uber_refusal",
        processed_at=utc_now(),
    )
    db_session.add(item)
    db_session.commit()

    provider = FakeWatchedGmailProvider()
    provider.provider_thread_id_for_drafts = "thread-failed-draft"
    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    db_session.refresh(item)
    db_session.refresh(provider_draft)
    sent_provider_draft = db_session.scalar(
        select(EmailProviderDraft)
        .where(EmailProviderDraft.id != provider_draft.id, EmailProviderDraft.status == "sent")
        .order_by(EmailProviderDraft.id.desc())
    )
    sent_attempt = db_session.scalar(
        select(AppealAttempt)
        .where(AppealAttempt.id != failed_attempt.id)
        .order_by(AppealAttempt.id.desc())
    )
    assert result.autopilot_sent_count == 1
    assert result.autopilot_failed_count == 0
    assert provider.created_draft_account_ids == [account.id]
    assert item.status == "processed"
    assert item.reason == "gmail_reply_sent"
    assert provider_draft.status == "failed"
    assert sent_provider_draft is not None
    assert sent_provider_draft.provider_thread_id == "thread-failed-draft"
    assert sent_attempt is not None
    assert sent_attempt.status == "sent"
    assert sent_attempt.based_on_refusal_message_id == inbound.id


@pytest.mark.parametrize("old_provider_status", ["provider_draft_created", "sent"])
def test_crousty_best_refusal_reply_is_reissued_once_with_asian_passion(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
    old_provider_status: str,
) -> None:
    owner, account, order = gmail_case
    order.restaurant.name = "Crousty Best"
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id=f"reply-crousty-best-{old_provider_status}",
        provider_thread_id=f"thread-crousty-best-{old_provider_status}",
        gmail_history_id=f"history-crousty-best-{old_provider_status}",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation Crousty Best F93BA",
        snippet="Nous maintenons le refus.",
        body_text="Nous maintenons le refus pour la commande F93BA.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id=inbound.provider_thread_id,
        first_starred_message_id=inbound.provider_message_id,
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    old_draft = EmailDraft(
        order_id=order.id,
        draft_type="appeal_generic_refusal",
        subject="Re: Contestation Crousty Best F93BA",
        body="Bonjour, je relance pour Crousty Best.\n\nCrousty Best",
        status="created",
    )
    db_session.add(old_draft)
    db_session.flush()
    old_provider_draft = EmailProviderDraft(
        email_draft_id=old_draft.id,
        email_account_id=account.id,
        provider="gmail",
        provider_draft_id=f"draft-crousty-best-{old_provider_status}",
        provider_thread_id=inbound.provider_thread_id,
        provider_message_id="old-sent-message" if old_provider_status == "sent" else None,
        to_email="restaurantsfrance@uber.com",
        subject=old_draft.subject,
        status=old_provider_status,
        sent_at=utc_now() if old_provider_status == "sent" else None,
        created_by_user_id=owner.id,
    )
    db_session.add(old_provider_draft)
    db_session.flush()
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_sent" if old_provider_status == "sent" else "appeal_needed",
        next_action_type="review_refusal" if old_provider_status == "sent" else "send_manual_appeal",
        appeal_attempt_count=1 if old_provider_status == "sent" else 0,
    )
    db_session.add(workflow)
    db_session.flush()
    old_attempt = AppealAttempt(
        workflow_id=workflow.id,
        attempt_number=1,
        appeal_type="first_appeal",
        status="sent" if old_provider_status == "sent" else "gmail_draft_created",
        based_on_refusal_message_id=inbound.id,
        email_draft_id=old_draft.id,
        provider_draft_id=old_provider_draft.id,
        created_by_user_id=owner.id,
        sent_by_user_id=owner.id if old_provider_status == "sent" else None,
        sent_at=utc_now() if old_provider_status == "sent" else None,
    )
    db_session.add(old_attempt)
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        gmail_thread_id=watched.gmail_thread_id,
        provider_message_id=inbound.provider_message_id,
        inbound_message_id=inbound.id,
        status="refused",
        reason="restaurant_identity_rename_requeue",
        processed_at=utc_now(),
    )
    db_session.add(item)
    db_session.commit()

    provider = FakeWatchedGmailProvider()
    provider.provider_thread_id_for_drafts = watched.gmail_thread_id
    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    new_attempt = db_session.scalar(
        select(AppealAttempt)
        .where(AppealAttempt.id != old_attempt.id)
        .order_by(AppealAttempt.id.desc())
    )
    db_session.refresh(old_provider_draft)
    assert result.autopilot_sent_count == 1
    assert result.autopilot_failed_count == 0
    assert len(provider.sent_drafts) == 1
    assert new_attempt is not None
    assert new_attempt.status == "sent"
    assert new_attempt.email_draft is not None
    assert "Asian Passion" in new_attempt.email_draft.subject
    assert "Asian Passion" in new_attempt.email_draft.body
    assert "Crousty Best" not in new_attempt.email_draft.subject
    assert "Crousty Best" not in new_attempt.email_draft.body
    expected_old_status = "failed" if old_provider_status == "provider_draft_created" else "sent"
    assert old_provider_draft.status == expected_old_status
    if old_provider_status == "provider_draft_created":
        assert old_provider_draft.last_error == "superseded_restaurant_identity"


def test_missing_gmail_thread_during_identity_repair_does_not_stop_actionable_queue(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=None,
        provider="gmail",
        provider_message_id="reply-missing-thread",
        provider_thread_id="thread-missing",
        gmail_history_id="history-reply-missing-thread",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation Uber",
        snippet="Nous maintenons le refus.",
        body_text="Nous maintenons le refus.",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="unlinked",
        match_reason="no_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-missing",
        first_starred_message_id="reply-missing-thread",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        gmail_thread_id="thread-missing",
        provider_message_id="reply-missing-thread",
        inbound_message_id=inbound.id,
        status="refused",
        reason="uber_refusal",
        processed_at=utc_now(),
    )
    db_session.add(item)
    db_session.commit()

    class MissingThreadProvider(FakeWatchedGmailProvider):
        def get_thread_messages_for_account(
            self,
            db: Session,
            account: EmailAccount,
            thread_id: str,
            *,
            include_attachments: bool = True,
        ) -> list[InboundEmailPayload]:
            raise EmailProviderError("Gmail API error: NOT_FOUND - Requested entity was not found.", 502)

    result = GmailWatchedThreadMonitorResult()
    GmailWatchedThreadMonitorService(MissingThreadProvider()).send_pending_actionable_replies(
        db_session,
        owner,
        account,
        result=result,
        max_items=1,
    )

    db_session.refresh(item)
    assert result.autopilot_sent_count == 0
    assert result.autopilot_skipped_count == 1
    assert item.status == "manual_review"
    assert item.reason.startswith("identity_repair_failed:Gmail API error: NOT_FOUND")


def test_missing_watched_thread_is_closed_and_removed_from_hot_queue(
    db_session: Session,
    gmail_case,
) -> None:
    owner, account, _order = gmail_case
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=None,
        provider="gmail",
        provider_message_id="missing-star-1",
        provider_thread_id="missing-thread-1",
        gmail_history_id="missing-history-1",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation Uber",
        snippet="Conversation supprimee",
        body_text="Conversation supprimee",
        received_at=utc_now(),
        raw_headers_json={},
        provider_labels_json=["INBOX", "STARRED"],
        match_status="unlinked",
        match_reason="no_match",
        review_status="unreviewed",
    )
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="missing-thread-1",
        first_starred_message_id="missing-star-1",
        status="active",
        star_active=True,
    )
    db_session.add_all([inbound, watched])
    db_session.flush()
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        gmail_thread_id=watched.gmail_thread_id,
        provider_message_id=inbound.provider_message_id,
        inbound_message_id=None,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()

    class MissingWatchedThreadProvider(FakeLightweightWatchedGmailProvider):
        def __init__(self) -> None:
            super().__init__()
            self.fetch_count = 0

        def get_thread_messages_for_account(
            self,
            db: Session,
            account: EmailAccount,
            thread_id: str,
            *,
            include_attachments: bool = True,
        ) -> list[InboundEmailPayload]:
            self.fetch_count += 1
            raise EmailProviderError("Gmail API error: NOT_FOUND - Requested entity was not found.", 502)

    provider = MissingWatchedThreadProvider()
    provider.starred_refs_by_query = {
        f"{GMAIL_STARRED_URGENT_QUERY} from:uber.com": [
            {"id": inbound.provider_message_id, "threadId": watched.gmail_thread_id}
        ]
    }
    service = GmailWatchedThreadMonitorService(provider)

    first_result = service.process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=True,
    )
    second_result = service.process_account(
        db_session,
        owner,
        account,
        discover_starred=True,
        process_new_messages=True,
    )

    db_session.refresh(inbound)
    db_session.refresh(watched)
    db_session.refresh(item)
    assert first_result.errors == []
    assert second_result.errors == []
    assert second_result.processed_messages == 0
    assert provider.fetch_count == 1
    assert watched.status == "closed"
    assert watched.star_active is False
    assert item.status == "skipped"
    assert item.reason == "gmail_thread_not_found"
    assert "STARRED" not in inbound.provider_labels_json


def test_non_starred_positive_reply_in_watched_thread_is_processed_and_star_removed(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("star-1", starred=True),
            payload("reply-positive-1", body="Bonjour, un paiement de 24.99 EUR est accorde pour F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(db_session, owner, account)

    watched = db_session.scalar(select(GmailWatchedThread))
    assert watched is not None
    assert watched.status == "payment_confirmed"
    assert watched.star_active is False
    assert ("star-1", "STARRED") in provider.removed_labels
    positive_item = db_session.scalar(
        select(GmailStarredWorkItem).where(GmailStarredWorkItem.provider_message_id == "reply-positive-1")
    )
    assert positive_item is not None
    assert positive_item.status == "positive"
    assert result.positive_responses >= 1


def test_positive_watched_thread_removes_every_starred_message_in_thread(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("star-1", starred=True),
            payload("star-2", body="Ancienne relance a verifier.", starred=True),
            payload("reply-positive-1", body="Bonjour, un paiement de 24.99 EUR est accorde pour F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(db_session, owner, account)

    watched = db_session.scalar(select(GmailWatchedThread))
    assert watched is not None
    assert watched.star_active is False
    assert set(provider.removed_labels) == {("star-1", "STARRED"), ("star-2", "STARRED")}
    assert result.positive_responses >= 1


def test_watched_thread_processes_only_latest_external_reply(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("sent-1", from_email=account.email_address, body="Bonjour je conteste F93BA."),
            payload("reply-old-1", body="Nous maintenons le refus pour F93BA."),
            payload("sent-2", from_email=account.email_address, body="Merci de reexaminer F93BA."),
            payload("reply-positive-1", body="Bonjour, un paiement de 24.99 EUR est accorde pour F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(db_session, owner, account)

    assert result.processed_messages == 1
    assert db_session.scalar(
        select(func.count(GmailStarredWorkItem.id)).where(
            GmailStarredWorkItem.provider_message_id == "reply-positive-1"
        )
    ) == 1
    assert db_session.scalar(
        select(func.count(GmailStarredWorkItem.id)).where(GmailStarredWorkItem.provider_message_id == "reply-old-1")
    ) == 0


def test_watched_thread_skips_non_uber_external_reply(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-noise",
        first_starred_message_id="star-noise",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.commit()
    provider = FakeWatchedGmailProvider()
    provider.thread_payloads = {
        "thread-noise": [
            payload(
                "reply-noise",
                thread_id="thread-noise",
                from_email="newsletter@example.com",
                body="Bonjour, un paiement de 24.99 EUR est accorde pour F93BA.",
                starred=True,
            )
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    assert result.processed_messages == 0
    assert result.work_items_created == 0
    assert db_session.scalar(
        select(InboundEmailMessage).where(InboundEmailMessage.provider_message_id == "reply-noise")
    ) is None


def test_watched_thread_uses_fast_latest_external_message_when_available(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    provider = FakeFastWatchedGmailProvider()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        first_starred_message_id="star-1",
        claim_order_id=order.id,
        linked_case_type="claim_order",
        linked_case_id=order.id,
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.commit()
    provider.latest_payloads = {
        "thread-f93ba": payload(
            "reply-positive-fast",
            body="Bonjour, un paiement de 24.99 EUR est accorde pour F93BA.",
        )
    }
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("sent-1", from_email=account.email_address, body="Bonjour je conteste F93BA."),
            payload("reply-old-1", body="Nous maintenons le refus pour F93BA."),
            payload("reply-positive-fast", body="Bonjour, un paiement de 24.99 EUR est accorde pour F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    assert provider.latest_calls == ["thread-f93ba"]
    assert provider.thread_include_attachments_calls == []
    assert result.processed_messages == 1
    assert db_session.scalar(
        select(func.count(GmailStarredWorkItem.id)).where(
            GmailStarredWorkItem.provider_message_id == "reply-positive-fast"
        )
    ) == 1


def test_unlinked_watched_thread_prefers_latest_external_before_full_thread(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeFastWatchedGmailProvider()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-unlinked",
        first_starred_message_id="star-unlinked",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.commit()
    provider.latest_payloads = {
        "thread-unlinked": payload(
            "reply-positive-latest",
            thread_id="thread-unlinked",
            subject="Re: Contestation Uber sans identifiant local",
            body="Bonjour, un paiement de 24.99 EUR est accorde.",
        )
    }
    provider.thread_payloads = {
        "thread-unlinked": [
            payload(
                "sent-unlinked",
                thread_id="thread-unlinked",
                from_email=account.email_address,
                subject="Re: Contestation Uber",
                body="Bonjour je conteste cette commande.",
            ),
            payload(
                "reply-positive-full",
                thread_id="thread-unlinked",
                subject="Re: Contestation Uber sans identifiant local",
                body="Bonjour, un paiement de 24.99 EUR est accorde.",
            ),
        ]
    }

    def fail_reprocess(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unlinked watched threads must use the fast classifier")

    def fail_identity_repair(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unlinked watched threads must not run slow identity repair")

    monkeypatch.setattr(GmailInboundSyncService, "reprocess_existing_message", fail_reprocess)
    monkeypatch.setattr(
        GmailWatchedThreadMonitorService,
        "repair_watched_thread_from_payloads",
        fail_identity_repair,
    )

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    assert provider.latest_calls == ["thread-unlinked"]
    assert provider.thread_include_attachments_calls == []
    assert result.processed_messages == 1
    positive_item = db_session.scalar(
        select(GmailStarredWorkItem).where(GmailStarredWorkItem.provider_message_id == "reply-positive-latest")
    )
    assert positive_item is not None
    assert positive_item.status == "positive"


def test_pending_local_work_item_is_processed_before_fetching_gmail(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeFastWatchedGmailProvider()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-local-backlog",
        first_starred_message_id="star-local-backlog",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    message = InboundEmailMessage(
        email_account_id=account.id,
        provider="gmail",
        provider_message_id="reply-local-refusal",
        provider_thread_id="thread-local-backlog",
        from_email="restaurantsfrance@uber.com",
        to_email=account.email_address,
        subject="Re: Contestation Uber",
        snippet="Nous maintenons le refus.",
        body_text="Bonjour, nous maintenons le refus et aucun remboursement ne sera applique.",
        received_at=utc_now(),
        raw_headers_json={"from": "restaurantsfrance@uber.com", "to": account.email_address},
        provider_labels_json=["INBOX"],
        match_status="unlinked",
        review_status="unreviewed",
    )
    db_session.add(message)
    db_session.flush()
    item = GmailStarredWorkItem(
        watched_thread_id=watched.id,
        email_account_id=account.id,
        inbound_message_id=message.id,
        gmail_thread_id=watched.gmail_thread_id,
        provider_message_id=message.provider_message_id,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()

    def fail_reprocess(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unlinked local backlog must use the fast classifier")

    monkeypatch.setattr(GmailInboundSyncService, "reprocess_existing_message", fail_reprocess)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        max_threads=1,
        discover_starred=False,
        process_new_messages=True,
    )

    assert provider.latest_calls == []
    assert provider.thread_include_attachments_calls == []
    assert result.processed_messages == 1
    assert result.refused_responses == 1
    db_session.refresh(item)
    assert item.status == "refused"
    assert item.reason == "uber_refusal"


def test_unlinked_watched_thread_fast_classifies_refusal_without_heavy_reprocess(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-unlinked-refusal",
        first_starred_message_id="star-unlinked-refusal",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.commit()
    provider.thread_payloads = {
        "thread-unlinked-refusal": [
            payload(
                "sent-unlinked-refusal",
                thread_id="thread-unlinked-refusal",
                from_email=account.email_address,
                subject="Re: Contestation Uber",
                body="Bonjour je conteste cette commande.",
            ),
            payload(
                "reply-unlinked-refusal",
                thread_id="thread-unlinked-refusal",
                subject="Re: Contestation Uber",
                body="Bonjour, nous maintenons le refus et aucun remboursement ne sera applique.",
            ),
        ]
    }

    def fail_reprocess(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unlinked watched threads must use the fast classifier")

    monkeypatch.setattr(GmailInboundSyncService, "reprocess_existing_message", fail_reprocess)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    watched = db_session.scalar(
        select(GmailWatchedThread).where(GmailWatchedThread.gmail_thread_id == "thread-unlinked-refusal")
    )
    assert watched is not None
    assert watched.status == "active"
    assert watched.star_active is True
    refused_item = db_session.scalar(
        select(GmailStarredWorkItem).where(GmailStarredWorkItem.provider_message_id == "reply-unlinked-refusal")
    )
    assert refused_item is not None
    assert refused_item.status == "refused"
    assert result.processed_messages == 1
    assert result.refused_responses == 1
    assert result.actionable_refused_threads == 1


def test_watched_thread_skips_final_latest_message_before_identity_repair(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeFastWatchedGmailProvider()
    watched = GmailWatchedThread(
        email_account_id=account.id,
        gmail_thread_id="thread-f93ba",
        first_starred_message_id="star-1",
        status="active",
        star_active=True,
    )
    db_session.add(watched)
    db_session.flush()
    db_session.add(
        GmailStarredWorkItem(
            watched_thread_id=watched.id,
            email_account_id=account.id,
            gmail_thread_id="thread-f93ba",
            provider_message_id="reply-refused-fast",
            status="refused",
            processed_at=utc_now(),
        )
    )
    db_session.commit()
    provider.latest_payloads = {
        "thread-f93ba": payload(
            "reply-refused-fast",
            body="Bonjour, nous maintenons le refus pour la commande F93BA.",
        )
    }
    repair_calls: list[str] = []

    def fake_repair(
        self: GmailWatchedThreadMonitorService,
        db: Session,
        user: User,
        watched_thread: GmailWatchedThread,
        payloads: list[InboundEmailPayload],
    ) -> ClaimOrder | None:
        repair_calls.append(watched_thread.gmail_thread_id)
        return None

    monkeypatch.setattr(
        GmailWatchedThreadMonitorService,
        "repair_watched_thread_from_payloads",
        fake_repair,
    )
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        discover_starred=False,
        process_new_messages=True,
    )

    assert provider.latest_calls == ["thread-f93ba"]
    assert provider.thread_include_attachments_calls == []
    assert repair_calls == []
    assert result.processed_messages == 0
    assert result.actionable_refused_threads == 1


def test_non_starred_refusal_reply_keeps_thread_star_active(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("star-1", starred=True),
            payload("reply-refused-1", body="Nous maintenons le refus pour la commande F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(db_session, owner, account)

    watched = db_session.scalar(select(GmailWatchedThread))
    assert watched is not None
    assert watched.status == "active"
    assert watched.star_active is True
    assert provider.removed_labels == []
    refused_item = db_session.scalar(
        select(GmailStarredWorkItem).where(GmailStarredWorkItem.provider_message_id == "reply-refused-1")
    )
    assert refused_item is not None
    assert refused_item.status == "refused"
    assert result.refused_responses >= 1


def test_evidence_request_in_watched_thread_creates_task(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("star-1", starred=True),
            payload("reply-proof-1", body="Merci de fournir une preuve pour la commande F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(db_session, owner, account)

    task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.order_id == order.id))
    assert task is not None
    assert task.status == "pending"
    assert task.priority == "urgent"
    proof_item = db_session.scalar(
        select(GmailStarredWorkItem).where(GmailStarredWorkItem.provider_message_id == "reply-proof-1")
    )
    assert proof_item is not None
    assert proof_item.status == "evidence_needed"
    assert result.evidence_requests >= 1


def test_evidence_request_with_existing_proof_sends_gmail_reply(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, order = gmail_case
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    db_session.add(
        EvidenceFile(
            order_id=order.id,
            evidence_type="preparation_proof",
            original_filename="ticket.jpg",
            storage_path="restaurant_1/order_1/ticket.jpg",
            storage_backend="local",
            mime_type="image/jpeg",
            file_size=123,
        )
    )
    db_session.commit()
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("star-1", starred=True),
            payload("reply-proof-1", body="Merci de fournir une preuve pour la commande F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)

    result = GmailWatchedThreadMonitorService(provider).process_account(db_session, owner, account)
    proof_item = db_session.scalar(
        select(GmailStarredWorkItem).where(GmailStarredWorkItem.provider_message_id == "reply-proof-1")
    )

    assert result.evidence_requests >= 1
    assert result.autopilot_sent_count == 1, proof_item.reason if proof_item else None
    assert result.autopilot_skipped_count == 0, proof_item.reason if proof_item else None
    assert len(provider.created_drafts) == 1
    assert len(provider.sent_drafts) == 1
    draft = db_session.scalar(select(EmailDraft).where(EmailDraft.draft_type == "proof_reply"))
    assert draft is not None
    provider_draft = db_session.get(EmailProviderDraft, provider.sent_drafts[0])
    assert provider_draft is not None
    assert provider_draft.status == "sent"
    assert provider_draft.provider_thread_id == "thread-f93ba"
    assert proof_item is not None
    assert proof_item.status == "processed"
    assert proof_item.reason == "gmail_proof_reply_sent"
    task = db_session.scalar(select(EvidenceRequestTask).where(EvidenceRequestTask.order_id == order.id))
    assert task is not None
    assert task.status == "completed"


def test_watched_thread_monitor_does_not_duplicate_work_items(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    provider.starred_payloads = [payload("star-1", starred=True)]
    provider.thread_payloads = {
        "thread-f93ba": [
            payload("star-1", starred=True),
            payload("reply-refused-1", body="Nous maintenons le refus pour la commande F93BA."),
        ]
    }
    install_fake_classifier(monkeypatch)
    service = GmailWatchedThreadMonitorService(provider)

    service.process_account(db_session, owner, account)
    service.process_account(db_session, owner, account)

    assert db_session.scalar(select(func.count(GmailWatchedThread.id))) == 1
    assert db_session.scalar(select(func.count(GmailStarredWorkItem.id))) == 2


def test_watched_thread_monitor_respects_cycle_limit(
    db_session: Session,
    gmail_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, account, _order = gmail_case
    provider = FakeWatchedGmailProvider()
    install_fake_classifier(monkeypatch)
    for index in range(3):
        watched = GmailWatchedThread(
            email_account_id=account.id,
            gmail_thread_id=f"thread-{index}",
            first_starred_message_id=f"star-{index}",
            status="active",
            star_active=True,
        )
        db_session.add(watched)
        provider.thread_payloads[f"thread-{index}"] = [
            payload(f"reply-{index}", thread_id=f"thread-{index}", body=f"Nous maintenons le refus {index}.")
        ]
    db_session.commit()

    result = GmailWatchedThreadMonitorService(provider).process_account(
        db_session,
        owner,
        account,
        max_threads=2,
        discover_starred=False,
    )

    assert result.processed_messages == 2
    assert db_session.scalar(select(func.count(GmailStarredWorkItem.id))) == 2
    assert provider.thread_include_attachments_calls == [False, False]
