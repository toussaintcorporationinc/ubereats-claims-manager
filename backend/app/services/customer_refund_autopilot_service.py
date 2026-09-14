from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailProviderDraft, Restaurant, UberCustomerRefundDispute, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.autopilot_service import (
    AutopilotError,
    gmail_provider_error_is_retryable,
    provider_draft_limit_skip_reason,
    safe_autopilot_recipient,
    send_provider_draft,
)
from app.services.customer_refund_dispute_service import (
    create_customer_refund_draft,
    create_customer_refund_gmail_draft,
    recalculate_dispute_evidence,
)
from app.services.email_provider import EmailProvider


@dataclass(frozen=True)
class CustomerRefundAutopilotResult:
    candidates: int = 0
    sent_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    repaired_count: int = 0
    errors: tuple[str, ...] = ()


def run_customer_refund_autopilot(
    db: Session,
    user: User,
    provider: EmailProvider,
    *,
    max_candidates: int = 4,
) -> CustomerRefundAutopilotResult:
    """Send ready customer-refund disputes through the same Gmail safety layer.

    Only disputes with complete/not-required evidence are eligible. Unknown
    disputes and anything requiring human evidence remain blocked.
    """

    disputes = list(
        db.scalars(
            select(UberCustomerRefundDispute)
            .join(Restaurant)
            .where(
                UberCustomerRefundDispute.dispute_type != "unknown",
                UberCustomerRefundDispute.status.in_((
                    "evidence_ready",
                    "draft_created",
                    "gmail_draft_created",
                    "sent",
                )),
                Restaurant.active.is_(True),
                Restaurant.autopilot_enabled.is_(True),
            )
            .order_by(
                UberCustomerRefundDispute.deducted_at.asc().nulls_last(),
                UberCustomerRefundDispute.id,
            )
            .limit(max(1, max_candidates))
        )
    )

    sent_count = 0
    skipped_count = 0
    failed_count = 0
    repaired_count = 0
    errors: list[str] = []

    for dispute in disputes:
        try:
            if dispute.status == "sent":
                continue
            if dispute.claim_order_id is None:
                skipped_count += 1
                continue

            recalculate_dispute_evidence(db, user, dispute, create_tasks=True)
            if dispute.evidence_status not in {"complete", "not_required"}:
                skipped_count += 1
                db.commit()
                continue

            if dispute.dispute_email_draft_id is None:
                create_customer_refund_draft(db, user, dispute)
                db.refresh(dispute)

            provider_draft: EmailProviderDraft | None = dispute.provider_draft
            if provider_draft is not None and provider_draft.status == "sent":
                dispute.status = "sent"
                dispute.updated_at = utc_now()
                db.commit()
                repaired_count += 1
                continue

            if provider_draft is not None and provider_draft.status == "failed":
                error_text = provider_draft.last_error or provider_draft.error_message
                if provider_draft.provider_draft_id and gmail_provider_error_is_retryable(error_text):
                    provider_draft.status = "provider_draft_created"
                    provider_draft.updated_at = utc_now()
                    repaired_count += 1
                    db.flush()
                else:
                    dispute.provider_draft_id = None
                    provider_draft = None
                    repaired_count += 1
                    db.flush()

            if provider_draft is None:
                provider_draft = create_customer_refund_gmail_draft(db, user, dispute, provider)
                db.refresh(dispute)

            if provider_draft.status != "provider_draft_created":
                skipped_count += 1
                continue

            skip_reason = provider_draft_limit_skip_reason(db, provider_draft)
            if skip_reason is not None:
                skipped_count += 1
                continue

            # Validate the configured support destination even though the Gmail
            # draft already exists, so a future bad config cannot silently send
            # recovery mail to an unintended recipient.
            safe_autopilot_recipient()
            send_provider_draft(
                db,
                user,
                provider_draft,
                provider,
                order_status_after_send="sent",
                require_reply_thread=False,
            )
            dispute.status = "sent"
            dispute.updated_at = utc_now()
            add_audit_log(
                db,
                entity_type="uber_customer_refund_dispute",
                entity_id=dispute.id,
                action="customer_refund_dispute.autopilot_sent",
                user_id=user.id,
                new_value={
                    "provider_draft_id": provider_draft.id,
                    "provider_message_id": provider_draft.provider_message_id,
                    "claim_order_id": dispute.claim_order_id,
                    "amount": str(dispute.customer_refund_amount),
                },
            )
            db.commit()
            sent_count += 1
        except (AutopilotError, HTTPException) as exc:
            db.rollback()
            skipped_count += 1
            message = getattr(exc, "message", None) or getattr(exc, "detail", None) or str(exc)
            errors.append(f"dispute:{dispute.id}:{message}")
        except Exception as exc:  # noqa: BLE001 - one dispute must not stop the recovery worker.
            db.rollback()
            failed_count += 1
            errors.append(f"dispute:{dispute.id}:{exc}")

    return CustomerRefundAutopilotResult(
        candidates=len(disputes),
        sent_count=sent_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        repaired_count=repaired_count,
        errors=tuple(errors[:50]),
    )
