from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

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
)
from app.services.email_provider import EmailConnectionStatus, EmailProvider, EmailProviderError
from app.services.followup_policy_service import complete_task_for_sent_provider_draft
from app.services.gmail_quota import parse_gmail_retry_after

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

        if skip_reason is not None:
            mark_skipped(action, skip_reason, dry_run=dry_run)
            continue
        if dry_run:
            action.status = "candidate"
            action.reason = "dry_run_candidate"
            continue

        try:
            send_candidate(db, user, candidate, action, provider)
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
    if not str(order.uber_order_number or "").strip() and not str(order.internal_reference or "").strip():
        return "missing_uber_order_number"
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
    if not str(order.uber_order_number or "").strip():
        return "missing_uber_order_number"
    if not str(order.customer_name or "").strip():
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

    return None


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
) -> AppealAttempt:
    order = workflow.claim_order
    if order is None:
        raise AutopilotError("missing_claim_order", 409)
    draft = EmailDraft(
        order_id=order.id,
        draft_type="appeal_generic_refusal",
        subject=starred_message.subject or f"Re: Contestation commande Uber Eats {display_order_number(order)}",
        body=build_starred_thread_reply_body(order, workflow, starred_message),
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
        argument_summary="starred_gmail_thread_reply",
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
) -> str:
    restaurant = order.restaurant
    subject_text = " ".join(value for value in [starred_message.subject, starred_message.snippet, starred_message.body_text] if value)
    is_cancellation = "annulation" in subject_text.casefold() or "cancel" in subject_text.casefold()
    identity_phrase = build_order_identity_phrase(order)
    date_line = format_display_date(order.order_date)
    if date_line and f"du {date_line}" not in identity_phrase:
        identity_phrase = f"{identity_phrase}, du {date_line}"
    opening = (
        f"Je vous demande de reexaminer le refus concernant {identity_phrase} "
        f"pour le restaurant {restaurant.name if restaurant else 'le restaurant'}."
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
