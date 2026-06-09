from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant
from app.models import (
    ClaimOrder,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReconciliationResult,
    User,
)
from app.services.audit import add_audit_log

PAID_TRANSACTION_TYPES = {"payment", "payout", "compensation", "reimbursement", "adjustment_credit"}
REFUND_TRANSACTION_TYPES = {"refund", "refunded", "refund_adjustment"}
CANCELLED_STATES = {"canceled", "cancelled", "canceled_by_customer", "cancelled_by_customer", "merchant_cancelled"}


class UberReconciliationService:
    def run(self, db: Session, current_user: User) -> dict[str, object]:
        created = 0
        updated = 0
        ignored = 0
        errors: list[str] = []
        snapshots = db.scalars(select(UberOrderSnapshot).order_by(UberOrderSnapshot.id)).all()

        for snapshot in snapshots:
            if not can_access_restaurant(db, current_user, snapshot.restaurant_id):
                ignored += 1
                continue
            if snapshot.current_state.lower() not in CANCELLED_STATES:
                ignored += 1
                continue

            existing_claim = db.scalar(
                select(ClaimOrder).where(
                    ClaimOrder.restaurant_id == snapshot.restaurant_id,
                    ClaimOrder.uber_order_number == snapshot.uber_order_id,
                )
            )
            paid_amount, refunded_amount = self.transaction_totals(db, snapshot)
            result_status, reason, missing_amount = self.classify(snapshot.order_total_amount, paid_amount, refunded_amount)
            if existing_claim is not None:
                result_status = "already_claimed"
                reason = "ClaimOrder already exists for this restaurant and Uber order"
                missing_amount = Decimal("0")

            result = db.scalar(
                select(UberReconciliationResult).where(
                    UberReconciliationResult.restaurant_id == snapshot.restaurant_id,
                    UberReconciliationResult.uber_order_id == snapshot.uber_order_id,
                )
            )
            if result is None:
                result = UberReconciliationResult(
                    restaurant_id=snapshot.restaurant_id,
                    uber_order_id=snapshot.uber_order_id,
                    status=result_status,
                    reason=reason,
                )
                db.add(result)
                created += 1
            else:
                updated += 1

            result.claim_order_id = existing_claim.id if existing_claim else None
            result.status = result_status
            result.reason = reason
            result.order_amount = snapshot.order_total_amount
            result.paid_amount = paid_amount
            result.refunded_amount = refunded_amount
            result.missing_amount = missing_amount
            result.evidence_required = result_status in {"not_compensated", "partially_compensated", "needs_evidence"}

        add_audit_log(
            db,
            entity_type="uber_reconciliation",
            entity_id=current_user.id,
            action="run_uber_reconciliation",
            user_id=current_user.id,
            new_value={"results_created": created, "results_updated": updated, "ignored_orders": ignored},
        )
        db.commit()
        return {"results_created": created, "results_updated": updated, "ignored_orders": ignored, "errors": errors}

    def transaction_totals(self, db: Session, snapshot: UberOrderSnapshot) -> tuple[Decimal, Decimal]:
        rows = db.execute(
            select(UberFinancialTransaction.transaction_type, func.coalesce(func.sum(UberFinancialTransaction.amount), 0))
            .where(
                UberFinancialTransaction.restaurant_id == snapshot.restaurant_id,
                UberFinancialTransaction.uber_order_id == snapshot.uber_order_id,
            )
            .group_by(UberFinancialTransaction.transaction_type)
        ).all()
        paid = Decimal("0")
        refunded = Decimal("0")
        for transaction_type, amount in rows:
            normalized_type = str(transaction_type).strip().lower()
            numeric_amount = Decimal(str(amount))
            if normalized_type in PAID_TRANSACTION_TYPES:
                paid += numeric_amount
            elif normalized_type in REFUND_TRANSACTION_TYPES:
                refunded += numeric_amount
        return paid, refunded

    def classify(
        self,
        order_amount: Decimal | None,
        paid_amount: Decimal,
        refunded_amount: Decimal,
    ) -> tuple[str, str, Decimal | None]:
        if order_amount is None:
            return "manual_review", "Missing order amount in Uber snapshot", None
        compensated_amount = paid_amount + refunded_amount
        missing_amount = order_amount - compensated_amount
        if missing_amount <= Decimal("0"):
            return "compensated", "Order appears compensated by imported financial transactions", Decimal("0")
        if compensated_amount > Decimal("0"):
            return "partially_compensated", "Order has partial financial compensation", missing_amount
        return "not_compensated", "Cancelled order has no matching compensation transaction", missing_amount

    def create_claim_order_from_result(
        self,
        db: Session,
        current_user: User,
        result_id: int,
    ) -> ClaimOrder:
        result = db.get(UberReconciliationResult, result_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")
        if not can_access_restaurant(db, current_user, result.restaurant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")
        existing_claim = db.scalar(
            select(ClaimOrder).where(
                ClaimOrder.restaurant_id == result.restaurant_id,
                ClaimOrder.uber_order_number == result.uber_order_id,
            )
        )
        if existing_claim is not None:
            result.claim_order_id = existing_claim.id
            result.status = "already_claimed"
            db.commit()
            return existing_claim
        if result.status not in {"not_compensated", "partially_compensated", "needs_evidence"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Result is not eligible for ClaimOrder creation")

        order = ClaimOrder(
            restaurant_id=result.restaurant_id,
            uber_order_number=result.uber_order_id,
            order_amount=result.missing_amount or result.order_amount,
            currency="EUR",
            status="missing_evidence",
            loss_type="uber_reconciliation",
            notes="Created from Uber reconciliation result. Evidence still required before claim.",
        )
        db.add(order)
        db.flush()
        result.claim_order_id = order.id
        result.status = "already_claimed"
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=order.id,
            action="create_from_uber_reconciliation",
            user_id=current_user.id,
            new_value={"uber_order_id": result.uber_order_id, "result_id": result.id},
        )
        db.commit()
        db.refresh(order)
        return order
