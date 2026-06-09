from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import (
    ClaimOrder,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReconciliationResult,
    UberReconciliationRun,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.claim_validation_service import get_claim_validation_gaps
from app.services.uber_reporting_import_service import is_cancelled_order_status

PAID_TRANSACTION_TYPES = {
    "payment",
    "payout",
    "merchant_payment",
    "compensation",
    "adjustment_positive",
    "adjustment_credit",
    "reimbursement",
    "paid",
    "net_payout",
}
REFUND_TRANSACTION_TYPES = {
    "refund",
    "chargeback",
    "adjustment_negative",
    "refund_adjustment",
    "deduction",
    "clawback",
    "eater_refund",
    "refunded",
}
FINAL_CLAIM_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}
ELIGIBLE_RESULT_STATUSES = {"not_compensated", "partially_compensated", "needs_evidence"}


@dataclass
class TransactionAnalysis:
    transactions: list[UberFinancialTransaction]
    paid_amount: Decimal
    refunded_amount: Decimal
    has_unknown_critical_type: bool
    has_conflict: bool


class UberReconciliationService:
    def run(
        self,
        db: Session,
        current_user: User,
        *,
        restaurant_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        response = self.run_reconciliation(
            db,
            current_user,
            restaurant_id=restaurant_id,
            date_from=date_from,
            date_to=date_to,
            dry_run=dry_run,
        )
        return response

    def run_reconciliation(
        self,
        db: Session,
        current_user: User,
        *,
        restaurant_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        settings = get_settings()
        today = date.today()
        resolved_date_to = date_to or today
        resolved_date_from = date_from or (resolved_date_to - timedelta(days=settings.uber_reconciliation_default_lookback_days))
        if resolved_date_from > resolved_date_to:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from must be before date_to")
        if restaurant_id is not None and not can_access_restaurant(db, current_user, restaurant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")

        run = UberReconciliationRun(
            created_by_user_id=current_user.id,
            restaurant_id=restaurant_id,
            date_from=resolved_date_from,
            date_to=resolved_date_to,
            status="running",
        )
        db.add(run)
        db.flush()

        snapshots = self._snapshots_for_run(db, current_user, restaurant_id, resolved_date_from, resolved_date_to)
        if len(snapshots) > settings.uber_reconciliation_max_results:
            run.status = "failed"
            run.error_message = "Too many snapshots to reconcile. Add filters and retry."
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=run.error_message)

        errors: list[str] = []
        counts = {
            "total_orders_analyzed": 0,
            "canceled_orders_count": 0,
            "compensated_count": 0,
            "not_compensated_count": 0,
            "partially_compensated_count": 0,
            "already_claimed_count": 0,
            "needs_evidence_count": 0,
            "manual_review_count": 0,
        }
        total_claimable_amount = Decimal("0")
        total_missing_amount = Decimal("0")

        for snapshot in snapshots:
            counts["total_orders_analyzed"] += 1
            result_payload = self.analyze_order_snapshot(db, snapshot)
            if result_payload["is_cancelled"]:
                counts["canceled_orders_count"] += 1
            if result_payload["status"] == "ignored":
                continue

            result_status = str(result_payload["status"])
            count_key = {
                "compensated": "compensated_count",
                "not_compensated": "not_compensated_count",
                "partially_compensated": "partially_compensated_count",
                "already_claimed": "already_claimed_count",
                "needs_evidence": "needs_evidence_count",
                "manual_review": "manual_review_count",
            }.get(result_status)
            if count_key:
                counts[count_key] += 1

            missing_amount = result_payload["missing_amount"]
            if isinstance(missing_amount, Decimal):
                total_missing_amount += missing_amount
                if result_status in ELIGIBLE_RESULT_STATUSES:
                    total_claimable_amount += missing_amount

            if not dry_run:
                self.build_reconciliation_result(db, run, snapshot, result_payload)

        run.status = "completed"
        run.completed_at = utc_now()
        for field, value in counts.items():
            setattr(run, field, value)
        run.total_claimable_amount = total_claimable_amount
        run.total_missing_amount = total_missing_amount
        add_audit_log(
            db,
            entity_type="uber_reconciliation_run",
            entity_id=run.id,
            action="run_uber_reconciliation",
            user_id=current_user.id,
            new_value={
                "restaurant_id": restaurant_id,
                "date_from": resolved_date_from,
                "date_to": resolved_date_to,
                "dry_run": dry_run,
                **counts,
                "total_missing_amount": total_missing_amount,
            },
        )
        db.commit()
        return {
            "run_id": run.id,
            "status": run.status,
            **counts,
            "total_claimable_amount": run.total_claimable_amount,
            "total_missing_amount": run.total_missing_amount,
            "errors": errors,
        }

    def analyze_order_snapshot(self, db: Session, snapshot: UberOrderSnapshot) -> dict[str, Any]:
        is_cancelled = snapshot.canceled_at is not None or is_cancelled_order_status(snapshot.current_state)
        if not is_cancelled:
            return self._analysis_payload(snapshot, "ignored", "not_cancelled", is_cancelled=False)

        if snapshot.order_total_amount is None:
            return self._analysis_payload(snapshot, "manual_review", "missing_order_amount", is_cancelled=True)

        transaction_analysis = self.find_matching_transactions(db, snapshot)
        existing_claim = self.detect_existing_claim_order(db, snapshot)
        paid_amount = transaction_analysis.paid_amount
        refunded_amount = transaction_analysis.refunded_amount
        tolerance = Decimal(str(get_settings().uber_reconciliation_amount_tolerance))
        min_missing = Decimal(str(get_settings().uber_reconciliation_min_missing_amount))
        missing_amount = max(Decimal(snapshot.order_total_amount) - paid_amount, Decimal("0"))

        result_status = "manual_review"
        reason = "manual_review"
        confidence = Decimal("0.75")
        if transaction_analysis.has_conflict:
            reason = "transaction_conflict"
            confidence = Decimal("0.40")
        elif transaction_analysis.has_unknown_critical_type:
            reason = "transaction_conflict"
            confidence = Decimal("0.50")
        elif missing_amount <= tolerance or missing_amount < min_missing:
            result_status = "compensated"
            reason = "canceled_payment_found" if paid_amount > 0 else "below_missing_amount_threshold"
            missing_amount = Decimal("0")
            confidence = Decimal("0.95")
        elif paid_amount == 0:
            result_status = "not_compensated"
            reason = "canceled_no_payment_found"
            confidence = Decimal("0.90")
        elif paid_amount > 0:
            result_status = "partially_compensated"
            reason = "canceled_partial_payment"
            confidence = Decimal("0.85")

        financial_status = result_status
        evidence_required = result_status in {"not_compensated", "partially_compensated"}
        claim_order_id = None
        if existing_claim is not None:
            claim_order_id = existing_claim.id
            if existing_claim.status in {"refused", "closed"} and missing_amount > tolerance:
                result_status = "manual_review"
                reason = "existing_closed_or_refused_claim"
                evidence_required = True
            else:
                result_status = "already_claimed"
                reason = "existing_claim_order"
                evidence_required = bool(get_claim_validation_gaps(db, existing_claim)[0])

        return self._analysis_payload(
            snapshot,
            result_status,
            reason,
            is_cancelled=True,
            financial_status=financial_status,
            claim_order_id=claim_order_id,
            paid_amount=paid_amount,
            refunded_amount=refunded_amount,
            missing_amount=missing_amount,
            evidence_required=evidence_required,
            confidence_score=confidence,
            transactions=transaction_analysis.transactions,
        )

    def find_matching_transactions(self, db: Session, snapshot: UberOrderSnapshot) -> TransactionAnalysis:
        transactions = list(
            db.scalars(
                select(UberFinancialTransaction).where(
                    UberFinancialTransaction.restaurant_id == snapshot.restaurant_id,
                    UberFinancialTransaction.uber_store_id == snapshot.uber_store_id,
                    UberFinancialTransaction.uber_order_id == snapshot.uber_order_id,
                )
            ).all()
        )
        paid_amount, refunded_amount = self.calculate_paid_amount(transactions)
        unknown_critical = False
        has_positive = False
        has_negative = False
        for transaction in transactions:
            normalized_type = transaction.transaction_type.strip().lower()
            amount = Decimal(transaction.amount)
            if normalized_type not in PAID_TRANSACTION_TYPES | REFUND_TRANSACTION_TYPES:
                unknown_critical = True
            has_positive = has_positive or amount > 0
            has_negative = has_negative or amount < 0
        return TransactionAnalysis(
            transactions=transactions,
            paid_amount=paid_amount,
            refunded_amount=refunded_amount,
            has_unknown_critical_type=unknown_critical,
            has_conflict=has_positive and has_negative and paid_amount == Decimal("0"),
        )

    def calculate_paid_amount(self, transactions: list[UberFinancialTransaction]) -> tuple[Decimal, Decimal]:
        paid = Decimal("0")
        refunded = Decimal("0")
        for transaction in transactions:
            normalized_type = transaction.transaction_type.strip().lower()
            amount = Decimal(transaction.amount)
            if normalized_type in PAID_TRANSACTION_TYPES and amount > 0:
                paid += amount
            elif normalized_type in REFUND_TRANSACTION_TYPES:
                refunded += abs(amount)
        return paid, refunded

    def detect_existing_claim_order(self, db: Session, snapshot: UberOrderSnapshot) -> ClaimOrder | None:
        candidates = [snapshot.uber_order_id]
        if snapshot.display_id:
            candidates.append(snapshot.display_id)
        return db.scalar(
            select(ClaimOrder).where(
                ClaimOrder.restaurant_id == snapshot.restaurant_id,
                ClaimOrder.uber_order_number.in_(candidates),
            )
        )

    def build_reconciliation_result(
        self,
        db: Session,
        run: UberReconciliationRun,
        snapshot: UberOrderSnapshot,
        payload: dict[str, Any],
    ) -> UberReconciliationResult:
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
                status=payload["status"],
                financial_status=payload["financial_status"],
                reason=payload["reason"],
            )
            db.add(result)

        transactions: list[UberFinancialTransaction] = payload["transactions"]
        result.run_id = run.id
        result.display_id = snapshot.display_id
        result.claim_order_id = payload["claim_order_id"]
        result.status = payload["status"]
        result.financial_status = payload["financial_status"]
        result.reason = payload["reason"]
        result.order_amount = snapshot.order_total_amount
        result.paid_amount = payload["paid_amount"]
        result.refunded_amount = payload["refunded_amount"]
        result.missing_amount = payload["missing_amount"]
        result.currency = snapshot.currency
        result.evidence_required = payload["evidence_required"]
        result.confidence_score = payload["confidence_score"]
        result.matched_transaction_ids_json = [transaction.id for transaction in transactions]
        result.matched_snapshot_id = snapshot.id
        return result

    def create_claim_order_from_result(
        self,
        db: Session,
        current_user: User,
        result_id: int,
    ) -> ClaimOrder:
        result = self._get_result_for_user(db, current_user, result_id)
        if result.claim_order_id is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reconciliation result already has a ClaimOrder")
        if result.status in {"compensated", "already_claimed", "ignored", "manual_review"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Result is not eligible for ClaimOrder creation")

        existing_claim = self._existing_claim_for_result(db, result)
        if existing_claim is not None:
            result.claim_order_id = existing_claim.id
            result.status = "already_claimed"
            db.commit()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ClaimOrder already exists for this Uber order")

        order = self._build_claim_order_from_result(result)
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
            new_value={
                "run_id": result.run_id,
                "result_id": result.id,
                "reason": result.reason,
                "uber_order_id": result.uber_order_id,
                "missing_amount": result.missing_amount,
            },
        )
        db.commit()
        db.refresh(order)
        return order

    def bulk_create_claim_orders_from_results(
        self,
        db: Session,
        current_user: User,
        result_ids: list[int],
    ) -> dict[str, object]:
        created_order_ids: list[int] = []
        errors: list[str] = []
        skipped = 0
        for result_id in result_ids:
            try:
                order = self.create_claim_order_from_result(db, current_user, result_id)
                created_order_ids.append(order.id)
            except HTTPException as exc:
                skipped += 1
                errors.append(f"{result_id}: {exc.detail}")
        return {
            "created_count": len(created_order_ids),
            "skipped_count": skipped,
            "errors": errors,
            "created_order_ids": created_order_ids,
        }

    def ignore_result(self, db: Session, current_user: User, result_id: int, reason: str) -> UberReconciliationResult:
        result = self._get_result_for_user(db, current_user, result_id)
        old_status = result.status
        result.status = "ignored"
        result.reason = reason
        result.evidence_required = False
        add_audit_log(
            db,
            entity_type="uber_reconciliation_result",
            entity_id=result.id,
            action="ignore_uber_reconciliation_result",
            user_id=current_user.id,
            old_value={"status": old_status},
            new_value={"status": "ignored", "reason": reason},
        )
        db.commit()
        db.refresh(result)
        return result

    def _snapshots_for_run(
        self,
        db: Session,
        current_user: User,
        restaurant_id: int | None,
        date_from: date,
        date_to: date,
    ) -> list[UberOrderSnapshot]:
        statement = select(UberOrderSnapshot)
        accessible_ids = get_accessible_restaurant_ids(db, current_user)
        if restaurant_id is not None:
            statement = statement.where(UberOrderSnapshot.restaurant_id == restaurant_id)
        elif accessible_ids is not None:
            statement = statement.where(UberOrderSnapshot.restaurant_id.in_(accessible_ids))

        start_dt = datetime.combine(date_from, datetime.min.time())
        end_dt = datetime.combine(date_to, datetime.max.time())
        statement = statement.where(
            and_(
                (UberOrderSnapshot.placed_at.is_(None)) | (UberOrderSnapshot.placed_at >= start_dt),
                (UberOrderSnapshot.placed_at.is_(None)) | (UberOrderSnapshot.placed_at <= end_dt),
            )
        )
        return list(db.scalars(statement.order_by(UberOrderSnapshot.id)).all())

    def _analysis_payload(
        self,
        snapshot: UberOrderSnapshot,
        status_value: str,
        reason: str,
        *,
        is_cancelled: bool,
        claim_order_id: int | None = None,
        paid_amount: Decimal = Decimal("0"),
        refunded_amount: Decimal = Decimal("0"),
        missing_amount: Decimal | None = None,
        evidence_required: bool = False,
        confidence_score: Decimal | None = None,
        transactions: list[UberFinancialTransaction] | None = None,
        financial_status: str | None = None,
    ) -> dict[str, Any]:
        return {
            "snapshot": snapshot,
            "status": status_value,
            "financial_status": financial_status or ("not_cancelled" if reason == "not_cancelled" else status_value),
            "reason": reason,
            "is_cancelled": is_cancelled,
            "claim_order_id": claim_order_id,
            "paid_amount": paid_amount,
            "refunded_amount": refunded_amount,
            "missing_amount": missing_amount,
            "evidence_required": evidence_required,
            "confidence_score": confidence_score,
            "transactions": transactions or [],
        }

    def _get_result_for_user(self, db: Session, current_user: User, result_id: int) -> UberReconciliationResult:
        result = db.get(UberReconciliationResult, result_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")
        if not can_access_restaurant(db, current_user, result.restaurant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")
        return result

    def _existing_claim_for_result(self, db: Session, result: UberReconciliationResult) -> ClaimOrder | None:
        candidates = [result.uber_order_id]
        if result.display_id:
            candidates.append(result.display_id)
        return db.scalar(
            select(ClaimOrder).where(
                ClaimOrder.restaurant_id == result.restaurant_id,
                ClaimOrder.uber_order_number.in_(candidates),
            )
        )

    def _build_claim_order_from_result(self, result: UberReconciliationResult) -> ClaimOrder:
        amount = result.missing_amount or result.order_amount
        note = (
            f"Cree depuis reconciliation Uber run #{result.run_id}, raison {result.reason}, "
            f"montant commande {result.order_amount}, paye {result.paid_amount}, manquant {result.missing_amount}."
        )
        return ClaimOrder(
            restaurant_id=result.restaurant_id,
            uber_order_number=result.display_id or result.uber_order_id,
            order_amount=amount,
            currency=result.currency,
            status="missing_evidence",
            loss_type="uber_reconciliation",
            notes=note,
        )
