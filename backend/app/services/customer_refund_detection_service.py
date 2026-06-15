import json
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.models import (
    ClaimOrder,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    User,
)
from app.services.audit import add_audit_log
from app.services.customer_refund_evidence_policy_service import evidence_policy_for_dispute
from app.services.customer_refund_dispute_service import ensure_evidence_requirements, recalculate_dispute_evidence

NEGATIVE_TRANSACTION_TYPES = {
    "refund",
    "customer_refund",
    "chargeback",
    "adjustment_negative",
    "adjustment negative",
    "deduction",
    "clawback",
    "eater_refund",
    "order_error",
    "order error",
    "order_error_adjustment",
    "order error adjustment",
}

CLASSIFICATION_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "order_not_received",
        "customer_reported_not_received",
        (
            "not received",
            "order not received",
            "never received",
            "customer did not receive",
            "eater did not receive",
            "non recu",
            "commande non recue",
            "client non livre",
            "livraison non recue",
            "pas recu",
        ),
    ),
    (
        "missing_item",
        "customer_reported_missing_item",
        (
            "missing item",
            "missing items",
            "item missing",
            "missing article",
            "article missing",
            "article manquant",
            "articles manquants",
            "element manquant",
            "produit manquant",
            "produits manquants",
            "il manque",
            "manque un article",
        ),
    ),
    (
        "incorrect_item",
        "customer_reported_wrong_item",
        (
            "wrong item",
            "incorrect item",
            "wrong order",
            "mauvaise commande",
            "mauvais article",
            "article incorrect",
            "produit incorrect",
        ),
    ),
    (
        "quality_issue",
        "customer_reported_quality_issue",
        (
            "quality",
            "qualite",
            "food issue",
            "probleme qualite",
        ),
    ),
    (
        "order_error_adjustment",
        "uber_adjustment_order_error",
        (
            "order error",
            "adjustment",
            "ajustement",
            "erreur de commande",
            "ajustement negatif",
            "adjustment negative",
            "adjustment_negative",
        ),
    ),
    (
        "chargeback",
        "refund_without_sufficient_proof",
        ("chargeback", "clawback"),
    ),
    (
        "customer_refund",
        "refund_without_sufficient_proof",
        ("refund", "remboursement", "eater refund", "eater_refund", "customer refund"),
    ),
)


@dataclass(frozen=True)
class CustomerRefundDetectionResult:
    detected_count: int
    needs_evidence_count: int
    manual_review_count: int
    total_deducted_amount: Decimal
    errors: list[str]


def detect_customer_refund_disputes(
    db: Session,
    current_user: User,
    *,
    restaurant_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> CustomerRefundDetectionResult:
    statement = select(UberFinancialTransaction).order_by(UberFinancialTransaction.id)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        if not can_access_restaurant(db, current_user, restaurant_id):
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")
        statement = statement.where(UberFinancialTransaction.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return CustomerRefundDetectionResult(0, 0, 0, Decimal("0"), [])
        statement = statement.where(UberFinancialTransaction.restaurant_id.in_(accessible_ids))
    if date_from is not None:
        statement = statement.where(UberFinancialTransaction.transaction_date >= date_from)
    if date_to is not None:
        statement = statement.where(UberFinancialTransaction.transaction_date <= date_to)

    detected_count = 0
    needs_evidence_count = 0
    manual_review_count = 0
    total_deducted_amount = Decimal("0")
    errors: list[str] = []

    for transaction in db.scalars(statement).all():
        try:
            if not is_disputable_transaction(transaction):
                continue
            existing = db.scalar(
                select(UberCustomerRefundDispute).where(
                    UberCustomerRefundDispute.financial_transaction_id == transaction.id
                )
            )
            if existing is not None:
                continue
            dispute_type, reason = classify_transaction(transaction)
            snapshot = find_snapshot_for_transaction(db, transaction)
            claim_order = find_claim_order_for_transaction(db, transaction, snapshot)
            amount = abs(Decimal(str(transaction.amount)))
            dispute = UberCustomerRefundDispute(
                restaurant_id=transaction.restaurant_id,
                uber_store_id=transaction.uber_store_id,
                uber_order_id=transaction.uber_order_id,
                display_id=snapshot.display_id if snapshot else None,
                claim_order_id=claim_order.id if claim_order else None,
                financial_transaction_id=transaction.id,
                customer_refund_reference=transaction.payout_reference,
                dispute_type=dispute_type,
                reason=reason,
                status="manual_review" if dispute_type == "unknown" else "needs_evidence",
                customer_refund_amount=amount,
                order_amount=snapshot.order_total_amount if snapshot else claim_order.order_amount if claim_order else None,
                currency=transaction.currency,
                deducted_at=transaction.transaction_date,
                order_date=snapshot.placed_at.date() if snapshot and snapshot.placed_at else None,
                evidence_required=True,
                evidence_status="manual_review" if dispute_type == "unknown" else "missing",
                raw_payload_json=transaction.raw_payload_json,
                created_by_user_id=current_user.id,
                notes=build_detection_note(transaction, dispute_type, reason),
            )
            db.add(dispute)
            db.flush()
            ensure_evidence_requirements(db, dispute, evidence_policy_for_dispute(dispute.dispute_type).required)
            recalculate_dispute_evidence(db, current_user, dispute, create_tasks=True)
            add_audit_log(
                db,
                entity_type="uber_customer_refund_dispute",
                entity_id=dispute.id,
                action="customer_refund_dispute.created",
                user_id=current_user.id,
                new_value={
                    "financial_transaction_id": transaction.id,
                    "dispute_type": dispute.dispute_type,
                    "reason": dispute.reason,
                    "amount": dispute.customer_refund_amount,
                },
            )
            detected_count += 1
            if dispute.evidence_status == "manual_review":
                manual_review_count += 1
            elif dispute.evidence_status != "complete":
                needs_evidence_count += 1
            total_deducted_amount += amount
        except Exception as exc:  # pragma: no cover - defensive batch path
            errors.append(f"transaction {transaction.id}: {exc}")

    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=0,
        action="customer_refund_dispute.detect",
        user_id=current_user.id,
        new_value={
            "restaurant_id": restaurant_id,
            "date_from": date_from,
            "date_to": date_to,
            "detected_count": detected_count,
            "needs_evidence_count": needs_evidence_count,
            "manual_review_count": manual_review_count,
            "total_deducted_amount": total_deducted_amount,
            "errors": errors,
        },
    )
    db.commit()
    return CustomerRefundDetectionResult(
        detected_count=detected_count,
        needs_evidence_count=needs_evidence_count,
        manual_review_count=manual_review_count,
        total_deducted_amount=total_deducted_amount,
        errors=errors,
    )


def is_disputable_transaction(transaction: UberFinancialTransaction) -> bool:
    amount = Decimal(str(transaction.amount))
    if amount >= 0:
        return False
    transaction_type = normalize_text(transaction.transaction_type)
    if any(marker in transaction_type for marker in NEGATIVE_TRANSACTION_TYPES):
        return True
    return True


def classify_transaction(transaction: UberFinancialTransaction) -> tuple[str, str]:
    text = build_transaction_search_text(transaction)
    for dispute_type, reason, needles in CLASSIFICATION_RULES:
        if contains_any(text, needles):
            return dispute_type, reason
    return "unknown", "unknown_reason"


def find_snapshot_for_transaction(db: Session, transaction: UberFinancialTransaction) -> UberOrderSnapshot | None:
    if not transaction.uber_order_id:
        return None
    return db.scalar(
        select(UberOrderSnapshot)
        .where(
            UberOrderSnapshot.restaurant_id == transaction.restaurant_id,
            UberOrderSnapshot.uber_store_id == transaction.uber_store_id,
            UberOrderSnapshot.uber_order_id == transaction.uber_order_id,
        )
        .order_by(UberOrderSnapshot.id.desc())
    )


def find_claim_order_for_transaction(
    db: Session,
    transaction: UberFinancialTransaction,
    snapshot: UberOrderSnapshot | None,
) -> ClaimOrder | None:
    candidates = [value for value in (transaction.uber_order_id, snapshot.display_id if snapshot else None) if value]
    if not candidates:
        return None
    return db.scalar(
        select(ClaimOrder)
        .where(
            ClaimOrder.restaurant_id == transaction.restaurant_id,
            ClaimOrder.uber_order_number.in_(candidates),
        )
        .order_by(ClaimOrder.id.desc())
    )


def build_detection_note(transaction: UberFinancialTransaction, dispute_type: str, reason: str) -> str:
    return (
        f"Deduction Uber detectee depuis transaction #{transaction.id}. "
        f"Type={dispute_type}, reason={reason}, montant={transaction.amount} {transaction.currency}."
    )


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_text = "".join(character for character in normalized if not unicodedata.combining(character))
    return " ".join(ascii_text.replace("_", " ").split())


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(normalize_text(needle) in text for needle in needles)


def build_transaction_search_text(transaction: UberFinancialTransaction) -> str:
    values = [
        transaction.transaction_type or "",
        transaction.payout_reference or "",
        *flatten_payload_text(transaction.raw_payload_json or {}),
        json.dumps(transaction.raw_payload_json or {}, ensure_ascii=False),
    ]
    return normalize_text(" ".join(str(value) for value in values if value not in {None, ""}))


def flatten_payload_text(value: object) -> list[str]:
    if isinstance(value, dict):
        pieces: list[str] = []
        for key, nested_value in value.items():
            pieces.append(str(key))
            pieces.extend(flatten_payload_text(nested_value))
        return pieces
    if isinstance(value, list):
        pieces = []
        for item in value:
            pieces.extend(flatten_payload_text(item))
        return pieces
    if value is None:
        return []
    return [str(value)]
