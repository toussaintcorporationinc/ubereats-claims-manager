from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_accessible_restaurant_ids, get_current_user
from app.core.database import get_db
from app.models import ClaimOrder, Restaurant, User
from app.schemas.domain import DashboardRestaurantSummary, DashboardSummary

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
            total_pending_amount=Decimal("0"),
            total_refused_amount=Decimal("0"),
            orders_by_status={},
            orders_by_restaurant=[],
        )

    total_orders_statement = select(func.count(ClaimOrder.id))
    total_claimed_statement = select(func.sum(ClaimOrder.order_amount))
    total_recovered_statement = select(func.sum(ClaimOrder.recovered_amount))
    total_refused_statement = select(func.sum(ClaimOrder.order_amount)).where(ClaimOrder.status == "refused")
    total_pending_statement = select(func.sum(ClaimOrder.order_amount)).where(
        ClaimOrder.status.notin_(TERMINAL_OR_RECOVERED_STATUSES)
    )
    status_statement = select(ClaimOrder.status, func.count(ClaimOrder.id)).group_by(ClaimOrder.status)

    if accessible_ids is not None:
        total_orders_statement = total_orders_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_claimed_statement = total_claimed_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_recovered_statement = total_recovered_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_refused_statement = total_refused_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        total_pending_statement = total_pending_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
        status_statement = status_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    total_orders = db.scalar(total_orders_statement) or 0
    total_claimed_amount = as_decimal(db.scalar(total_claimed_statement))
    total_recovered_amount = as_decimal(db.scalar(total_recovered_statement))
    total_refused_amount = as_decimal(db.scalar(total_refused_statement))
    total_pending_amount = as_decimal(db.scalar(total_pending_statement))

    status_rows = db.execute(status_statement).all()
    orders_by_status = {status: count for status, count in status_rows}

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

    return DashboardSummary(
        total_orders=total_orders,
        total_claimed_amount=total_claimed_amount,
        total_recovered_amount=total_recovered_amount,
        total_pending_amount=total_pending_amount,
        total_refused_amount=total_refused_amount,
        orders_by_status=orders_by_status,
        orders_by_restaurant=orders_by_restaurant,
    )

