from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ClaimOrder, Restaurant
from app.schemas.domain import DashboardRestaurantSummary, DashboardSummary

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])

TERMINAL_OR_RECOVERED_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}


def as_decimal(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    total_orders = db.scalar(select(func.count(ClaimOrder.id))) or 0
    total_claimed_amount = as_decimal(db.scalar(select(func.sum(ClaimOrder.order_amount))))
    total_recovered_amount = as_decimal(db.scalar(select(func.sum(ClaimOrder.recovered_amount))))
    total_refused_amount = as_decimal(
        db.scalar(select(func.sum(ClaimOrder.order_amount)).where(ClaimOrder.status == "refused"))
    )
    total_pending_amount = as_decimal(
        db.scalar(
            select(func.sum(ClaimOrder.order_amount)).where(ClaimOrder.status.notin_(TERMINAL_OR_RECOVERED_STATUSES))
        )
    )

    status_rows = db.execute(select(ClaimOrder.status, func.count(ClaimOrder.id)).group_by(ClaimOrder.status)).all()
    orders_by_status = {status: count for status, count in status_rows}

    restaurant_rows = db.execute(
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
    ).all()
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

