from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AutopilotRun, EmailAccount, EmailDraft, EmailProviderDraft
from app.models.domain import utc_now

GMAIL_SEND_PACING_REASON = "gmail_account_send_pacing_active"
GMAIL_SEND_DAILY_LIMIT_REASON = "gmail_account_daily_limit_reached"
GMAIL_INITIAL_CLAIM_DUPLICATE_REASON = "gmail_initial_claim_already_sent"
GMAIL_SEND_ACCOUNT_MISSING_REASON = "gmail_send_account_missing"
GMAIL_REMOTE_SEND_WINDOW_UNAVAILABLE_REASON = "gmail_remote_send_window_unavailable"
GMAIL_PROVIDER_DRAFT_ALREADY_SENT_REASON = "provider_draft_already_sent"
GMAIL_PROVIDER_DRAFT_NOT_READY_REASON = "provider_draft_not_ready"
GMAIL_EMERGENCY_STOP_REASON = "autopilot_emergency_stopped"
GMAIL_SEND_SAFETY_REASONS = {
    GMAIL_SEND_PACING_REASON,
    GMAIL_SEND_DAILY_LIMIT_REASON,
    GMAIL_INITIAL_CLAIM_DUPLICATE_REASON,
    GMAIL_SEND_ACCOUNT_MISSING_REASON,
    GMAIL_REMOTE_SEND_WINDOW_UNAVAILABLE_REASON,
    GMAIL_PROVIDER_DRAFT_ALREADY_SENT_REASON,
    GMAIL_PROVIDER_DRAFT_NOT_READY_REASON,
    GMAIL_EMERGENCY_STOP_REASON,
}


class GmailSendSafetyError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def minimum_gmail_send_interval_seconds(daily_limit: int) -> int:
    if daily_limit <= 0:
        return 0
    return (24 * 60 * 60 + daily_limit - 1) // daily_limit


def lock_and_validate_gmail_send(
    db: Session,
    provider_draft: EmailProviderDraft,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> None:
    """Serialize Gmail sends per account and recheck limits under the lock."""
    if provider_draft.provider != "gmail":
        return
    if provider_draft.email_account_id is None:
        raise GmailSendSafetyError(GMAIL_SEND_ACCOUNT_MISSING_REASON)

    account = db.scalar(
        select(EmailAccount)
        .where(EmailAccount.id == provider_draft.email_account_id)
        .with_for_update()
    )
    if account is None or account.disconnected_at is not None:
        raise GmailSendSafetyError(GMAIL_SEND_ACCOUNT_MISSING_REASON)

    db.refresh(provider_draft)
    if provider_draft.status == "sent":
        raise GmailSendSafetyError(GMAIL_PROVIDER_DRAFT_ALREADY_SENT_REASON)
    if provider_draft.status != "provider_draft_created":
        raise GmailSendSafetyError(GMAIL_PROVIDER_DRAFT_NOT_READY_REASON)

    latest_emergency_stop_status = db.scalar(
        select(AutopilotRun.status)
        .where(AutopilotRun.mode == "emergency_stop")
        .order_by(AutopilotRun.id.desc())
        .limit(1)
    )
    if latest_emergency_stop_status == "stopped":
        raise GmailSendSafetyError(GMAIL_EMERGENCY_STOP_REASON)

    current_time = now or utc_now()
    active_settings = settings or get_settings()
    daily_limit = active_settings.autopilot_per_gmail_account_daily_limit

    if daily_limit > 0:
        sent_last_24_hours = int(
            db.scalar(
                select(func.count(EmailProviderDraft.id)).where(
                    EmailProviderDraft.provider == "gmail",
                    EmailProviderDraft.email_account_id == account.id,
                    EmailProviderDraft.status == "sent",
                    EmailProviderDraft.sent_at >= current_time - timedelta(hours=24),
                )
            )
            or 0
        )
        if sent_last_24_hours >= daily_limit:
            raise GmailSendSafetyError(GMAIL_SEND_DAILY_LIMIT_REASON)

        minimum_interval = minimum_gmail_send_interval_seconds(daily_limit)
        recent_sent_draft_id = db.scalar(
            select(EmailProviderDraft.id)
            .where(
                EmailProviderDraft.provider == "gmail",
                EmailProviderDraft.email_account_id == account.id,
                EmailProviderDraft.status == "sent",
                EmailProviderDraft.id != provider_draft.id,
                EmailProviderDraft.sent_at > current_time - timedelta(seconds=minimum_interval),
            )
            .limit(1)
        )
        if recent_sent_draft_id is not None:
            raise GmailSendSafetyError(GMAIL_SEND_PACING_REASON)

    email_draft = provider_draft.email_draft
    if email_draft.draft_type != "initial_claim":
        return

    existing_initial_claim = db.scalar(
        select(EmailProviderDraft.id)
        .join(EmailDraft, EmailDraft.id == EmailProviderDraft.email_draft_id)
        .where(
            EmailProviderDraft.provider == "gmail",
            EmailProviderDraft.status == "sent",
            EmailProviderDraft.id != provider_draft.id,
            EmailDraft.order_id == email_draft.order_id,
            EmailDraft.draft_type == "initial_claim",
        )
        .limit(1)
    )
    if existing_initial_claim is not None:
        raise GmailSendSafetyError(GMAIL_INITIAL_CLAIM_DUPLICATE_REASON)
