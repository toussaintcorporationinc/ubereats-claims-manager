from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, ClaimOrder, UberCustomerRefundDispute

OFFICIAL_CLAIM_PAYMENT_RESULT = "payment_confirmed_from_uber_reporting"
OFFICIAL_CUSTOMER_REFUND_PAYMENT_ACTION = "customer_refund.payment_confirmed_from_uber_reporting"


def claim_payment_is_verified(order: Any) -> bool:
    return (
        order.status == "payment_confirmed"
        and order.result == OFFICIAL_CLAIM_PAYMENT_RESULT
        and order.recovered_amount is not None
    )


def verified_claim_recovered_amount(order: Any) -> Decimal | None:
    if not claim_payment_is_verified(order):
        return None
    return Decimal(order.recovered_amount)


def verified_claim_recovered_amount_expression():
    return case(
        (
            and_(
                ClaimOrder.status == "payment_confirmed",
                ClaimOrder.result == OFFICIAL_CLAIM_PAYMENT_RESULT,
            ),
            func.coalesce(ClaimOrder.recovered_amount, Decimal("0")),
        ),
        else_=Decimal("0"),
    )


def verified_customer_refund_ids(
    db: Session,
    disputes: Iterable[UberCustomerRefundDispute],
) -> set[int]:
    dispute_ids = [dispute.id for dispute in disputes if dispute.id is not None]
    if not dispute_ids:
        return set()
    return set(
        db.scalars(
            select(AuditLog.entity_id).where(
                AuditLog.entity_type == "uber_customer_refund_dispute",
                AuditLog.entity_id.in_(dispute_ids),
                AuditLog.action == OFFICIAL_CUSTOMER_REFUND_PAYMENT_ACTION,
            )
        ).all()
    )


def verified_customer_refund_recovered_amount(
    dispute: UberCustomerRefundDispute,
    verified_ids: set[int],
) -> Decimal | None:
    if (
        dispute.id not in verified_ids
        or dispute.status != "payment_confirmed"
        or dispute.recovered_amount is None
    ):
        return None
    return Decimal(dispute.recovered_amount)
