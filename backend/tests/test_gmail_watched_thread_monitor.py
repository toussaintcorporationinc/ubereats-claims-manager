from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Generator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ClaimOrder,
    EmailAccount,
    EvidenceRequestTask,
    GmailResponseAnalysis,
    GmailStarredWorkItem,
    GmailWatchedThread,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.services.email_provider import InboundEmailPayload
from app.services.gmail_inbound_sync_service import GmailInboundSyncResult, GmailInboundSyncService
from app.services.gmail_watched_thread_monitor_service import GmailWatchedThreadMonitorService


class FakeWatchedGmailProvider:
    provider = "gmail"

    def __init__(self) -> None:
        self.starred_payloads: list[InboundEmailPayload] = []
        self.thread_payloads: dict[str, list[InboundEmailPayload]] = {}
        self.removed_labels: list[tuple[str, str]] = []
        self.full_history_calls: list[str] = []

    def sync_inbound_replies_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        if query != "is:starred":
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
        if query != "is:starred":
            return []
        return self.starred_payloads

    def get_thread_messages_for_account(
        self,
        db: Session,
        account: EmailAccount,
        thread_id: str,
    ) -> list[InboundEmailPayload]:
        return self.thread_payloads.get(thread_id, [])

    def remove_message_label_for_account(
        self,
        db: Session,
        account: EmailAccount,
        provider_message_id: str,
        label: str,
    ) -> None:
        self.removed_labels.append((provider_message_id, label))


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
    starred: bool = False,
) -> InboundEmailPayload:
    labels = ["INBOX"]
    if starred:
        labels.append("STARRED")
    return InboundEmailPayload(
        provider_message_id=provider_message_id,
        provider_thread_id=thread_id,
        gmail_history_id=f"history-{provider_message_id}",
        from_email="restaurantsfrance@uber.com",
        to_email="tiramisumaisonfrance@gmail.com",
        subject=subject,
        snippet=body[:120],
        body_text=body,
        received_at=utc_now(),
        raw_headers={
            "from": "restaurantsfrance@uber.com",
            "to": "tiramisumaisonfrance@gmail.com",
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

    assert provider.full_history_calls == ["is:starred"]
    assert result.watched_threads_created == 5
    assert db_session.scalar(select(func.count(GmailWatchedThread.id))) == 5


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
