from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.models import (
    ClaimOrder,
    EvidenceRequestTask,
    FollowUpTask,
    UberCustomerRefundDispute,
    UberReconciliationResult,
    User,
)
from app.models.domain import utc_now
from app.schemas.domain import (
    RecoveryAction,
    RecoveryBreakdownItem,
    RecoveryCase,
    RecoveryFilterEcho,
    RecoveryRestaurantBreakdownItem,
    RecoverySummary,
    RecoveryTotals,
)

FINAL_CASE_STAGES = {"payment_confirmed", "refused", "ignored"}
RECOVERED_STAGES = {"payment_confirmed"}
REFUSED_STAGES = {"refused"}
SENT_STAGES = {"sent", "waiting_uber_response", "response_received", "followup_1_sent", "followup_2_sent", "escalation_sent"}
MISSING_EVIDENCE_STAGES = {"needs_evidence", "missing_evidence"}
MANUAL_REVIEW_STAGES = {"manual_review"}


@dataclass(frozen=True)
class RecoveryFilters:
    restaurant_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    loss_category: str | None = None
    include_ignored: bool = False

    def to_echo(self) -> RecoveryFilterEcho:
        return RecoveryFilterEcho(**self.__dict__)


class RecoveryPermissionError(Exception):
    pass


class RecoveryExportLimitError(Exception):
    pass


class RecoveryCockpitService:
    def __init__(self, db: Session, user: User, filters: RecoveryFilters | None = None) -> None:
        self.db = db
        self.user = user
        self.filters = filters or RecoveryFilters()

    def summary(self) -> RecoverySummary:
        cases = self.cases(limit=None, offset=0)
        return RecoverySummary(
            filters=self.filters.to_echo(),
            totals=build_totals(cases),
            by_restaurant=restaurant_breakdown(cases),
            by_loss_category=breakdown(cases, lambda item: item.loss_category),
            by_recovery_stage=breakdown(cases, lambda item: item.recovery_stage),
            top_recoverable_cases=sorted(
                [case for case in cases if case.claimable_amount > 0],
                key=lambda item: (item.claimable_amount, item.detected_amount, item.created_at),
                reverse=True,
            )[:10],
        )

    def cases(self, *, limit: int | None, offset: int = 0) -> list[RecoveryCase]:
        raw_cases = [
            *self.claim_order_cases(),
            *self.reconciliation_cases(),
            *self.customer_refund_cases(),
        ]
        filtered = [case for case in raw_cases if self.case_matches_filters(case)]
        filtered.sort(key=lambda item: (item.claimable_amount, item.detected_amount, item.created_at), reverse=True)
        if limit is None:
            return filtered
        return filtered[offset : offset + limit]

    def actions(self, *, limit: int | None, offset: int = 0) -> list[RecoveryAction]:
        actions = [*self.evidence_actions()]
        if self.user.role in {"owner", "manager"}:
            actions.extend(self.customer_refund_actions())
            actions.extend(self.followup_actions())
        actions.sort(key=lambda item: (priority_rank(item.priority), normalized_datetime(item.due_at)), reverse=True)
        if limit is None:
            return actions
        return actions[offset : offset + limit]

    def ensure_export_limit(self, rows: list[object], max_rows: int) -> None:
        if self.user.role == "staff":
            raise RecoveryPermissionError("Staff cannot export financial recovery reports")
        if len(rows) > max_rows:
            raise RecoveryExportLimitError(f"Export row limit exceeded: {len(rows)} rows > {max_rows}")

    def claim_order_cases(self) -> list[RecoveryCase]:
        statement = select(ClaimOrder).order_by(ClaimOrder.created_at.desc(), ClaimOrder.id.desc())
        statement = self.apply_restaurant_filter(statement, ClaimOrder)
        orders = self.db.scalars(statement).all()
        cases = []
        for order in orders:
            amount = money(order.order_amount)
            stage = claim_order_stage(order.status)
            recovered = recovered_amount(order.recovered_amount, stage, amount)
            refused = amount if stage in REFUSED_STAGES else Decimal("0")
            claimable = claimable_amount(amount, stage, recovered, refused)
            cases.append(
                RecoveryCase(
                    case_type="claim_order",
                    case_id=order.id,
                    restaurant_id=order.restaurant_id,
                    restaurant_name=order.restaurant.name if order.restaurant else f"#{order.restaurant_id}",
                    uber_order_number=order.uber_order_number,
                    loss_category=claim_order_loss_category(order),
                    recovery_stage=stage,
                    detected_amount=amount,
                    claimable_amount=claimable,
                    recovered_amount=recovered,
                    status=order.status,
                    evidence_status="missing" if order.status == "missing_evidence" else None,
                    next_action=next_action_for_stage(stage),
                    created_at=order.created_at,
                    link_url=f"/orders/{order.id}",
                )
            )
        return cases

    def reconciliation_cases(self) -> list[RecoveryCase]:
        statement = select(UberReconciliationResult).order_by(
            UberReconciliationResult.created_at.desc(), UberReconciliationResult.id.desc()
        )
        statement = self.apply_restaurant_filter(statement, UberReconciliationResult)
        results = self.db.scalars(statement).all()
        cases = []
        for result in results:
            amount = money(result.missing_amount if result.missing_amount is not None else result.order_amount)
            stage = reconciliation_stage(result.status, result.evidence_required)
            recovered = Decimal("0")
            claimable = amount if result.status in {"not_compensated", "partially_compensated", "needs_evidence"} else Decimal("0")
            cases.append(
                RecoveryCase(
                    case_type="reconciliation_result",
                    case_id=result.id,
                    restaurant_id=result.restaurant_id,
                    restaurant_name=result.restaurant.name if result.restaurant else f"#{result.restaurant_id}",
                    uber_order_number=result.display_id or result.uber_order_id,
                    loss_category="cancellation_not_compensated",
                    recovery_stage=stage,
                    detected_amount=amount,
                    claimable_amount=quantize_decimal(claimable),
                    recovered_amount=recovered,
                    status=result.status,
                    evidence_status="missing" if result.evidence_required else None,
                    next_action=next_action_for_stage(stage),
                    created_at=result.created_at,
                    link_url=f"/uber/reconciliation/results/{result.id}",
                )
            )
        return cases

    def customer_refund_cases(self) -> list[RecoveryCase]:
        statement = select(UberCustomerRefundDispute).order_by(
            UberCustomerRefundDispute.created_at.desc(), UberCustomerRefundDispute.id.desc()
        )
        statement = self.apply_restaurant_filter(statement, UberCustomerRefundDispute)
        disputes = self.db.scalars(statement).all()
        cases = []
        for dispute in disputes:
            amount = money(dispute.customer_refund_amount)
            stage = customer_refund_stage(dispute.status)
            recovered = recovered_amount(dispute.recovered_amount, stage, amount)
            refused = amount if stage in REFUSED_STAGES else Decimal("0")
            cases.append(
                RecoveryCase(
                    case_type="customer_refund_dispute",
                    case_id=dispute.id,
                    restaurant_id=dispute.restaurant_id,
                    restaurant_name=dispute.restaurant.name if dispute.restaurant else f"#{dispute.restaurant_id}",
                    uber_order_number=dispute.display_id or dispute.uber_order_id,
                    loss_category=customer_refund_loss_category(dispute.dispute_type),
                    recovery_stage=stage,
                    detected_amount=amount,
                    claimable_amount=claimable_amount(amount, stage, recovered, refused),
                    recovered_amount=recovered,
                    status=dispute.status,
                    evidence_status=dispute.evidence_status,
                    next_action=next_action_for_stage(stage),
                    created_at=dispute.created_at,
                    link_url=f"/customer-refunds/{dispute.id}",
                )
            )
        return cases

    def evidence_actions(self) -> list[RecoveryAction]:
        statement = select(EvidenceRequestTask).where(EvidenceRequestTask.status.in_(("pending", "uploaded")))
        statement = self.apply_restaurant_filter(statement, EvidenceRequestTask)
        tasks = self.db.scalars(statement).all()
        return [
            RecoveryAction(
                action_type="upload_evidence",
                case_type="evidence_request_task",
                case_id=task.id,
                restaurant_name=task.restaurant.name if task.restaurant else f"#{task.restaurant_id}",
                priority=task.priority,
                amount=money(task.order.order_amount if task.order else None),
                due_at=task.due_at,
                label=task.title,
                url=f"/evidence-tasks/{task.id}",
            )
            for task in tasks
        ]

    def customer_refund_actions(self) -> list[RecoveryAction]:
        statement = select(UberCustomerRefundDispute).where(UberCustomerRefundDispute.status.not_in(("ignored", "refused", "payment_confirmed")))
        statement = self.apply_restaurant_filter(statement, UberCustomerRefundDispute)
        disputes = self.db.scalars(statement).all()
        actions: list[RecoveryAction] = []
        for dispute in disputes:
            action_type, label, priority = customer_refund_action(dispute)
            actions.append(
                RecoveryAction(
                    action_type=action_type,
                    case_type="customer_refund_dispute",
                    case_id=dispute.id,
                    restaurant_name=dispute.restaurant.name if dispute.restaurant else f"#{dispute.restaurant_id}",
                    priority=priority,
                    amount=money(dispute.customer_refund_amount),
                    due_at=None,
                    label=label,
                    url=f"/customer-refunds/{dispute.id}",
                )
            )
        return actions

    def followup_actions(self) -> list[RecoveryAction]:
        statement = (
            select(FollowUpTask)
            .join(ClaimOrder, FollowUpTask.order_id == ClaimOrder.id)
            .where(FollowUpTask.status.in_(("pending", "draft_created", "provider_draft_created")))
        )
        statement = self.apply_restaurant_filter(statement, ClaimOrder)
        tasks = self.db.scalars(statement).all()
        return [
            RecoveryAction(
                action_type="followup",
                case_type="followup_task",
                case_id=task.id,
                restaurant_name=task.order.restaurant.name if task.order and task.order.restaurant else f"#{task.order.restaurant_id}",
                priority="high" if is_due(task.due_at) else "normal",
                amount=money(task.order.order_amount if task.order else None),
                due_at=task.due_at,
                label=f"Relance {task.task_type} a traiter",
                url="/followups",
            )
            for task in tasks
        ]

    def apply_restaurant_filter(self, statement, model):
        accessible_ids = get_accessible_restaurant_ids(self.db, self.user)
        restaurant_column = model.restaurant_id
        if self.filters.restaurant_id is not None:
            if not can_access_restaurant(self.db, self.user, self.filters.restaurant_id):
                raise RecoveryPermissionError("Restaurant access denied")
            return statement.where(restaurant_column == self.filters.restaurant_id)
        if accessible_ids is not None:
            if not accessible_ids:
                return statement.where(restaurant_column == -1)
            return statement.where(restaurant_column.in_(accessible_ids))
        return statement

    def case_matches_filters(self, case: RecoveryCase) -> bool:
        if not self.filters.include_ignored and case.recovery_stage == "ignored":
            return False
        if self.filters.loss_category and case.loss_category != self.filters.loss_category:
            return False
        case_date = case.created_at.date()
        if self.filters.date_from and case_date < self.filters.date_from:
            return False
        if self.filters.date_to and case_date > self.filters.date_to:
            return False
        return True


def build_totals(cases: list[RecoveryCase]) -> RecoveryTotals:
    detected_amount = sum_decimal(case.detected_amount for case in cases)
    claimable_amount_total = sum_decimal(case.claimable_amount for case in cases)
    missing_evidence_amount = sum_decimal(
        case.detected_amount for case in cases if case.recovery_stage in MISSING_EVIDENCE_STAGES or case.evidence_status in {"missing", "partial"}
    )
    sent_amount = sum_decimal(case.detected_amount for case in cases if case.recovery_stage in SENT_STAGES)
    recovered = sum_decimal(case.recovered_amount for case in cases)
    refused = sum_decimal(case.detected_amount for case in cases if case.recovery_stage in REFUSED_STAGES)
    pending = max(claimable_amount_total - recovered - refused, Decimal("0"))
    reviewed_count = len([case for case in cases if case.recovery_stage not in {"detected", "needs_evidence", "evidence_ready", "draft_created", "gmail_draft_created", "sent"}])
    return RecoveryTotals(
        detected_amount=detected_amount,
        claimable_amount=claimable_amount_total,
        missing_evidence_amount=missing_evidence_amount,
        sent_amount=sent_amount,
        recovered_amount=recovered,
        refused_amount=refused,
        pending_amount=quantize_decimal(pending),
        detected_count=len(cases),
        claimable_count=len([case for case in cases if case.claimable_amount > 0]),
        missing_evidence_count=len(
            [case for case in cases if case.recovery_stage in MISSING_EVIDENCE_STAGES or case.evidence_status in {"missing", "partial"}]
        ),
        sent_count=len([case for case in cases if case.recovery_stage in SENT_STAGES]),
        recovered_count=len([case for case in cases if case.recovered_amount > 0 or case.recovery_stage in RECOVERED_STAGES]),
        refused_count=len([case for case in cases if case.recovery_stage in REFUSED_STAGES]),
        manual_review_count=len([case for case in cases if case.recovery_stage in MANUAL_REVIEW_STAGES]),
        recovery_rate=ratio(recovered, sent_amount),
        review_coverage_rate=ratio(Decimal(reviewed_count), Decimal(len(cases))),
    )


def restaurant_breakdown(cases: list[RecoveryCase]) -> list[RecoveryRestaurantBreakdownItem]:
    grouped: dict[int, list[RecoveryCase]] = {}
    for case in cases:
        grouped.setdefault(case.restaurant_id, []).append(case)
    rows = []
    for restaurant_id, items in sorted(grouped.items()):
        base = aggregate_items(items)
        rows.append(
            RecoveryRestaurantBreakdownItem(
                key=str(restaurant_id),
                restaurant_id=restaurant_id,
                restaurant_name=items[0].restaurant_name,
                **base,
            )
        )
    return rows


def breakdown(cases: list[RecoveryCase], key_func) -> list[RecoveryBreakdownItem]:
    grouped: dict[str, list[RecoveryCase]] = {}
    for case in cases:
        grouped.setdefault(str(key_func(case)), []).append(case)
    return [RecoveryBreakdownItem(key=key, **aggregate_items(items)) for key, items in sorted(grouped.items())]


def aggregate_items(items: list[RecoveryCase]) -> dict[str, object]:
    return {
        "count": len(items),
        "detected_amount": sum_decimal(item.detected_amount for item in items),
        "claimable_amount": sum_decimal(item.claimable_amount for item in items),
        "recovered_amount": sum_decimal(item.recovered_amount for item in items),
        "refused_amount": sum_decimal(item.detected_amount for item in items if item.recovery_stage in REFUSED_STAGES),
    }


def claim_order_stage(status: str) -> str:
    if status == "missing_evidence":
        return "needs_evidence"
    if status == "ready_to_send":
        return "evidence_ready"
    if status == "draft_email_created":
        return "draft_created"
    if status in {"waiting_uber_response", "followup_1_sent", "followup_2_sent", "escalation_sent"}:
        return "sent"
    if status in {
        "detected",
        "needs_evidence",
        "evidence_ready",
        "draft_created",
        "gmail_draft_created",
        "sent",
        "response_received",
        "accepted",
        "payment_to_verify",
        "payment_confirmed",
        "refused",
        "ignored",
        "manual_review",
    }:
        return status
    return "manual_review"


def reconciliation_stage(status: str, evidence_required: bool) -> str:
    if status == "compensated":
        return "payment_confirmed"
    if status in {"not_compensated", "partially_compensated", "needs_evidence"}:
        return "needs_evidence" if evidence_required else "detected"
    if status == "already_claimed":
        return "manual_review"
    if status == "ignored":
        return "ignored"
    return "manual_review"


def customer_refund_stage(status: str) -> str:
    return status if status != "evidence_ready" else "evidence_ready"


def claim_order_loss_category(order: ClaimOrder) -> str:
    if order.loss_type == "customer_refund_dispute":
        return "customer_refund"
    return "cancellation_not_compensated"


def customer_refund_loss_category(dispute_type: str) -> str:
    mapping = {
        "order_not_received": "order_not_received",
        "missing_item": "missing_item",
        "incorrect_item": "incorrect_item",
        "order_error_adjustment": "order_error_adjustment",
        "chargeback": "chargeback",
        "unknown": "manual_review",
    }
    return mapping.get(dispute_type, "customer_refund")


def next_action_for_stage(stage: str) -> str | None:
    return {
        "needs_evidence": "upload_evidence",
        "evidence_ready": "create_draft",
        "draft_created": "create_gmail_draft",
        "gmail_draft_created": "send_manually",
        "sent": "process_response_or_followup",
        "response_received": "process_response",
        "payment_to_verify": "verify_payment",
        "manual_review": "manual_review",
    }.get(stage)


def customer_refund_action(dispute: UberCustomerRefundDispute) -> tuple[str, str, str]:
    if dispute.claim_order_id is None:
        return "create_claim_order", "Creer dossier TENNET", "high"
    if dispute.evidence_status in {"missing", "partial"}:
        return "upload_evidence", "Completer les preuves", "high"
    if dispute.dispute_email_draft_id is None and dispute.evidence_status in {"complete", "not_required"}:
        return "create_draft", "Creer brouillon interne", "normal"
    if dispute.provider_draft_id is None and dispute.dispute_email_draft_id is not None:
        return "create_gmail_draft", "Creer brouillon Gmail", "normal"
    if dispute.status in {"sent", "payment_to_verify", "manual_review"}:
        return "process_response", "Traiter la decision Uber", "normal"
    return "manual_review", "Revue manuelle", "normal"


def claimable_amount(amount: Decimal, stage: str, recovered: Decimal, refused: Decimal) -> Decimal:
    if stage in FINAL_CASE_STAGES:
        return Decimal("0")
    return quantize_decimal(max(amount - recovered - refused, Decimal("0")))


def recovered_amount(value: Decimal | None, stage: str, amount: Decimal) -> Decimal:
    if value is not None:
        return quantize_decimal(value)
    if stage == "payment_confirmed":
        return amount
    return Decimal("0")


def sum_decimal(values: Iterable[Decimal | None]) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return quantize_decimal(total)


def money(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return quantize_decimal(Decimal(str(value)))


def quantize_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return quantize_decimal(numerator / denominator)


def priority_rank(value: str) -> int:
    return {"urgent": 4, "high": 3, "normal": 2, "low": 1}.get(value, 0)


def normalized_datetime(value):
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=utc_now().tzinfo)
    return value


def is_due(value) -> bool:
    if value is None:
        return False
    return normalized_datetime(value) <= utc_now()
