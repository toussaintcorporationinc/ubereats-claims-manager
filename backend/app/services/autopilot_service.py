from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import (
    AppealAttempt,
    AppealWorkflow,
    AutopilotAction,
    AutopilotRun,
    ClaimOrder,
    ClaimResponseReview,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    FollowUpTask,
    GmailResponseAnalysis,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.services.appeal_workflow_service import (
    AppealWorkflowError,
    create_appeal_draft,
    create_refusal_analysis,
    latest_analysis,
    latest_attempt_with_draft,
    mark_appeal_sent,
)
from app.services.autopilot_identity_repair_service import (
    clean_customer_identity,
    clean_order_identifier,
    repair_appeal_workflow_for_autopilot,
    repair_order_identity_for_autopilot,
)
from app.services.audit import add_audit_log
from app.services.claim_validation_service import FINAL_CLAIM_STATUSES, get_claim_validation_gaps
from app.services.email_draft_service import EmailDraftBusinessError, create_email_draft
from app.services.email_draft_service import (
    build_order_identity_phrase,
    display_order_number,
    format_amount,
    format_display_date,
    format_restaurant_signature,
    restaurant_display_name,
)
from app.services.restaurant_identity_service import canonicalize_restaurant_names_in_text
from app.services.email_provider import (
    EmailConnectionStatus,
    EmailProvider,
    EmailProviderError,
    InboundEmailPayload,
)
from app.services.followup_policy_service import complete_task_for_sent_provider_draft
from app.services.gmail_quota import parse_gmail_retry_after
from app.services.gmail_payment_signal_service import (
    current_payload_response_order_number,
    current_response_order_number,
    message_has_explicit_payment_confirmation,
    payload_has_explicit_payment_confirmation,
)

AUTOPILOT_FINAL_ORDER_STATUSES = FINAL_CLAIM_STATUSES | {"accepted", "payment_to_verify", "payment_confirmed"}
POSITIVE_PAYMENT_REVIEW_TYPES = {"accepted", "payment_to_verify", "payment_confirmed"}
POSITIVE_PAYMENT_SIGNAL_CONFIDENCE = Decimal("0.70")
ELIGIBLE_APPEAL_STATUSES = {
    "active",
    "appeal_needed",
    "draft_needed",
    "gmail_draft_needed",
    "appeal_sent",
    "response_received",
    "escalated",
}
TERMINAL_APPEAL_STATUSES = {"accepted", "payment_confirmed", "manually_closed"}
FOLLOWUP_ACTION_BY_TASK = {
    "followup_1": "send_followup_1",
    "followup_2": "send_followup_2",
    "escalation": "send_escalation",
}


class AutopilotError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class AutopilotExecutionResult:
    run: AutopilotRun
    actions: list[AutopilotAction]


@dataclass(frozen=True)
class PreparedDraftResumeResult:
    status: str
    sent_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    provider_draft_id: int | None = None
    reason: str | None = None


def today_utc_start() -> datetime:
    now = utc_now()
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


def settings_snapshot() -> dict[str, object]:
    settings = get_settings()
    return {
        "enabled": settings.autopilot_enabled,
        "initial_claims_enabled": settings.autopilot_initial_claims_enabled,
        "followups_enabled": settings.autopilot_followups_enabled,
        "appeals_enabled": settings.autopilot_appeals_enabled,
        "daily_send_limit": settings.autopilot_daily_send_limit,
        "per_gmail_account_daily_limit": settings.autopilot_per_gmail_account_daily_limit,
        "per_restaurant_daily_limit": settings.autopilot_per_restaurant_daily_limit,
        "max_candidates_per_run": settings.autopilot_max_candidates_per_run,
        "min_amount": Decimal(str(settings.autopilot_min_amount)),
        "max_amount_without_owner_review": Decimal(str(settings.autopilot_max_amount_without_owner_review)),
        "require_complete_evidence": settings.autopilot_require_complete_evidence,
        "require_complete_restaurant_signature": settings.autopilot_require_complete_restaurant_signature,
        "require_gmail_connected": settings.autopilot_require_gmail_connected,
        "cooldown_hours": settings.autopilot_cooldown_hours,
        "refusal_retry_enabled": settings.autopilot_refusal_retry_enabled,
        "max_appeal_attempts": settings.autopilot_max_appeal_attempts,
        "never_close_on_refusal": settings.autopilot_never_close_on_refusal,
    }


def autopilot_is_emergency_stopped(db: Session) -> bool:
    latest = db.scalar(
        select(AutopilotRun)
        .where(AutopilotRun.mode == "emergency_stop")
        .order_by(AutopilotRun.id.desc())
        .limit(1)
    )
    return latest is not None and latest.status == "stopped"


def sent_today_count(db: Session, restaurant_id: int | None = None) -> int:
    statement = select(func.count(AutopilotAction.id)).where(
        AutopilotAction.status == "sent",
        AutopilotAction.sent_at >= today_utc_start(),
    )
    if restaurant_id is not None:
        statement = statement.where(AutopilotAction.restaurant_id == restaurant_id)
    return int(db.scalar(statement) or 0)


def gmail_account_sent_last_24_hours_count(db: Session, email_account_id: int | None) -> int:
    if email_account_id is None:
        return 0
    window_start = utc_now() - timedelta(hours=24)
    return int(
        db.scalar(
            select(func.count(EmailProviderDraft.id)).where(
                EmailProviderDraft.provider == "gmail",
                EmailProviderDraft.email_account_id == email_account_id,
                EmailProviderDraft.status == "sent",
                EmailProviderDraft.sent_at >= window_start,
            )
        )
        or 0
    )


def gmail_account_send_pacing_active(
    db: Session,
    email_account_id: int | None,
    daily_limit: int,
) -> bool:
    if email_account_id is None or daily_limit <= 0:
        return False
    minimum_interval_seconds = (24 * 60 * 60 + daily_limit - 1) // daily_limit
    window_start = utc_now() - timedelta(seconds=minimum_interval_seconds)
    return (
        db.scalar(
            select(EmailProviderDraft.id)
            .where(
                EmailProviderDraft.provider == "gmail",
                EmailProviderDraft.email_account_id == email_account_id,
                EmailProviderDraft.status == "sent",
                EmailProviderDraft.sent_at >= window_start,
            )
            .limit(1)
        )
        is not None
    )


def create_emergency_stop(db: Session, user: User) -> AutopilotRun:
    run = AutopilotRun(
        started_by_user_id=user.id,
        mode="emergency_stop",
        status="stopped",
        total_candidates=0,
        sent_count=0,
        skipped_count=0,
        failed_count=0,
        completed_at=utc_now(),
    )
    db.add(run)
    db.flush()
    add_audit_log(
        db,
        entity_type="autopilot_run",
        entity_id=run.id,
        action="autopilot.emergency_stop",
        user_id=user.id,
        new_value={"status": run.status},
    )
    return run


def run_autopilot(
    db: Session,
    user: User,
    *,
    mode: str,
    restaurant_id: int | None,
    dry_run: bool,
    provider: EmailProvider,
) -> AutopilotExecutionResult:
    if user.role == "staff":
        raise AutopilotError("Staff cannot run AutoPilot", 403)
    if mode not in {"initial_claims", "followups", "appeals", "all"}:
        raise AutopilotError("Invalid AutoPilot mode", 422)
    if restaurant_id is not None and not can_access_restaurant(db, user, restaurant_id):
        raise AutopilotError("Restaurant access denied", 403)

    settings = get_settings()
    if not dry_run:
        if not settings.autopilot_enabled:
            raise AutopilotError("autopilot_disabled", 409)
        if autopilot_is_emergency_stopped(db):
            raise AutopilotError("autopilot_emergency_stopped", 409)

    connection = provider.get_connection_status(db, user)
    if not dry_run and settings.autopilot_require_gmail_connected:
        ensure_provider_ready(connection)

    run = AutopilotRun(
        started_by_user_id=user.id,
        mode=mode,
        status="running",
        total_candidates=0,
        sent_count=0,
        skipped_count=0,
        failed_count=0,
    )
    db.add(run)
    db.flush()

    actions: list[AutopilotAction] = []
    global_sent = sent_today_count(db)
    per_restaurant_sent: dict[int, int] = {}
    errors: list[str] = []
    quota_pause_reason: str | None = None

    for candidate in iter_candidates(
        db,
        user,
        mode,
        restaurant_id,
        max_candidates=settings.autopilot_max_candidates_per_run,
    ):
        action = create_candidate_action(db, run, candidate)
        actions.append(action)

        skip_reason = candidate_skip_reason(db, candidate, connection)
        if skip_reason is None and not dry_run:
            skip_reason = limit_skip_reason(
                db,
                candidate.restaurant_id,
                current_global_sent=global_sent,
                current_restaurant_sent=per_restaurant_sent.get(candidate.restaurant_id, 0),
            )
        if skip_reason is None and not dry_run:
            skip_reason = remote_thread_safety_skip_reason(db, candidate, provider)

        if skip_reason is not None:
            mark_skipped(action, skip_reason, dry_run=dry_run)
            continue
        if dry_run:
            action.status = "candidate"
            action.reason = "dry_run_candidate"
            continue

        try:
            send_candidate(db, user, candidate, action, provider)
            if action.status == "sent":
                global_sent += 1
                per_restaurant_sent[candidate.restaurant_id] = per_restaurant_sent.get(candidate.restaurant_id, 0) + 1
        except Exception as exc:  # pragma: no cover - defensive path covered by integration behavior
            retry_after = parse_gmail_retry_after(
                str(exc),
                safety_seconds=settings.gmail_quota_retry_safety_seconds,
            )
            if retry_after is not None:
                quota_pause_reason = f"gmail_quota_retry_after:{retry_after.isoformat()}"
                mark_skipped(action, quota_pause_reason, dry_run=False)
                break
            action.status = "failed"
            action.skipped_reason = str(exc)
            action.updated_at = utc_now()
            errors.append(f"{candidate.case_type}:{candidate.case_id}:{exc}")

    run.total_candidates = len(actions)
    run.sent_count = sum(1 for action in actions if action.status == "sent")
    run.skipped_count = sum(1 for action in actions if action.status in {"skipped", "manual_review"})
    run.failed_count = sum(1 for action in actions if action.status == "failed")
    run.status = "failed" if errors and run.sent_count == 0 else "completed"
    run.completed_at = utc_now()
    run.error_message = quota_pause_reason or ("; ".join(errors)[:2000] if errors else None)
    add_audit_log(
        db,
        entity_type="autopilot_run",
        entity_id=run.id,
        action="autopilot.dry_run" if dry_run else "autopilot.run",
        user_id=user.id,
        new_value={
            "mode": mode,
            "restaurant_id": restaurant_id,
            "dry_run": dry_run,
            "total_candidates": run.total_candidates,
            "sent_count": run.sent_count,
            "skipped_count": run.skipped_count,
            "failed_count": run.failed_count,
        },
    )
    return AutopilotExecutionResult(run=run, actions=actions)


@dataclass(frozen=True)
class Candidate:
    case_type: str
    case_id: int
    restaurant_id: int
    action_type: str
    reason: str
    object: object


def resume_next_prepared_provider_draft(
    db: Session,
    user: User,
    account: EmailAccount,
    provider: EmailProvider,
) -> PreparedDraftResumeResult:
    """Resume one safe Gmail draft for an account after the pacing window opens."""

    settings = get_settings()
    if user.role == "staff" or account.user_id != user.id or account.disconnected_at is not None:
        return PreparedDraftResumeResult(status="skipped", skipped_count=1, reason="gmail_account_not_connected")
    if not settings.autopilot_enabled or autopilot_is_emergency_stopped(db):
        return PreparedDraftResumeResult(status="skipped", skipped_count=1, reason="autopilot_disabled")

    pending_drafts = list(
        db.scalars(
            select(EmailProviderDraft)
            .join(EmailDraft)
            .join(ClaimOrder)
            .where(
                EmailProviderDraft.provider == "gmail",
                EmailProviderDraft.email_account_id == account.id,
                EmailProviderDraft.status == "provider_draft_created",
            )
            .order_by(EmailProviderDraft.created_at, EmailProviderDraft.id)
            .limit(max(500, settings.autopilot_max_candidates_per_run))
        )
    )
    if not pending_drafts:
        return PreparedDraftResumeResult(status="empty")

    account_limit_reason = provider_draft_limit_skip_reason(db, pending_drafts[0])
    if account_limit_reason is not None:
        return PreparedDraftResumeResult(
            status="skipped",
            skipped_count=1,
            provider_draft_id=pending_drafts[0].id,
            reason=account_limit_reason,
        )

    connection = provider.get_connection_status(db, user)
    first_skip_reason: str | None = None
    for provider_draft in pending_drafts:
        candidate, resolution_reason = candidate_for_prepared_provider_draft(db, provider_draft)
        if candidate is None:
            first_skip_reason = first_skip_reason or resolution_reason
            continue
        if not can_access_restaurant(db, user, candidate.restaurant_id):
            first_skip_reason = first_skip_reason or "restaurant_access_denied"
            continue

        skip_reason = candidate_skip_reason(db, candidate, connection)
        if skip_reason is None:
            skip_reason = limit_skip_reason(
                db,
                candidate.restaurant_id,
                current_global_sent=sent_today_count(db),
                current_restaurant_sent=0,
            )
        if skip_reason is None:
            skip_reason = prepared_reply_thread_skip_reason(db, candidate, provider_draft)
        if skip_reason is None:
            skip_reason = remote_thread_safety_skip_reason(db, candidate, provider)
        if skip_reason is not None:
            first_skip_reason = first_skip_reason or skip_reason
            continue

        return send_prepared_provider_draft(
            db,
            user,
            candidate,
            provider_draft,
            provider,
        )

    return PreparedDraftResumeResult(
        status="skipped",
        skipped_count=1,
        reason=first_skip_reason or "no_safe_prepared_gmail_draft",
    )


def candidate_for_prepared_provider_draft(
    db: Session,
    provider_draft: EmailProviderDraft,
) -> tuple[Candidate | None, str | None]:
    attempt = db.scalar(
        select(AppealAttempt)
        .where(AppealAttempt.provider_draft_id == provider_draft.id)
        .order_by(AppealAttempt.id.desc())
        .limit(1)
    )
    if attempt is not None:
        workflow = attempt.workflow
        latest_attempt = latest_attempt_with_draft(db, workflow)
        if latest_attempt is None or latest_attempt.id != attempt.id:
            return None, "superseded_appeal_draft"
        return (
            Candidate(
                case_type="appeal_workflow",
                case_id=workflow.id,
                restaurant_id=workflow.restaurant_id,
                action_type="send_appeal",
                reason="prepared_gmail_draft_ready",
                object=workflow,
            ),
            None,
        )

    task = db.scalar(
        select(FollowUpTask)
        .where(FollowUpTask.generated_provider_draft_id == provider_draft.id)
        .limit(1)
    )
    if task is not None and task.task_type in FOLLOWUP_ACTION_BY_TASK:
        return (
            Candidate(
                case_type="followup_task",
                case_id=task.id,
                restaurant_id=task.order.restaurant_id,
                action_type=FOLLOWUP_ACTION_BY_TASK[task.task_type],
                reason="prepared_gmail_draft_ready",
                object=task,
            ),
            None,
        )

    draft = provider_draft.email_draft
    if draft.draft_type == "initial_claim":
        order = draft.order
        return (
            Candidate(
                case_type="claim_order",
                case_id=order.id,
                restaurant_id=order.restaurant_id,
                action_type="send_initial_claim",
                reason="prepared_gmail_draft_ready",
                object=order,
            ),
            None,
        )
    return None, "unsupported_prepared_gmail_draft"


def prepared_reply_thread_skip_reason(
    db: Session,
    candidate: Candidate,
    provider_draft: EmailProviderDraft,
) -> str | None:
    if candidate.action_type == "send_initial_claim":
        return None
    order = candidate_order(candidate)
    if order is None:
        return "missing_claim_order"
    starred_message = latest_starred_linked_inbound_message(db, order.id)
    if starred_message is None or not starred_message.provider_thread_id:
        return "starred_gmail_thread_required"
    if not provider_draft.provider_thread_id:
        return "gmail_reply_thread_required"
    if provider_draft.provider_thread_id != starred_message.provider_thread_id:
        return "gmail_reply_thread_changed"
    return None


def send_prepared_provider_draft(
    db: Session,
    user: User,
    candidate: Candidate,
    provider_draft: EmailProviderDraft,
    provider: EmailProvider,
) -> PreparedDraftResumeResult:
    run_mode = (
        "initial_claims"
        if candidate.action_type == "send_initial_claim"
        else "followups"
        if candidate.action_type.startswith("send_followup") or candidate.action_type == "send_escalation"
        else "appeals"
    )
    run = AutopilotRun(
        started_by_user_id=user.id,
        mode=run_mode,
        status="running",
        total_candidates=1,
        sent_count=0,
        skipped_count=0,
        failed_count=0,
    )
    db.add(run)
    db.flush()
    action = create_candidate_action(db, run, candidate)
    action.email_draft_id = provider_draft.email_draft_id
    action.provider_draft_id = provider_draft.id
    action.status = "provider_draft_created"
    db.flush()

    try:
        if candidate.action_type == "send_initial_claim":
            send_provider_draft(
                db,
                user,
                provider_draft,
                provider,
                order_status_after_send="sent",
                require_reply_thread=False,
            )
            action.reason = "initial_claim_sent"
        elif isinstance(candidate.object, FollowUpTask):
            send_provider_draft(
                db,
                user,
                provider_draft,
                provider,
                order_status_after_send=candidate.object.order.status,
            )
            complete_task_for_sent_provider_draft(db, user, provider_draft)
            action.reason = f"{candidate.object.task_type}_sent"
        elif isinstance(candidate.object, AppealWorkflow):
            send_provider_draft(
                db,
                user,
                provider_draft,
                provider,
                order_status_after_send=None,
            )
            mark_appeal_sent(db, workflow=candidate.object, user=user)
            action.reason = "appeal_sent"
        else:
            raise AutopilotError("unsupported_prepared_gmail_draft", 409)
        action.status = "sent"
        action.sent_at = provider_draft.sent_at
        run.sent_count = 1
        result = PreparedDraftResumeResult(
            status="sent",
            sent_count=1,
            provider_draft_id=provider_draft.id,
        )
    except AutopilotError as exc:
        mark_skipped(action, exc.message, dry_run=False)
        run.skipped_count = 1
        result = PreparedDraftResumeResult(
            status="skipped",
            skipped_count=1,
            provider_draft_id=provider_draft.id,
            reason=exc.message,
        )
    except Exception as exc:  # noqa: BLE001 - one queued Gmail draft must not stop the scheduler.
        action.status = "failed"
        action.skipped_reason = str(exc)[:2000]
        action.updated_at = utc_now()
        run.failed_count = 1
        run.error_message = str(exc)[:2000]
        result = PreparedDraftResumeResult(
            status="failed",
            failed_count=1,
            provider_draft_id=provider_draft.id,
            reason=str(exc)[:2000],
        )

    run.status = "failed" if run.failed_count else "completed"
    run.completed_at = utc_now()
    add_audit_log(
        db,
        entity_type="autopilot_run",
        entity_id=run.id,
        action="autopilot.prepared_gmail_draft_resumed",
        user_id=user.id,
        new_value={
            "email_account_id": provider_draft.email_account_id,
            "provider_draft_id": provider_draft.id,
            "restaurant_id": candidate.restaurant_id,
            "status": result.status,
            "reason": result.reason,
        },
    )
    db.flush()
    return result


def iter_candidates(
    db: Session,
    user: User,
    mode: str,
    restaurant_id: int | None,
    *,
    max_candidates: int | None = None,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    remaining = max_candidates if max_candidates and max_candidates > 0 else None
    if mode in {"initial_claims", "all"}:
        initial_candidates = initial_claim_candidates(db, user, restaurant_id, limit=remaining)
        candidates.extend(initial_candidates)
        if remaining is not None:
            remaining -= len(initial_candidates)
            if remaining <= 0:
                return candidates
    if mode in {"followups", "all"}:
        followup_items = followup_candidates(db, user, restaurant_id, limit=remaining)
        candidates.extend(followup_items)
        if remaining is not None:
            remaining -= len(followup_items)
            if remaining <= 0:
                return candidates
    if mode in {"appeals", "all"}:
        candidates.extend(appeal_candidates(db, user, restaurant_id, limit=remaining))
    return candidates


def accessible_restaurant_filter(db: Session, user: User, restaurant_id: int | None) -> list[int] | None:
    if restaurant_id is not None:
        return [restaurant_id]
    accessible_ids = get_accessible_restaurant_ids(db, user)
    if accessible_ids is None:
        return None
    return list(accessible_ids)


def initial_claim_candidates(
    db: Session,
    user: User,
    restaurant_id: int | None,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    statement = (
        select(ClaimOrder)
        .join(Restaurant)
        .where(
            ClaimOrder.status == "ready_to_send",
            Restaurant.active.is_(True),
            Restaurant.autopilot_enabled.is_(True),
        )
        .order_by(ClaimOrder.id)
    )
    restaurant_ids = accessible_restaurant_filter(db, user, restaurant_id)
    if restaurant_ids is not None:
        if not restaurant_ids:
            return []
        statement = statement.where(ClaimOrder.restaurant_id.in_(restaurant_ids))
    if limit is not None and limit > 0:
        statement = statement.limit(limit)
    orders = db.scalars(statement).all()
    for order in orders:
        repair_order_identity_for_autopilot(db, user, order)
    return [
        Candidate(
            case_type="claim_order",
            case_id=order.id,
            restaurant_id=order.restaurant_id,
            action_type="send_initial_claim",
            reason="ready_to_send_initial_claim",
            object=order,
        )
        for order in orders
    ]


def followup_candidates(
    db: Session,
    user: User,
    restaurant_id: int | None,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    now = utc_now()
    statement = (
        select(FollowUpTask)
        .join(ClaimOrder)
        .join(Restaurant)
        .where(
            FollowUpTask.task_type.in_(tuple(FOLLOWUP_ACTION_BY_TASK.keys())),
            FollowUpTask.status.in_(("pending", "draft_created", "provider_draft_created")),
            FollowUpTask.due_at <= now,
            Restaurant.active.is_(True),
            Restaurant.autopilot_enabled.is_(True),
        )
        .order_by(FollowUpTask.due_at, FollowUpTask.id)
    )
    restaurant_ids = accessible_restaurant_filter(db, user, restaurant_id)
    if restaurant_ids is not None:
        if not restaurant_ids:
            return []
        statement = statement.where(ClaimOrder.restaurant_id.in_(restaurant_ids))
    if limit is not None and limit > 0:
        statement = statement.limit(limit)
    tasks = db.scalars(statement).all()
    for task in tasks:
        repair_order_identity_for_autopilot(db, user, task.order)
    return [
        Candidate(
            case_type="followup_task",
            case_id=task.id,
            restaurant_id=task.order.restaurant_id,
            action_type=FOLLOWUP_ACTION_BY_TASK[task.task_type],
            reason="followup_due",
            object=task,
        )
        for task in tasks
    ]


def appeal_candidates(
    db: Session,
    user: User,
    restaurant_id: int | None,
    *,
    limit: int | None = None,
) -> list[Candidate]:
    now = utc_now()
    statement = (
        select(AppealWorkflow)
        .join(Restaurant)
        .where(
            AppealWorkflow.status.in_(ELIGIBLE_APPEAL_STATUSES),
            or_(AppealWorkflow.next_action_at.is_(None), AppealWorkflow.next_action_at <= now),
            Restaurant.active.is_(True),
            Restaurant.autopilot_enabled.is_(True),
        )
        .order_by(AppealWorkflow.next_action_at, AppealWorkflow.id)
    )
    restaurant_ids = accessible_restaurant_filter(db, user, restaurant_id)
    if restaurant_ids is not None:
        if not restaurant_ids:
            return []
        statement = statement.where(AppealWorkflow.restaurant_id.in_(restaurant_ids))
    if limit is not None and limit > 0:
        statement = statement.limit(limit)
    workflows = db.scalars(statement).all()
    for workflow in workflows:
        repair_appeal_workflow_for_autopilot(db, user, workflow)
    return [
        Candidate(
            case_type="appeal_workflow",
            case_id=workflow.id,
            restaurant_id=workflow.restaurant_id,
            action_type=appeal_action_type(workflow),
            reason="appeal_due",
            object=workflow,
        )
        for workflow in workflows
    ]


def appeal_action_type(workflow: AppealWorkflow) -> str:
    if workflow.next_action_type == "request_more_evidence":
        return "request_more_evidence"
    if workflow.next_action_type == "manual_review":
        return "manual_review"
    return "send_appeal"


def create_candidate_action(db: Session, run: AutopilotRun, candidate: Candidate) -> AutopilotAction:
    action = AutopilotAction(
        run_id=run.id,
        case_type=candidate.case_type,
        case_id=candidate.case_id,
        restaurant_id=candidate.restaurant_id,
        action_type=candidate.action_type,
        status="candidate",
        reason=candidate.reason,
    )
    db.add(action)
    db.flush()
    return action


def candidate_skip_reason(
    db: Session,
    candidate: Candidate,
    connection: EmailConnectionStatus,
) -> str | None:
    settings = get_settings()
    if settings.autopilot_require_gmail_connected:
        if not connection.enabled:
            return "email_provider_disabled"
        if not connection.connected:
            return "gmail_account_not_connected"
    if candidate.action_type in {"send_initial_claim", "send_followup_1", "send_followup_2", "send_escalation", "send_appeal"}:
        recipient_error = safe_autopilot_recipient_error()
        if recipient_error is not None:
            return recipient_error

    if candidate.action_type == "send_initial_claim":
        if not settings.autopilot_initial_claims_enabled:
            return "initial_claims_disabled"
        return initial_claim_skip_reason(db, candidate.object)  # type: ignore[arg-type]
    if candidate.action_type.startswith("send_followup"):
        if not settings.autopilot_followups_enabled:
            return "followups_disabled"
        return followup_skip_reason(db, candidate.object)  # type: ignore[arg-type]
    if candidate.action_type == "send_appeal":
        if not settings.autopilot_appeals_enabled:
            return "appeals_disabled"
        return appeal_skip_reason(db, candidate.object)  # type: ignore[arg-type]
    if candidate.action_type == "request_more_evidence":
        return "requires_more_evidence"
    if candidate.action_type == "manual_review":
        return "manual_review_required"
    return "unsupported_action"


def ensure_provider_ready(connection: EmailConnectionStatus) -> None:
    if not connection.enabled:
        raise AutopilotError("email_provider_disabled", 503)
    if not connection.connected:
        raise AutopilotError("gmail_account_not_connected", 409)


def initial_claim_skip_reason(db: Session, order: ClaimOrder) -> str | None:
    settings = get_settings()
    if order.status in AUTOPILOT_FINAL_ORDER_STATUSES:
        return "final_status"
    positive_signal_reason = positive_payment_signal_skip_reason(db, order.id)
    if positive_signal_reason is not None:
        return positive_signal_reason
    if order.status != "ready_to_send":
        return "not_ready_to_send"
    if order.restaurant is None or not order.restaurant.autopilot_enabled:
        return "restaurant_autopilot_disabled"
    signature_reason = restaurant_signature_skip_reason(order.restaurant)
    if signature_reason is not None:
        return signature_reason
    if order.order_amount is None:
        return "missing_amount"
    amount = Decimal(order.order_amount)
    if amount < Decimal(str(settings.autopilot_min_amount)):
        return "amount_below_autopilot_minimum"
    if amount > Decimal(str(settings.autopilot_max_amount_without_owner_review)):
        return "amount_requires_owner_review"
    if settings.autopilot_require_complete_evidence:
        missing_items, _ = get_claim_validation_gaps(db, order)
        if missing_items:
            return "missing_evidence"
    if has_sent_provider_draft(db, order.id) or has_outbound_thread(db, order.id):
        return "already_sent"
    if has_unreviewed_inbound(db, order.id):
        return "unreviewed_inbound_response"
    return None


def followup_skip_reason(db: Session, task: FollowUpTask) -> str | None:
    settings = get_settings()
    order = task.order
    if order.status in FINAL_CLAIM_STATUSES:
        return "final_status"
    identity_reason = order_identity_skip_reason(order)
    if identity_reason is not None:
        return identity_reason
    signature_reason = restaurant_signature_skip_reason(order.restaurant)
    if signature_reason is not None:
        return signature_reason
    positive_signal_reason = positive_payment_signal_skip_reason(db, order.id)
    if positive_signal_reason is not None:
        return positive_signal_reason
    if has_unreviewed_inbound(db, order.id):
        return "unreviewed_inbound_response"
    if order.retry_count >= settings.max_followups_per_order:
        return "max_followups_reached"
    if cooldown_active(order.last_followup_sent_at, settings.autopilot_cooldown_hours):
        return "cooldown_active"
    if task.generated_provider_draft is not None and task.generated_provider_draft.status == "sent":
        return "already_sent"
    if latest_starred_linked_inbound_message(db, order.id) is None:
        return "starred_gmail_thread_required"
    thread_identity_reason = local_thread_identity_skip_reason(db, order)
    if thread_identity_reason is not None:
        return thread_identity_reason
    return None


def appeal_skip_reason(db: Session, workflow: AppealWorkflow) -> str | None:
    settings = get_settings()
    if workflow.status in TERMINAL_APPEAL_STATUSES:
        return "terminal_appeal_status"
    if workflow.claim_order is not None and workflow.claim_order.status in {"accepted", "payment_confirmed"}:
        return "claim_order_resolved"
    if workflow.claim_order is not None:
        starred_message = latest_starred_linked_inbound_message(db, workflow.claim_order.id)
        if starred_message is not None:
            thread_identity_reason = local_thread_identity_skip_reason(db, workflow.claim_order)
            if thread_identity_reason is not None:
                return thread_identity_reason
            starred_reason = starred_thread_reply_skip_reason(db, workflow)
            if starred_reason is not None:
                return starred_reason
            return None
        identity_reason = order_identity_skip_reason(workflow.claim_order)
        if identity_reason is not None:
            return identity_reason
        signature_reason = restaurant_signature_skip_reason(workflow.claim_order.restaurant)
        if signature_reason is not None:
            return signature_reason
        positive_signal_reason = positive_payment_signal_skip_reason(db, workflow.claim_order.id)
        if positive_signal_reason is not None:
            return positive_signal_reason
    if workflow.appeal_attempt_count >= settings.autopilot_max_appeal_attempts:
        return "max_appeal_attempts_reached"
    if not settings.autopilot_refusal_retry_enabled:
        return "refusal_retry_disabled"
    if cooldown_active(workflow.last_appeal_sent_at, settings.autopilot_cooldown_hours):
        return "cooldown_active"
    analysis = latest_analysis(db, workflow)
    if analysis is not None and analysis.recommended_next_action in {"provide_missing_evidence", "manual_review"}:
        starred_override = (
            analysis.recommended_next_action == "manual_review"
            and workflow.claim_order is not None
            and order_identity_skip_reason(workflow.claim_order) is None
            and latest_starred_linked_inbound_message(db, workflow.claim_order.id) is not None
        )
        if not starred_override:
            return "manual_review_or_evidence_needed"
    latest_attempt = latest_attempt_with_draft(db, workflow)
    if (
        latest_attempt is not None
        and latest_attempt.status == "sent"
        and not settings.appeal_allow_same_template_resend
        and not latest_attempt.new_evidence_summary
    ):
        return "same_template_without_new_argument"
    if workflow.claim_order is not None and latest_starred_linked_inbound_message(db, workflow.claim_order.id) is None:
        return "starred_gmail_thread_required"
    return None


def starred_thread_reply_skip_reason(db: Session, workflow: AppealWorkflow) -> str | None:
    settings = get_settings()
    order = workflow.claim_order
    if order is None:
        return "missing_claim_order"
    if not clean_order_identifier(order.uber_order_number or order.internal_reference):
        return "missing_uber_order_number"
    if order.customer_name and not clean_customer_identity(order.customer_name):
        return "invalid_customer_name"
    signature_reason = restaurant_signature_skip_reason(order.restaurant)
    if signature_reason is not None:
        return signature_reason
    positive_signal_reason = positive_payment_signal_skip_reason(db, order.id)
    if positive_signal_reason is not None:
        return positive_signal_reason
    if workflow.appeal_attempt_count >= settings.autopilot_max_appeal_attempts:
        return "max_appeal_attempts_reached"
    if not settings.autopilot_refusal_retry_enabled:
        return "refusal_retry_disabled"
    starred_message = latest_starred_linked_inbound_message(db, order.id)
    if cooldown_active(workflow.last_appeal_sent_at, settings.autopilot_cooldown_hours) and not (
        starred_message is not None
        and message_is_newer_than(starred_message.received_at, workflow.last_appeal_sent_at)
    ):
        return "cooldown_active"
    return None


def message_is_newer_than(message_at: datetime | None, reference_at: datetime | None) -> bool:
    if message_at is None or reference_at is None:
        return False
    if message_at.tzinfo is None:
        message_at = message_at.replace(tzinfo=timezone.utc)
    if reference_at.tzinfo is None:
        reference_at = reference_at.replace(tzinfo=timezone.utc)
    return message_at > reference_at


def cooldown_active(value: datetime | None, cooldown_hours: int) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value + timedelta(hours=cooldown_hours) > utc_now()


def has_unreviewed_inbound(db: Session, order_id: int) -> bool:
    return (
        db.scalar(
            select(InboundEmailMessage.id)
            .where(
                InboundEmailMessage.order_id == order_id,
                InboundEmailMessage.review_status == "unreviewed",
            )
            .limit(1)
        )
        is not None
    )


def order_identity_skip_reason(order: ClaimOrder) -> str | None:
    if not clean_order_identifier(order.uber_order_number):
        return "missing_uber_order_number"
    if not clean_customer_identity(order.customer_name):
        return "missing_customer_name"
    if order.order_date is None:
        return "missing_order_date"
    if order.restaurant is None or not str(order.restaurant.name or "").strip():
        return "missing_restaurant_name"
    return None


def restaurant_signature_skip_reason(restaurant: Restaurant | None) -> str | None:
    settings = get_settings()
    if restaurant is None:
        return "missing_restaurant"
    public_fields = {
        "restaurant_name": restaurant.name,
        "restaurant_address": restaurant.address,
        "restaurant_phone_number": restaurant.phone_number,
        "restaurant_sender_email": restaurant.sender_email,
    }
    for value in public_fields.values():
        if value and "tennet" in str(value).casefold():
            return "restaurant_signature_contains_internal_brand"
    if not settings.autopilot_require_complete_restaurant_signature:
        return None
    for key, value in public_fields.items():
        if not str(value or "").strip():
            return f"missing_{key}"
    return None


def latest_starred_linked_inbound_message(db: Session, order_id: int) -> InboundEmailMessage | None:
    messages = db.scalars(
        select(InboundEmailMessage)
        .where(
            InboundEmailMessage.order_id == order_id,
            InboundEmailMessage.provider == "gmail",
            InboundEmailMessage.provider_thread_id.is_not(None),
        )
        .order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
        .limit(25)
    ).all()
    for message in messages:
        labels = {str(label).strip().casefold() for label in (message.provider_labels_json or [])}
        if "starred" in labels:
            return message
    return None


def positive_payment_signal_skip_reason(db: Session, order_id: int) -> str | None:
    if (
        db.scalar(
            select(ClaimResponseReview.id)
            .where(
                ClaimResponseReview.order_id == order_id,
                ClaimResponseReview.review_type.in_(POSITIVE_PAYMENT_REVIEW_TYPES),
            )
            .limit(1)
        )
        is not None
    ):
        return "positive_payment_review_exists"

    if (
        db.scalar(
            select(GmailResponseAnalysis.id)
            .where(
                GmailResponseAnalysis.order_id == order_id,
                GmailResponseAnalysis.status.in_(("analyzed", "applied")),
                GmailResponseAnalysis.recommended_review_type.in_(POSITIVE_PAYMENT_REVIEW_TYPES),
                or_(
                    GmailResponseAnalysis.confidence_score.is_(None),
                    GmailResponseAnalysis.confidence_score >= POSITIVE_PAYMENT_SIGNAL_CONFIDENCE,
                ),
            )
            .limit(1)
        )
        is not None
    ):
        return "positive_gmail_payment_signal_detected"

    order = db.get(ClaimOrder, order_id)
    if order is None:
        return None
    thread_keys = {
        (email_account_id, provider_thread_id)
        for email_account_id, provider_thread_id in db.execute(
            select(
                InboundEmailMessage.email_account_id,
                InboundEmailMessage.provider_thread_id,
            ).where(
                InboundEmailMessage.order_id == order_id,
                InboundEmailMessage.provider == "gmail",
                InboundEmailMessage.provider_thread_id.is_not(None),
            )
        ).all()
        if provider_thread_id
    }
    if not thread_keys:
        return None
    account_ids = {email_account_id for email_account_id, _thread_id in thread_keys}
    thread_ids = {thread_id for _email_account_id, thread_id in thread_keys}
    sender_filter = get_settings().gmail_support_sender_filter.strip().casefold()
    thread_messages = db.scalars(
        select(InboundEmailMessage)
        .where(
            InboundEmailMessage.email_account_id.in_(account_ids),
            InboundEmailMessage.provider == "gmail",
            InboundEmailMessage.provider_thread_id.in_(thread_ids),
        )
        .order_by(
            InboundEmailMessage.received_at.desc().nullslast(),
            InboundEmailMessage.id.desc(),
        )
        .limit(250)
    ).all()
    for message in thread_messages:
        if (message.email_account_id, message.provider_thread_id) not in thread_keys:
            continue
        if sender_filter and sender_filter not in str(message.from_email or "").casefold():
            continue
        response_order_number = current_response_order_number(message)
        if response_order_number and not order_identifiers_equivalent(
            response_order_number,
            order.uber_order_number,
            order.internal_reference,
        ):
            continue
        if message_has_explicit_payment_confirmation(message):
            return "positive_gmail_thread_history_detected"

    return None


def local_thread_identity_skip_reason(db: Session, order: ClaimOrder) -> str | None:
    starred_message = latest_starred_linked_inbound_message(db, order.id)
    if starred_message is None or not starred_message.provider_thread_id:
        return None
    account = db.get(EmailAccount, starred_message.email_account_id)
    if account is None:
        return "gmail_thread_identity_preflight_failed"
    thread_messages = db.scalars(
        select(InboundEmailMessage)
        .where(
            InboundEmailMessage.email_account_id == account.id,
            InboundEmailMessage.provider == "gmail",
            InboundEmailMessage.provider_thread_id == starred_message.provider_thread_id,
        )
        .order_by(
            InboundEmailMessage.received_at.asc().nulls_last(),
            InboundEmailMessage.id.asc(),
        )
        .limit(100)
    ).all()
    original_identifier = first_account_sent_order_identifier(
        thread_messages,
        account.email_address,
        current_response_order_number,
    )
    if original_identifier and not order_identifiers_equivalent(
        original_identifier,
        order.uber_order_number,
        order.internal_reference,
    ):
        return "gmail_thread_order_identity_mismatch"
    return None


def remote_thread_safety_skip_reason(
    db: Session,
    candidate: Candidate,
    provider: EmailProvider,
) -> str | None:
    order = candidate_order(candidate)
    if order is None or candidate.action_type == "send_initial_claim":
        return None
    starred_message = latest_starred_linked_inbound_message(db, order.id)
    if starred_message is None or not starred_message.provider_thread_id:
        return None
    account = db.get(EmailAccount, starred_message.email_account_id)
    if account is None:
        return "gmail_thread_history_preflight_failed"
    get_thread_messages = getattr(provider, "get_thread_messages_for_account", None)
    if not callable(get_thread_messages):
        return None
    try:
        try:
            payloads = list(
                get_thread_messages(
                    db,
                    account,
                    starred_message.provider_thread_id,
                    include_attachments=False,
                )
            )
        except TypeError:
            payloads = list(get_thread_messages(db, account, starred_message.provider_thread_id))
    except Exception as exc:  # noqa: BLE001 - an unreadable thread must never be sent to blindly.
        if gmail_thread_history_not_found(exc):
            return None
        return "gmail_thread_history_preflight_failed"

    sender_filter = get_settings().gmail_support_sender_filter.strip().casefold()
    account_address = str(account.email_address or "").strip().casefold()
    original_identifier = first_account_sent_order_identifier(
        payloads,
        account.email_address,
        current_payload_response_order_number,
    )
    if original_identifier and not order_identifiers_equivalent(
        original_identifier,
        order.uber_order_number,
        order.internal_reference,
    ):
        return "gmail_thread_order_identity_mismatch"
    for payload in payloads:
        if payload.provider_thread_id != starred_message.provider_thread_id:
            continue
        from_email = str(payload.from_email or "").strip().casefold()
        if not from_email or from_email == account_address:
            continue
        if sender_filter and sender_filter not in from_email:
            continue
        if not payload_has_explicit_payment_confirmation(payload):
            continue
        response_order_number = current_payload_response_order_number(payload)
        if response_order_number and not order_identifiers_equivalent(
            response_order_number,
            order.uber_order_number,
            order.internal_reference,
        ):
            continue
        return "positive_gmail_thread_history_detected"
    return None


def first_account_sent_order_identifier(
    messages: list[InboundEmailMessage] | list[InboundEmailPayload],
    account_email: str | None,
    extractor: Callable[[Any], str | None],
) -> str | None:
    normalized_account = str(account_email or "").strip().casefold()
    if not normalized_account:
        return None
    for message in messages:
        if str(message.from_email or "").strip().casefold() != normalized_account:
            continue
        identifier = extractor(message)
        if identifier:
            return identifier
    return None


def gmail_thread_history_not_found(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 404:
        return True
    text = str(getattr(exc, "message", exc)).strip().casefold()
    return "not_found" in text or "not found" in text or "status 404" in text


def candidate_order(candidate: Candidate) -> ClaimOrder | None:
    if isinstance(candidate.object, ClaimOrder):
        return candidate.object
    if isinstance(candidate.object, FollowUpTask):
        return candidate.object.order
    if isinstance(candidate.object, AppealWorkflow):
        return candidate.object.claim_order
    return None


def order_identifiers_equivalent(response_identifier: str, *order_identifiers: str | None) -> bool:
    response = "".join(character for character in response_identifier.upper() if character.isalnum())
    if not response:
        return False
    response_confusion_key = response.replace("O", "0")
    for value in order_identifiers:
        candidate = "".join(character for character in str(value or "").upper() if character.isalnum())
        if candidate and (
            candidate == response or candidate.replace("O", "0") == response_confusion_key
        ):
            return True
    return False


def has_sent_provider_draft(db: Session, order_id: int) -> bool:
    return (
        db.scalar(
            select(EmailProviderDraft.id)
            .join(EmailDraft)
            .where(
                EmailDraft.order_id == order_id,
                EmailProviderDraft.status == "sent",
            )
            .limit(1)
        )
        is not None
    )


def has_outbound_thread(db: Session, order_id: int) -> bool:
    return (
        db.scalar(
            select(EmailThread.id)
            .where(
                EmailThread.order_id == order_id,
                EmailThread.direction == "outbound",
            )
            .limit(1)
        )
        is not None
    )


def limit_skip_reason(
    db: Session,
    restaurant_id: int,
    *,
    current_global_sent: int,
    current_restaurant_sent: int,
) -> str | None:
    settings = get_settings()
    if current_global_sent >= settings.autopilot_daily_send_limit:
        return "daily_send_limit_reached"
    existing_restaurant_sent = sent_today_count(db, restaurant_id)
    if existing_restaurant_sent + current_restaurant_sent >= settings.autopilot_per_restaurant_daily_limit:
        return "per_restaurant_daily_limit_reached"
    return None


def provider_draft_limit_skip_reason(db: Session, provider_draft: EmailProviderDraft) -> str | None:
    settings = get_settings()
    limit = settings.autopilot_per_gmail_account_daily_limit
    if limit <= 0 or provider_draft.provider != "gmail" or provider_draft.email_account_id is None:
        return None
    if gmail_account_sent_last_24_hours_count(db, provider_draft.email_account_id) >= limit:
        return "gmail_account_daily_limit_reached"
    if gmail_account_send_pacing_active(db, provider_draft.email_account_id, limit):
        return "gmail_account_send_pacing_active"
    return None


def mark_skipped(action: AutopilotAction, reason: str, *, dry_run: bool) -> None:
    action.status = "candidate" if dry_run else "skipped"
    action.reason = "dry_run_skipped" if dry_run else "skipped"
    action.skipped_reason = reason
    action.updated_at = utc_now()


def safe_autopilot_recipient_error() -> str | None:
    settings = get_settings()
    recipient = (settings.default_uber_eats_support_email or "").strip()
    if not recipient or "@" not in recipient:
        return "invalid_autopilot_recipient"
    sender_filter = (settings.gmail_support_sender_filter or "").strip().casefold()
    if sender_filter and sender_filter not in recipient.casefold():
        return "recipient_not_matching_support_filter"
    return None


def safe_autopilot_recipient() -> str:
    error = safe_autopilot_recipient_error()
    if error is not None:
        raise AutopilotError(error, 409)
    return get_settings().default_uber_eats_support_email.strip()


def send_candidate(
    db: Session,
    user: User,
    candidate: Candidate,
    action: AutopilotAction,
    provider: EmailProvider,
) -> None:
    if candidate.action_type == "send_initial_claim":
        send_initial_claim(db, user, candidate.object, action, provider)  # type: ignore[arg-type]
    elif candidate.action_type.startswith("send_followup"):
        send_followup(db, user, candidate.object, action, provider)  # type: ignore[arg-type]
    elif candidate.action_type == "send_appeal":
        send_appeal(db, user, candidate.object, action, provider)  # type: ignore[arg-type]
    else:
        raise AutopilotError("unsupported_action", 400)


def send_initial_claim(
    db: Session,
    user: User,
    order: ClaimOrder,
    action: AutopilotAction,
    provider: EmailProvider,
) -> None:
    previous_order_status = order.status
    draft = latest_draft(db, order.id, "initial_claim")
    if draft is None:
        draft = create_email_draft(db, order.id, "initial_claim", user_id=user.id)
        action.status = "draft_created"
        action.email_draft_id = draft.id
        db.flush()
    provider_draft = provider.create_draft(
        db,
        user,
        draft,
        to_email=safe_autopilot_recipient(),
        include_evidence=True,
    )
    action.status = "provider_draft_created"
    action.provider_draft_id = provider_draft.id
    db.flush()
    skip_reason = provider_draft_limit_skip_reason(db, provider_draft)
    if skip_reason is not None:
        order.status = previous_order_status
        order.updated_at = utc_now()
        mark_skipped(action, skip_reason, dry_run=False)
        return
    send_provider_draft(db, user, provider_draft, provider, order_status_after_send="sent", require_reply_thread=False)
    action.status = "sent"
    action.sent_at = provider_draft.sent_at
    action.reason = "initial_claim_sent"
    action.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="autopilot_action",
        entity_id=action.id,
        action="autopilot.initial_claim.sent",
        user_id=user.id,
        new_value={"order_id": order.id, "provider_draft_id": provider_draft.id},
    )


def send_followup(
    db: Session,
    user: User,
    task: FollowUpTask,
    action: AutopilotAction,
    provider: EmailProvider,
) -> None:
    draft = task.generated_email_draft
    if draft is None:
        try:
            draft = create_email_draft(db, task.order_id, task.task_type, user_id=user.id)
        except EmailDraftBusinessError as exc:
            raise AutopilotError(exc.message, 409) from exc
        task.generated_email_draft_id = draft.id
        task.status = "draft_created"
        action.status = "draft_created"
        action.email_draft_id = draft.id
        db.flush()
    provider_draft = task.generated_provider_draft
    if provider_draft is None:
        provider_draft = provider.create_draft(
            db,
            user,
            draft,
            to_email=safe_autopilot_recipient(),
            include_evidence=True,
        )
        task.generated_provider_draft_id = provider_draft.id
        task.status = "provider_draft_created"
        action.status = "provider_draft_created"
        action.provider_draft_id = provider_draft.id
        db.flush()
    skip_reason = provider_draft_limit_skip_reason(db, provider_draft)
    if skip_reason is not None:
        mark_skipped(action, skip_reason, dry_run=False)
        return
    send_provider_draft(db, user, provider_draft, provider, order_status_after_send=task.order.status)
    complete_task_for_sent_provider_draft(db, user, provider_draft)
    action.status = "sent"
    action.sent_at = provider_draft.sent_at
    action.reason = f"{task.task_type}_sent"
    action.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="autopilot_action",
        entity_id=action.id,
        action="autopilot.followup.sent",
        user_id=user.id,
        new_value={"task_id": task.id, "provider_draft_id": provider_draft.id},
    )


def send_appeal(
    db: Session,
    user: User,
    workflow: AppealWorkflow,
    action: AutopilotAction,
    provider: EmailProvider,
) -> None:
    starred_message = None
    if workflow.claim_order_id is not None:
        starred_message = latest_starred_linked_inbound_message(db, workflow.claim_order_id)
    attempt = latest_attempt_with_draft(db, workflow)
    if starred_message is not None and attempt_is_already_sent(attempt):
        attempt = create_starred_thread_reply_attempt(db, workflow=workflow, starred_message=starred_message, user=user)
        action.status = "draft_created"
        action.email_draft_id = attempt.email_draft_id
        db.flush()
    elif starred_message is not None and (attempt is None or attempt.email_draft is None):
        attempt = create_starred_thread_reply_attempt(db, workflow=workflow, starred_message=starred_message, user=user)
        action.status = "draft_created"
        action.email_draft_id = attempt.email_draft_id
        db.flush()
    elif attempt is None or attempt.email_draft is None:
        if latest_analysis(db, workflow) is None:
            create_refusal_analysis(db, workflow=workflow, user=user)
        try:
            attempt = create_appeal_draft(db, workflow=workflow, user=user)
        except AppealWorkflowError as exc:
            raise AutopilotError(exc.message, exc.status_code) from exc
        action.status = "draft_created"
        action.email_draft_id = attempt.email_draft_id
        db.flush()
    provider_draft = attempt.provider_draft
    if provider_draft is None:
        provider_draft = provider.create_draft(
            db,
            user,
            attempt.email_draft,
            to_email=safe_autopilot_recipient(),
            include_evidence=True,
        )
        attempt.provider_draft_id = provider_draft.id
        attempt.status = "gmail_draft_created"
        workflow.status = "appeal_needed"
        workflow.next_action_type = "send_manual_appeal"
        workflow.updated_at = utc_now()
        action.status = "provider_draft_created"
        action.provider_draft_id = provider_draft.id
        db.flush()
    skip_reason = provider_draft_limit_skip_reason(db, provider_draft)
    if skip_reason is not None:
        mark_skipped(action, skip_reason, dry_run=False)
        return
    send_provider_draft(db, user, provider_draft, provider, order_status_after_send=None)
    try:
        mark_appeal_sent(db, workflow=workflow, user=user)
    except AppealWorkflowError as exc:
        raise AutopilotError(exc.message, exc.status_code) from exc
    action.status = "sent"
    action.sent_at = provider_draft.sent_at
    action.reason = "appeal_sent"
    action.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="autopilot_action",
        entity_id=action.id,
        action="autopilot.appeal.sent",
        user_id=user.id,
        new_value={"workflow_id": workflow.id, "provider_draft_id": provider_draft.id},
    )


def attempt_is_already_sent(attempt: AppealAttempt | None) -> bool:
    if attempt is None:
        return False
    if attempt.status == "sent":
        return True
    return attempt.provider_draft is not None and attempt.provider_draft.status == "sent"


def create_starred_thread_reply_attempt(
    db: Session,
    *,
    workflow: AppealWorkflow,
    starred_message: InboundEmailMessage,
    user: User,
    reply_kind: str = "refusal",
) -> AppealAttempt:
    order = workflow.claim_order
    if order is None:
        raise AutopilotError("missing_claim_order", 409)
    if reply_kind not in {"refusal", "followup"}:
        raise AutopilotError("unsupported_starred_reply_kind", 409)
    draft = EmailDraft(
        order_id=order.id,
        draft_type="followup_1" if reply_kind == "followup" else "appeal_generic_refusal",
        subject=canonicalize_restaurant_names_in_text(
            starred_message.subject or f"Re: Contestation commande Uber Eats {display_order_number(order)}"
        ),
        body=build_starred_thread_reply_body(order, workflow, starred_message, reply_kind=reply_kind),
        status="created",
    )
    db.add(draft)
    db.flush()
    attempt = AppealAttempt(
        workflow_id=workflow.id,
        attempt_number=next_attempt_number_for_workflow(db, workflow),
        appeal_type=starred_thread_appeal_type(workflow),
        status="draft_created",
        based_on_refusal_message_id=starred_message.id,
        email_draft_id=draft.id,
        argument_summary=f"starred_gmail_thread_{reply_kind}_reply",
        new_evidence_summary=None,
        created_by_user_id=user.id,
    )
    db.add(attempt)
    workflow.status = "gmail_draft_needed"
    workflow.next_action_type = "create_gmail_draft"
    workflow.next_action_at = utc_now()
    workflow.updated_at = utc_now()
    db.flush()
    add_audit_log(
        db,
        entity_type="appeal_attempt",
        entity_id=attempt.id,
        action="appeal_attempt.starred_gmail_reply_draft_created",
        user_id=user.id,
        new_value={
            "workflow_id": workflow.id,
            "email_draft_id": draft.id,
            "inbound_message_id": starred_message.id,
        },
    )
    return attempt


def next_attempt_number_for_workflow(db: Session, workflow: AppealWorkflow) -> int:
    current = db.scalar(select(func.max(AppealAttempt.attempt_number)).where(AppealAttempt.workflow_id == workflow.id))
    return int(current or 0) + 1


def starred_thread_appeal_type(workflow: AppealWorkflow) -> str:
    if workflow.appeal_attempt_count >= 2:
        return "escalation"
    if workflow.appeal_attempt_count == 1:
        return "second_appeal"
    return "first_appeal"


def build_starred_thread_reply_body(
    order: ClaimOrder,
    workflow: AppealWorkflow,
    starred_message: InboundEmailMessage,
    *,
    reply_kind: str = "refusal",
) -> str:
    restaurant = order.restaurant
    subject_text = " ".join(value for value in [starred_message.subject, starred_message.snippet, starred_message.body_text] if value)
    is_cancellation = "annulation" in subject_text.casefold() or "cancel" in subject_text.casefold()
    identity_phrase = build_order_identity_phrase(order)
    date_line = format_display_date(order.order_date)
    if date_line and f"du {date_line}" not in identity_phrase:
        identity_phrase = f"{identity_phrase}, du {date_line}"
    if reply_kind == "followup":
        opening = (
            f"Je vous relance concernant {identity_phrase} "
            f"pour le restaurant {restaurant_display_name(restaurant) if restaurant else 'le restaurant'}, "
            "toujours sans decision de paiement claire."
        )
    else:
        opening = (
            f"Je vous demande de reexaminer le refus concernant {identity_phrase} "
            f"pour le restaurant {restaurant_display_name(restaurant) if restaurant else 'le restaurant'}."
        )
    if is_cancellation:
        argument = (
            "La commande avait ete acceptee et preparee avant l'annulation. "
            "Le restaurant a supporte une perte et du gaspillage; merci de reexaminer le dossier."
        )
    else:
        argument = (
            "La commande a ete preparee complete et les articles demandes ont ete places dans le sac avant l'envoi. "
            "Nous verifions les commandes avant remise au livreur."
        )
    if workflow.appeal_attempt_count >= 2:
        argument += (
            "\n\nLe dossier a deja ete relance sans regularisation claire. "
            "Merci de transmettre la demande a un niveau de traitement superieur si necessaire."
        )
    paragraphs = [
        "Bonjour,",
        opening,
    ]
    if order.order_amount is not None:
        paragraphs.append(f"Montant concerne : {format_amount(order.order_amount)} {order.currency or 'EUR'}")
    paragraphs.extend(
        [
            argument,
            "Merci de revoir ce dossier et de nous confirmer la suite donnee a la demande.",
            f"Cordialement,\n{format_restaurant_signature(restaurant) if restaurant else 'Restaurant'}",
        ]
    )
    return "\n\n".join(paragraphs)


def latest_draft(db: Session, order_id: int, draft_type: str) -> EmailDraft | None:
    return db.scalar(
        select(EmailDraft)
        .where(EmailDraft.order_id == order_id, EmailDraft.draft_type == draft_type)
        .order_by(EmailDraft.id.desc())
        .limit(1)
    )


def send_provider_draft(
    db: Session,
    user: User,
    provider_draft: EmailProviderDraft,
    provider: EmailProvider,
    *,
    order_status_after_send: str | None,
    require_reply_thread: bool = True,
) -> None:
    if provider_draft.status == "sent":
        raise AutopilotError("provider_draft_already_sent", 409)
    if provider_draft.status != "provider_draft_created":
        raise AutopilotError("provider_draft_not_ready", 409)
    if require_reply_thread and not provider_draft.provider_thread_id:
        raise AutopilotError("gmail_reply_thread_required", 409)
    skip_reason = provider_draft_limit_skip_reason(db, provider_draft)
    if skip_reason is not None:
        raise AutopilotError(skip_reason, 409)
    old_status = provider_draft.status
    provider_draft.status = "send_requested"
    provider_draft.updated_at = utc_now()
    db.flush()
    try:
        send_result = provider.send_draft(db, user, provider_draft)
    except EmailProviderError as exc:
        provider_draft.status = "failed"
        provider_draft.last_error = exc.message
        provider_draft.updated_at = utc_now()
        add_audit_log(
            db,
            entity_type="email_provider_draft",
            entity_id=provider_draft.id,
            action="autopilot.send_gmail_draft_failed",
            user_id=user.id,
            old_value={"status": old_status},
            new_value={"status": "failed", "error": exc.message},
        )
        raise AutopilotError(exc.message, exc.status_code) from exc

    provider_draft.status = "sent"
    provider_draft.sent_at = send_result.sent_at
    provider_draft.sent_by_user_id = user.id
    provider_draft.provider_message_id = send_result.provider_message_id
    provider_draft.provider_thread_id = send_result.provider_thread_id or provider_draft.provider_thread_id
    provider_draft.last_error = None
    provider_draft.updated_at = utc_now()

    email_draft = provider_draft.email_draft
    order = email_draft.order
    if order_status_after_send is not None:
        order.status = order_status_after_send
        if order.first_email_sent_at is None:
            order.first_email_sent_at = provider_draft.sent_at
        order.updated_at = utc_now()
    db.add(
        EmailThread(
            order_id=order.id,
            provider="gmail",
            thread_id=provider_draft.provider_thread_id,
            message_id=provider_draft.provider_message_id,
            direction="outbound",
            subject=provider_draft.subject,
            body=email_draft.body,
            sent_at=provider_draft.sent_at,
        )
    )
    add_audit_log(
        db,
        entity_type="email_provider_draft",
        entity_id=provider_draft.id,
        action="autopilot.send_gmail_draft",
        user_id=user.id,
        old_value={"status": old_status},
        new_value={
            "status": provider_draft.status,
            "provider_message_id": provider_draft.provider_message_id,
            "provider_thread_id": provider_draft.provider_thread_id,
            "order_id": order.id,
        },
    )
