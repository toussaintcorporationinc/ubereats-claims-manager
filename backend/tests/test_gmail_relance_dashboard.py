from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models import (
    AutopilotAction,
    AutopilotRun,
    ClaimOrder,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    GmailResponseAnalysis,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.services.email_provider import EmailConnectionStatus


class FakeGmailProvider:
    provider = "gmail"

    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        account = db.scalar(
            select(EmailAccount).where(
                EmailAccount.user_id == user.id,
                EmailAccount.provider == "gmail",
                EmailAccount.disconnected_at.is_(None),
            )
        )
        return EmailConnectionStatus(
            connected=account is not None,
            provider="gmail",
            email_address=account.email_address if account else None,
            enabled=True,
        )


@pytest.fixture()
def gmail_dashboard_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_ENABLED", "true")
    monkeypatch.setenv("GMAIL_INBOUND_AUTO_SYNC_CONTINUOUS_ENABLED", "true")
    monkeypatch.setenv("AI_GMAIL_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_FOLLOWUPS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    get_settings.cache_clear()
    app.dependency_overrides[get_gmail_provider] = lambda: FakeGmailProvider()
    yield
    app.dependency_overrides.pop(get_gmail_provider, None)
    get_settings.cache_clear()


def test_gmail_relance_dashboard_lists_starred_threads_sent_relances_and_actions(
    client: TestClient,
    db_session: Session,
    gmail_dashboard_enabled: None,
) -> None:
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
    db_session.flush()
    account = EmailAccount(
        user_id=owner.id,
        provider="gmail",
        email_address="tiramisumaisonfrance@gmail.com",
        connected_at=utc_now(),
    )
    db_session.add(account)
    db_session.flush()
    inbound = InboundEmailMessage(
        email_account_id=account.id,
        order_id=order.id,
        provider="gmail",
        provider_message_id="gmail-message-1",
        provider_thread_id="gmail-thread-1",
        from_email="restaurantsfrance@uber.com",
        to_email="tiramisumaisonfrance@gmail.com",
        subject="Re: Contestation de remboursement de commande",
        snippet="Nous ne pouvons pas donner suite a cette demande.",
        body_text="Nous refusons la demande.",
        received_at=utc_now(),
        provider_labels_json=["INBOX", "STARRED"],
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(inbound)
    db_session.flush()
    analysis = GmailResponseAnalysis(
        inbound_message_id=inbound.id,
        order_id=order.id,
        recommended_review_type="refused",
        status="applied",
        confidence_score=Decimal("0.94"),
        reason="negative_uber_reply",
    )
    db_session.add(analysis)
    email_draft = EmailDraft(
        order_id=order.id,
        draft_type="followup_1",
        subject="Re: Contestation de remboursement de commande",
        body="Bonjour, merci de reexaminer le dossier.",
        status="ready",
    )
    db_session.add(email_draft)
    db_session.flush()
    provider_draft = EmailProviderDraft(
        email_draft_id=email_draft.id,
        email_account_id=account.id,
        provider="gmail",
        provider_draft_id="draft-1",
        provider_thread_id="gmail-thread-1",
        provider_message_id="sent-1",
        to_email="restaurantsfrance@uber.com",
        subject=email_draft.subject,
        status="sent",
        created_by_user_id=owner.id,
        sent_by_user_id=owner.id,
        sent_at=utc_now(),
    )
    db_session.add(provider_draft)
    run = AutopilotRun(
        started_by_user_id=None,
        status="completed",
        mode="appeals",
        total_candidates=1,
        sent_count=1,
        skipped_count=0,
        failed_count=0,
        completed_at=utc_now(),
    )
    db_session.add(run)
    db_session.flush()
    action = AutopilotAction(
        run_id=run.id,
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=restaurant.id,
        action_type="send_appeal",
        status="sent",
        reason="starred_gmail_refusal",
        email_draft_id=email_draft.id,
        provider_draft_id=provider_draft.id,
        sent_at=utc_now(),
    )
    db_session.add(action)
    db_session.commit()

    response = client.get("/v1/email/gmail/relances")

    assert response.status_code == 200
    payload = response.json()
    assert payload["worker"]["connected"] is True
    assert payload["summary"]["connected_accounts_count"] == 1
    assert payload["summary"]["starred_threads_seen"] == 1
    assert payload["summary"]["sent_relances_last_24h"] == 1
    assert payload["starred_threads"][0]["order"]["uber_order_number"] == "F93BA"
    assert payload["starred_threads"][0]["order"]["customer_name"] == "Yoann O."
    assert payload["sent_relances"][0]["provider_thread_id"] == "gmail-thread-1"
    assert payload["recent_actions"][0]["action_type"] == "send_appeal"
