from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_accessible_restaurant_ids, get_current_user
from app.core.database import get_db
from app.models import ClaimOrder, FollowUpTask, Restaurant, UberCustomerRefundDispute, User
from app.models.domain import utc_now
from app.schemas.domain import DashboardRestaurantSummary, DashboardSummary, DashboardTopRestaurantSummary
from app.services.reporting_service import (
    ReportingFilters,
    ReportingService,
    recovered_amount_for_customer_refund,
)

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])

TERMINAL_OR_RECOVERED_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}


def as_decimal(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummary:
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None and not accessible_ids:
        return DashboardSummary(
            total_orders=0,
            total_claimed_amount=Decimal("0"),
            total_recovered_amount=Decimal("0"),
            total_approved_amount=Decimal("0"),
            total_pending_amount=Decimal("0"),
            total_refused_amount=Decimal("0"),
            accepted_count=0,
            payment_to_verify_count=0,
            payment_confirmed_count=0,
            refused_count=0,
            manual_review_count=0,
            pending_response_count=0,
            followups_due_count=0,
            followups_pending_count=0,
            escalations_due_count=0,
            manual_review_due_count=0,
            orders_by_status={},
            orders_by_restaurant=[],
        )

    total_orders_statement = select(func.count(ClaimOrder.id))
    total_claimed_statement = select(func.sum(ClaimOrder.order_amount))
    total_recovered_statement = select(func.sum(ClaimOrder.recovered_amount))
    has_customer_refund_dispute = (
        select(UberCustomerRefundDispute.id)
        .where(UberCustomerRefundDispute.claim_order_id == ClaimOrder.id)
        .exists()
    )
    standalone_approved_statement = select(func.sum(ClaimOrder.order_amount)).where(
        ClaimOrder.status.in_(["accepted", "payment_to_verify"]),
        ClaimOrder.recovered_amount.is_(None),
        ~has_customer_refund_dispute,
    )
    total_refused_statement = select(func.sum(ClaimOrder.order_amount)).where(ClaimOrder.status == "refused")
    total_pending_statement = select(func.sum(ClaimOrder.order_amount)).where(
        ClaimOrder.status.notin_(TERMINAL_OR_RECOVERED_STATUSES)
    )
    status_statement = select(ClaimOrder.status, func.count(ClaimOrder.id)).group_by(ClaimOrder.status)

    if accessible_ids is not None:
        total_orders_statement = total_orders_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_claimed_statement = total_claimed_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_recovered_statement = total_recovered_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        standalone_approved_statement = standalone_approved_statement.where(
            ClaimOrder.restaurant_id.in_(accessible_ids)
        )
        total_refused_statement = total_refused_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_pending_statement = total_pending_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        status_statement = status_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    total_orders = db.scalar(total_orders_statement) or 0
    total_claimed_amount = as_decimal(db.scalar(total_claimed_statement))
    total_recovered_amount = as_decimal(db.scalar(total_recovered_statement))
    standalone_approved_amount = as_decimal(db.scalar(standalone_approved_statement))
    total_refused_amount = as_decimal(db.scalar(total_refused_statement))
    total_pending_amount = as_decimal(db.scalar(total_pending_statement))

    status_rows = db.execute(status_statement).all()
    orders_by_status = {status: count for status, count in status_rows}
    accepted_count = orders_by_status.get("accepted", 0)
    payment_to_verify_count = orders_by_status.get("payment_to_verify", 0)
    payment_confirmed_count = orders_by_status.get("payment_confirmed", 0)
    refused_count = orders_by_status.get("refused", 0)
    manual_review_count = orders_by_status.get("manual_review", 0)
    pending_response_count = orders_by_status.get("sent", 0) + orders_by_status.get("waiting_uber_response", 0)
    followup_counts = get_followup_counts(db, accessible_ids)

    restaurant_statement = (
        select(
            Restaurant.id,
            Restaurant.name,
            func.count(ClaimOrder.id),
            func.coalesce(func.sum(ClaimOrder.order_amount), 0),
            func.coalesce(func.sum(ClaimOrder.recovered_amount), 0),
        )
        .join(ClaimOrder, ClaimOrder.restaurant_id == Restaurant.id)
        .group_by(Restaurant.id, Restaurant.name)
        .order_by(Restaurant.id)
    )
    if accessible_ids is not None:
        restaurant_statement = restaurant_statement.where(Restaurant.id.in_(accessible_ids))

    restaurant_rows = db.execute(restaurant_statement).all()
    orders_by_restaurant = [
        DashboardRestaurantSummary(
            restaurant_id=restaurant_id,
            restaurant_name=restaurant_name,
            total_orders=order_count,
            total_claimed_amount=claimed_amount,
            total_recovered_amount=recovered_amount,
        )
        for restaurant_id, restaurant_name, order_count, claimed_amount, recovered_amount in restaurant_rows
    ]
    reporting_service = ReportingService(db, current_user, ReportingFilters())
    report_summary = reporting_service.commercial_summary()
    for customer_refund in reporting_service.customer_refund_rows():
        recovered_customer_refund = recovered_amount_for_customer_refund(customer_refund)
        if recovered_customer_refund is None:
            continue
        linked_order = (
            db.get(ClaimOrder, customer_refund.claim_order_id)
            if customer_refund.claim_order_id is not None
            else None
        )
        if linked_order is None or linked_order.recovered_amount is None:
            total_recovered_amount += recovered_customer_refund
    total_approved_amount = (
        standalone_approved_amount + report_summary.customer_refunds.total_approved_amount
    )
    top_restaurants_by_claimed_amount = [
        DashboardTopRestaurantSummary(
            restaurant_id=row.restaurant_id,
            restaurant_name=row.restaurant_name,
            amount=row.claimed_amount,
        )
        for row in sorted(report_summary.by_restaurant, key=lambda item: item.claimed_amount, reverse=True)[:5]
    ]
    top_restaurants_by_pending_amount = [
        DashboardTopRestaurantSummary(
            restaurant_id=row.restaurant_id,
            restaurant_name=row.restaurant_name,
            amount=row.pending_amount,
        )
        for row in sorted(report_summary.by_restaurant, key=lambda item: item.pending_amount, reverse=True)[:5]
    ]

    return DashboardSummary(
        total_orders=total_orders,
        total_claimed_amount=total_claimed_amount,
        total_recovered_amount=total_recovered_amount,
        total_approved_amount=total_approved_amount,
        total_pending_amount=total_pending_amount,
        total_refused_amount=total_refused_amount,
        accepted_count=accepted_count,
        payment_to_verify_count=payment_to_verify_count,
        payment_confirmed_count=payment_confirmed_count,
        refused_count=refused_count,
        manual_review_count=manual_review_count,
        pending_response_count=pending_response_count,
        followups_due_count=followup_counts["followups_due_count"],
        followups_pending_count=followup_counts["followups_pending_count"],
        escalations_due_count=followup_counts["escalations_due_count"],
        manual_review_due_count=followup_counts["manual_review_due_count"],
        success_rate=report_summary.totals.success_rate,
        top_restaurants_by_claimed_amount=top_restaurants_by_claimed_amount,
        top_restaurants_by_pending_amount=top_restaurants_by_pending_amount,
        orders_by_status=orders_by_status,
        orders_by_restaurant=orders_by_restaurant,
    )


def get_followup_counts(db: Session, accessible_ids: set[int] | None) -> dict[str, int]:
    now = utc_now()
    active_statuses = {"pending", "draft_created", "provider_draft_created"}

    base_statement = select(func.count(FollowUpTask.id)).join(ClaimOrder, FollowUpTask.order_id == ClaimOrder.id)
    if accessible_ids is not None:
        base_statement = base_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    due_statement = base_statement.where(FollowUpTask.status == "pending", FollowUpTask.due_at <= now)
    pending_statement = base_statement.where(FollowUpTask.status.in_(active_statuses))
    escalation_statement = base_statement.where(
        FollowUpTask.status == "pending",
        FollowUpTask.task_type == "escalation",
        FollowUpTask.due_at <= now,
    )
    manual_review_statement = base_statement.where(
        FollowUpTask.status == "pending",
        FollowUpTask.task_type == "manual_review",
        FollowUpTask.due_at <= now,
    )
    return {
        "followups_due_count": db.scalar(due_statement) or 0,
        "followups_pending_count": db.scalar(pending_statement) or 0,
        "escalations_due_count": db.scalar(escalation_statement) or 0,
        "manual_review_due_count": db.scalar(manual_review_statement) or 0,
    }
