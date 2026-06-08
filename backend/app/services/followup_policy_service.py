from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ClaimOrder, EmailDraft, EmailProviderDraft, EmailThread, FollowUpTask, InboundEmailMessage, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log

FINAL_ORDER_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}
FOLLOWUP_ELIGIBLE_STATUSES = {
    "sent",
    "waiting_uber_response",
    "response_received",
    "followup_1_sent",
    "followup_2_sent",
    "escalation_sent",
}
FOLLOWUP_DRAFT_TYPES = {"followup_1", "followup_2", "escalation"}
FOLLOWUP_SENT_STATUS_BY_TYPE = {
    "followup_1": "followup_1_sent",
    "followup_2": "followup_2_sent",
    "escalation": "escalation_sent",
}


@dataclass(frozen=True)
class FollowUpDecision:
    task_type: str
    due_at: datetime
    reason: str


@dataclass(frozen=True)
class FollowUpRecalculateResult:
    created_tasks: int
    skipped_orders: int
    manual_review_orders: int
    errors: list[str]


class FollowUpPolicyService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def recalculate(
        self,
        db: Session,
        user: User,
        orders_query: Select[tuple[ClaimOrder]],
        *,
        dry_run: bool = False,
    ) -> FollowUpRecalculateResult:
        created_tasks = 0
        skipped_orders = 0
        manual_review_orders = 0
        errors: list[str] = []

        for order in db.scalars(orders_query).all():
            try:
                decision = self.decide_next_task(db, order)
                if decision is None:
                    skipped_orders += 1
                    continue
                if decision.task_type == "manual_review":
                    manual_review_orders += 1
                if dry_run:
                    created_tasks += 1
                    continue
                task = FollowUpTask(
                    order_id=order.id,
                    task_type=decision.task_type,
                    status="pending",
                    due_at=decision.due_at,
                    created_by_user_id=user.id,
                )
                db.add(task)
                db.flush()
                order.next_action_at = decision.due_at
                order.updated_at = utc_now()
                add_audit_log(
                    db,
                    entity_type="followup_task",
                    entity_id=task.id,
                    action="followup_task.recalculate_created",
                    user_id=user.id,
                    new_value={
                        "order_id": order.id,
                        "task_type": task.task_type,
                        "due_at": task.due_at,
                        "reason": decision.reason,
                    },
                )
                created_tasks += 1
            except Exception as exc:  # noqa: BLE001 - keep recalculate resilient and report per-order failures.
                errors.append(f"order {order.id}: {exc}")

        return FollowUpRecalculateResult(
            created_tasks=created_tasks,
            skipped_orders=skipped_orders,
            manual_review_orders=manual_review_orders,
            errors=errors,
        )

    def decide_next_task(self, db: Session, order: ClaimOrder, now: datetime | None = None) -> FollowUpDecision | None:
        now = normalize_datetime(now or utc_now())
        if order.status in FINAL_ORDER_STATUSES:
            return None
        if self.task_exists(db, order.id, "manual_review"):
            return None
        if self.has_unreviewed_inbound_message(db, order.id):
            return FollowUpDecision("manual_review", now, "unreviewed_inbound_message")
        if order.retry_count >= self.settings.max_followups_per_order:
            return FollowUpDecision("manual_review", now, "max_followups_reached")
        if order.status not in FOLLOWUP_ELIGIBLE_STATUSES:
            return None

        first_sent_at = self.first_sent_at(db, order)
        if first_sent_at is None:
            return None

        first_sent_at = normalize_datetime(first_sent_at)
        if now >= first_sent_at + timedelta(days=self.settings.manual_review_after_days):
            return FollowUpDecision(
                "manual_review",
                first_sent_at + timedelta(days=self.settings.manual_review_after_days),
                "manual_review_delay_reached",
            )
        if (
            now >= first_sent_at + timedelta(days=self.settings.escalation_delay_days)
            and self.email_draft_exists(db, order.id, "followup_1")
            and self.email_draft_exists(db, order.id, "followup_2")
            and not self.followup_exists(db, order.id, "escalation")
        ):
            return FollowUpDecision(
                "escalation",
                first_sent_at + timedelta(days=self.settings.escalation_delay_days),
                "escalation_delay_reached",
            )
        if (
            now >= first_sent_at + timedelta(days=self.settings.followup_2_delay_days)
            and self.email_draft_exists(db, order.id, "followup_1")
            and not self.followup_exists(db, order.id, "followup_2")
        ):
            return FollowUpDecision(
                "followup_2",
                first_sent_at + timedelta(days=self.settings.followup_2_delay_days),
                "followup_2_delay_reached",
            )
        if now >= first_sent_at + timedelta(days=self.settings.followup_1_delay_days) and not self.followup_exists(
            db,
            order.id,
            "followup_1",
        ):
            return FollowUpDecision(
                "followup_1",
                first_sent_at + timedelta(days=self.settings.followup_1_delay_days),
                "followup_1_delay_reached",
            )
        return None

    def first_sent_at(self, db: Session, order: ClaimOrder) -> datetime | None:
        dates = [order.first_email_sent_at]
        dates.append(
            db.scalar(
                select(func.min(EmailThread.sent_at)).where(
                    EmailThread.order_id == order.id,
                    EmailThread.direction == "outbound",
                    EmailThread.sent_at.is_not(None),
                )
            )
        )
        dates.append(
            db.scalar(
                select(func.min(EmailProviderDraft.sent_at))
                .join(EmailDraft, EmailProviderDraft.email_draft_id == EmailDraft.id)
                .where(
                    EmailDraft.order_id == order.id,
                    EmailProviderDraft.status == "sent",
                    EmailProviderDraft.sent_at.is_not(None),
                )
            )
        )
        present_dates = [normalize_datetime(value) for value in dates if value is not None]
        return min(present_dates) if present_dates else None

    def followup_exists(self, db: Session, order_id: int, draft_type: str) -> bool:
        if self.task_exists(db, order_id, draft_type):
            return True
        return self.email_draft_exists(db, order_id, draft_type)

    def email_draft_exists(self, db: Session, order_id: int, draft_type: str) -> bool:
        return (
            db.scalar(
                select(EmailDraft.id).where(
                    EmailDraft.order_id == order_id,
                    EmailDraft.draft_type == draft_type,
                )
            )
            is not None
        )

    def task_exists(self, db: Session, order_id: int, task_type: str) -> bool:
        return (
            db.scalar(
                select(FollowUpTask.id).where(
                    FollowUpTask.order_id == order_id,
                    FollowUpTask.task_type == task_type,
                )
            )
            is not None
        )

    def has_unreviewed_inbound_message(self, db: Session, order_id: int) -> bool:
        return (
            db.scalar(
                select(InboundEmailMessage.id).where(
                    InboundEmailMessage.order_id == order_id,
                    InboundEmailMessage.match_status == "linked",
                    InboundEmailMessage.review_status == "unreviewed",
                )
            )
            is not None
        )

    def next_action_after_completed_followup(self, db: Session, order: ClaimOrder) -> datetime | None:
        first_sent_at = self.first_sent_at(db, order)
        if first_sent_at is None:
            return None
        if order.retry_count >= self.settings.max_followups_per_order:
            return normalize_datetime(first_sent_at) + timedelta(days=self.settings.manual_review_after_days)
        if order.retry_count <= 1:
            return normalize_datetime(first_sent_at) + timedelta(days=self.settings.followup_2_delay_days)
        if order.retry_count == 2:
            return normalize_datetime(first_sent_at) + timedelta(days=self.settings.escalation_delay_days)
        return normalize_datetime(first_sent_at) + timedelta(days=self.settings.manual_review_after_days)


def apply_followup_completion_effects(
    db: Session,
    task: FollowUpTask,
    user: User,
    *,
    completed_at: datetime | None = None,
) -> None:
    now = completed_at or utc_now()
    order = task.order
    old_status = order.status
    old_retry_count = order.retry_count
    old_task_status = task.status
    was_completed = task.status == "completed"

    task.status = "completed"
    task.completed_by_user_id = user.id
    task.completed_at = now
    task.updated_at = now

    provider_draft = task.generated_provider_draft
    if task.task_type in FOLLOWUP_SENT_STATUS_BY_TYPE and provider_draft is not None and provider_draft.status == "sent":
        sent_at = provider_draft.sent_at or now
        if not was_completed:
            order.retry_count = order.retry_count + 1
        order.last_followup_sent_at = sent_at
        order.status = FOLLOWUP_SENT_STATUS_BY_TYPE[task.task_type]
        order.next_action_at = FollowUpPolicyService().next_action_after_completed_followup(db, order)
        order.updated_at = now
    elif task.task_type == "manual_review":
        order.status = "manual_review"
        order.next_action_at = None
        order.updated_at = now

    add_audit_log(
        db,
        entity_type="followup_task",
        entity_id=task.id,
        action="followup_task.completed",
        user_id=user.id,
        old_value={"order_status": old_status, "retry_count": old_retry_count, "task_status": old_task_status},
        new_value={
            "order_status": order.status,
            "retry_count": order.retry_count,
            "task_type": task.task_type,
            "provider_draft_id": provider_draft.id if provider_draft else None,
        },
    )


def complete_task_for_sent_provider_draft(db: Session, user: User, provider_draft: EmailProviderDraft) -> FollowUpTask | None:
    task = db.scalar(
        select(FollowUpTask).where(
            FollowUpTask.generated_provider_draft_id == provider_draft.id,
            FollowUpTask.status != "completed",
        )
    )
    if task is None:
        return None
    apply_followup_completion_effects(db, task, user, completed_at=provider_draft.sent_at or utc_now())
    return task


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
