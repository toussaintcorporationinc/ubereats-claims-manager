from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.models import (
    ClaimOrder,
    ClaimResponseReview,
    EmailDraft,
    EvidenceFile,
    FollowUpTask,
    InboundEmailMessage,
    Restaurant,
    UberCustomerRefundDispute,
    User,
)
from app.models.domain import utc_now
from app.schemas.domain import (
    CommercialFollowupSummary,
    CommercialCustomerRefundSummary,
    CommercialResponseSummary,
    CommercialRestaurantSummary,
    CommercialSummary,
    CommercialTotals,
    ReportBreakdownItem,
    ReportFilterEcho,
    ReportFollowupRow,
    ReportOrderRow,
    ReportResponseRow,
)

FINAL_ORDER_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}
SUCCESS_STATUSES = {"accepted", "payment_confirmed"}
PROCESSED_STATUSES = {"accepted", "payment_confirmed", "refused"}


@dataclass(frozen=True)
class ReportingFilters:
    restaurant_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None
    result: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    include_customer_names: bool = False

    def to_echo(self) -> ReportFilterEcho:
        return ReportFilterEcho(**self.__dict__)


class ReportingPermissionError(Exception):
    pass


class ReportingExportLimitError(Exception):
    pass


class ReportingService:
    def __init__(self, db: Session, user: User, filters: ReportingFilters | None = None) -> None:
        self.db = db
        self.user = user
        self.filters = filters or ReportingFilters()

    def commercial_summary(self) -> CommercialSummary:
        orders = self.order_rows(limit=None, offset=0)
        followups = self.followup_rows(limit=None, offset=0)
        responses = self.response_rows(limit=None, offset=0)
        customer_refunds = self.customer_refund_rows()

        total_claimed = sum_decimal(row.order_amount for row in orders)
        total_recovered = sum_decimal(row.recovered_amount for row in orders)
        total_refused = sum_decimal(row.order_amount for row in orders if row.status == "refused")
        total_pending = sum_decimal(row.order_amount for row in orders if row.status not in FINAL_ORDER_STATUSES)
        average_claim = quantize_decimal(total_claimed / len(orders)) if orders else Decimal("0")
        processed_count = len([row for row in orders if row.status in PROCESSED_STATUSES])
        success_count = len([row for row in orders if row.status in SUCCESS_STATUSES])
        success_rate = quantize_decimal(Decimal(success_count) / Decimal(processed_count)) if processed_count else Decimal("0")

        return CommercialSummary(
            filters=self.filters.to_echo(),
            totals=CommercialTotals(
                orders_count=len(orders),
                total_claimed_amount=total_claimed,
                total_recovered_amount=total_recovered,
                total_pending_amount=total_pending,
                total_refused_amount=total_refused,
                average_claim_amount=average_claim,
                success_rate=success_rate,
            ),
            by_status=breakdown_orders(orders, lambda row: row.status),
            by_result=breakdown_orders(orders, lambda row: row.result or "none"),
            by_restaurant=restaurant_breakdown(orders),
            followups=CommercialFollowupSummary(
                due_count=len([row for row in followups if row.task_status == "pending" and is_due(row.due_at)]),
                pending_count=len([row for row in followups if row.task_status in {"pending", "draft_created", "provider_draft_created"}]),
                escalation_due_count=len(
                    [row for row in followups if row.task_type == "escalation" and row.task_status == "pending" and is_due(row.due_at)]
                ),
                manual_review_count=len(
                    [row for row in followups if row.task_type == "manual_review" and row.task_status == "pending" and is_due(row.due_at)]
                ),
            ),
            responses=CommercialResponseSummary(
                accepted_count=len([row for row in responses if row.review_type == "accepted"]),
                refused_count=len([row for row in responses if row.review_type == "refused"]),
                payment_to_verify_count=len([row for row in responses if row.review_type == "payment_to_verify"]),
                payment_confirmed_count=len([row for row in responses if row.review_type == "payment_confirmed"]),
                manual_review_count=len([row for row in responses if row.review_type == "manual_review"]),
            ),
            customer_refunds=CommercialCustomerRefundSummary(
                total_deducted_amount=sum_decimal(row.customer_refund_amount for row in customer_refunds),
                total_recovered_amount=sum_decimal(recovered_amount_for_customer_refund(row) for row in customer_refunds),
                total_refused_amount=sum_decimal(
                    row.customer_refund_amount for row in customer_refunds if row.status == "refused"
                ),
                total_pending_amount=sum_decimal(
                    row.customer_refund_amount
                    for row in customer_refunds
                    if row.status not in {"payment_confirmed", "refused", "ignored"}
                ),
                disputes_count=len(customer_refunds),
                needs_evidence_count=len([row for row in customer_refunds if row.evidence_status in {"missing", "partial"}]),
                evidence_ready_count=len([row for row in customer_refunds if row.evidence_status == "complete"]),
                sent_count=len([row for row in customer_refunds if row.status == "sent"]),
                accepted_count=len([row for row in customer_refunds if row.status in {"accepted", "payment_confirmed"}]),
                refused_count=len([row for row in customer_refunds if row.status == "refused"]),
            ),
        )

    def customer_refund_rows(self) -> list[UberCustomerRefundDispute]:
        statement = select(UberCustomerRefundDispute)
        statement = self.apply_customer_refund_filters(statement)
        return list(self.db.scalars(statement).all())

    def order_rows(self, *, limit: int | None, offset: int = 0) -> list[ReportOrderRow]:
        evidence_counts = (
            select(EvidenceFile.order_id, func.count(EvidenceFile.id).label("count"))
            .where(EvidenceFile.deleted_at.is_(None))
            .group_by(EvidenceFile.order_id)
            .subquery()
        )
        draft_counts = (
            select(EmailDraft.order_id, func.count(EmailDraft.id).label("count"))
            .group_by(EmailDraft.order_id)
            .subquery()
        )
        inbound_counts = (
            select(InboundEmailMessage.order_id, func.count(InboundEmailMessage.id).label("count"))
            .where(InboundEmailMessage.order_id.is_not(None))
            .group_by(InboundEmailMessage.order_id)
            .subquery()
        )
        response_counts = (
            select(ClaimResponseReview.order_id, func.count(ClaimResponseReview.id).label("count"))
            .group_by(ClaimResponseReview.order_id)
            .subquery()
        )

        statement = (
            select(
                ClaimOrder,
                Restaurant.name.label("restaurant_name"),
                func.coalesce(evidence_counts.c.count, 0).label("evidence_count"),
                func.coalesce(draft_counts.c.count, 0).label("drafts_count"),
                func.coalesce(inbound_counts.c.count, 0).label("inbound_messages_count"),
                func.coalesce(response_counts.c.count, 0).label("response_reviews_count"),
            )
            .join(Restaurant, ClaimOrder.restaurant_id == Restaurant.id)
            .outerjoin(evidence_counts, evidence_counts.c.order_id == ClaimOrder.id)
            .outerjoin(draft_counts, draft_counts.c.order_id == ClaimOrder.id)
            .outerjoin(inbound_counts, inbound_counts.c.order_id == ClaimOrder.id)
            .outerjoin(response_counts, response_counts.c.order_id == ClaimOrder.id)
            .order_by(ClaimOrder.order_date.desc().nullslast(), ClaimOrder.id.desc())
        )
        statement = self.apply_order_filters(statement)
        if limit is not None:
            statement = statement.limit(limit).offset(offset)

        rows = self.db.execute(statement).all()
        return [
            ReportOrderRow(
                order_id=order.id,
                restaurant_id=order.restaurant_id,
                restaurant_name=restaurant_name,
                uber_order_number=order.uber_order_number,
                customer_name=order.customer_name if self.filters.include_customer_names else None,
                order_date=order.order_date,
                order_amount=order.order_amount,
                currency=order.currency,
                status=order.status,
                result=order.result,
                recovered_amount=order.recovered_amount,
                retry_count=order.retry_count,
                last_followup_sent_at=order.last_followup_sent_at,
                next_action_at=order.next_action_at,
                evidence_count=evidence_count,
                drafts_count=drafts_count,
                inbound_messages_count=inbound_messages_count,
                response_reviews_count=response_reviews_count,
            )
            for order, restaurant_name, evidence_count, drafts_count, inbound_messages_count, response_reviews_count in rows
        ]

    def followup_rows(self, *, limit: int | None, offset: int = 0) -> list[ReportFollowupRow]:
        statement = (
            select(FollowUpTask, ClaimOrder, Restaurant.name.label("restaurant_name"))
            .join(ClaimOrder, FollowUpTask.order_id == ClaimOrder.id)
            .join(Restaurant, ClaimOrder.restaurant_id == Restaurant.id)
            .order_by(FollowUpTask.due_at.asc(), FollowUpTask.id.asc())
        )
        statement = self.apply_order_filters(statement)
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        rows = self.db.execute(statement).all()
        return [
            ReportFollowupRow(
                task_id=task.id,
                restaurant_name=restaurant_name,
                order_id=order.id,
                uber_order_number=order.uber_order_number,
                task_type=task.task_type,
                task_status=task.status,
                due_at=task.due_at,
                claim_status=order.status,
                order_amount=order.order_amount,
                currency=order.currency,
                retry_count=order.retry_count,
            )
            for task, order, restaurant_name in rows
        ]

    def response_rows(self, *, limit: int | None, offset: int = 0) -> list[ReportResponseRow]:
        statement = (
            select(ClaimResponseReview, ClaimOrder, Restaurant.name.label("restaurant_name"))
            .join(ClaimOrder, ClaimResponseReview.order_id == ClaimOrder.id)
            .join(Restaurant, ClaimOrder.restaurant_id == Restaurant.id)
            .order_by(ClaimResponseReview.created_at.desc(), ClaimResponseReview.id.desc())
        )
        statement = self.apply_order_filters(statement)
        if limit is not None:
            statement = statement.limit(limit).offset(offset)
        rows = self.db.execute(statement).all()
        return [
            ReportResponseRow(
                review_id=review.id,
                restaurant_name=restaurant_name,
                order_id=order.id,
                uber_order_number=order.uber_order_number,
                review_type=review.review_type,
                previous_order_status=review.previous_order_status,
                new_order_status=review.new_order_status,
                recovered_amount=review.recovered_amount,
                refusal_reason=review.refusal_reason,
                evidence_requested=review.evidence_requested,
                created_at=review.created_at,
                reviewed_by_user_id=review.reviewed_by_user_id,
            )
            for review, order, restaurant_name in rows
        ]

    def apply_order_filters(self, statement: Any) -> Any:
        accessible_ids = get_accessible_restaurant_ids(self.db, self.user)
        if self.filters.restaurant_id is not None:
            if not can_access_restaurant(self.db, self.user, self.filters.restaurant_id):
                raise ReportingPermissionError("Restaurant access denied")
            statement = statement.where(ClaimOrder.restaurant_id == self.filters.restaurant_id)
        elif accessible_ids is not None:
            if not accessible_ids:
                return statement.where(ClaimOrder.id == -1)
            statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

        if self.filters.date_from is not None:
            statement = statement.where(ClaimOrder.order_date >= self.filters.date_from)
        if self.filters.date_to is not None:
            statement = statement.where(ClaimOrder.order_date <= self.filters.date_to)
        if self.filters.status:
            statement = statement.where(ClaimOrder.status == self.filters.status)
        if self.filters.result:
            statement = statement.where(ClaimOrder.result == self.filters.result)
        if self.filters.min_amount is not None:
            statement = statement.where(ClaimOrder.order_amount >= self.filters.min_amount)
        if self.filters.max_amount is not None:
            statement = statement.where(ClaimOrder.order_amount <= self.filters.max_amount)
        return statement

    def apply_customer_refund_filters(self, statement: Any) -> Any:
        accessible_ids = get_accessible_restaurant_ids(self.db, self.user)
        if self.filters.restaurant_id is not None:
            if not can_access_restaurant(self.db, self.user, self.filters.restaurant_id):
                raise ReportingPermissionError("Restaurant access denied")
            statement = statement.where(UberCustomerRefundDispute.restaurant_id == self.filters.restaurant_id)
        elif accessible_ids is not None:
            if not accessible_ids:
                return statement.where(UberCustomerRefundDispute.id == -1)
            statement = statement.where(UberCustomerRefundDispute.restaurant_id.in_(accessible_ids))
        if self.filters.date_from is not None:
            statement = statement.where(UberCustomerRefundDispute.deducted_at >= self.filters.date_from)
        if self.filters.date_to is not None:
            statement = statement.where(UberCustomerRefundDispute.deducted_at <= self.filters.date_to)
        if self.filters.status:
            statement = statement.where(UberCustomerRefundDispute.status == self.filters.status)
        if self.filters.min_amount is not None:
            statement = statement.where(UberCustomerRefundDispute.customer_refund_amount >= self.filters.min_amount)
        if self.filters.max_amount is not None:
            statement = statement.where(UberCustomerRefundDispute.customer_refund_amount <= self.filters.max_amount)
        return statement

    def ensure_export_limit(self, rows: list[object], max_rows: int) -> None:
        if len(rows) > max_rows:
            raise ReportingExportLimitError(f"Export row limit exceeded: {len(rows)} rows > {max_rows}")


def sum_decimal(values: list[Decimal | None] | Any) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return quantize_decimal(total)


def quantize_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recovered_amount_for_customer_refund(row: UberCustomerRefundDispute) -> Decimal | None:
    if row.recovered_amount is not None:
        return row.recovered_amount
    if row.status == "payment_confirmed":
        return row.customer_refund_amount
    return None


def breakdown_orders(orders: list[ReportOrderRow], key_func: Any) -> list[ReportBreakdownItem]:
    grouped: dict[str, list[ReportOrderRow]] = {}
    for order in orders:
        grouped.setdefault(str(key_func(order)), []).append(order)
    return [
        ReportBreakdownItem(
            key=key,
            count=len(rows),
            claimed_amount=sum_decimal(row.order_amount for row in rows),
            recovered_amount=sum_decimal(row.recovered_amount for row in rows),
        )
        for key, rows in sorted(grouped.items())
    ]


def restaurant_breakdown(orders: list[ReportOrderRow]) -> list[CommercialRestaurantSummary]:
    grouped: dict[int, list[ReportOrderRow]] = {}
    for order in orders:
        grouped.setdefault(order.restaurant_id, []).append(order)
    result: list[CommercialRestaurantSummary] = []
    for restaurant_id, rows in sorted(grouped.items()):
        restaurant_name = rows[0].restaurant_name
        result.append(
            CommercialRestaurantSummary(
                restaurant_id=restaurant_id,
                restaurant_name=restaurant_name,
                orders_count=len(rows),
                claimed_amount=sum_decimal(row.order_amount for row in rows),
                recovered_amount=sum_decimal(row.recovered_amount for row in rows),
                pending_amount=sum_decimal(row.order_amount for row in rows if row.status not in FINAL_ORDER_STATUSES),
                refused_amount=sum_decimal(row.order_amount for row in rows if row.status == "refused"),
                accepted_count=len([row for row in rows if row.status == "accepted"]),
                refused_count=len([row for row in rows if row.status == "refused"]),
                manual_review_count=len([row for row in rows if row.status == "manual_review"]),
            )
        )
    return result


def is_due(value: Any) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=utc_now().tzinfo)
    return value <= utc_now()
