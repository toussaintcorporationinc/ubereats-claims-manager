from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AppealWorkflow,
    ClaimOrder,
    FollowUpTask,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log

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
OPEN_FOLLOWUP_STATUSES = {"pending", "draft_created", "provider_draft_created"}


@dataclass
class UberPaymentApplicationResult:
    applied_transaction_ids: set[int] = field(default_factory=set)
    applied_claim_ids: set[int] = field(default_factory=set)
    applied_dispute_ids: set[int] = field(default_factory=set)
    unmatched_transaction_ids: set[int] = field(default_factory=set)
    conflict_transaction_ids: set[int] = field(default_factory=set)

    def as_dict(self) -> dict[str, int]:
        return {
            "payments_applied_count": len(self.applied_transaction_ids),
            "payment_claims_updated_count": len(self.applied_claim_ids),
            "payment_disputes_updated_count": len(self.applied_dispute_ids),
            "payments_unmatched_count": len(self.unmatched_transaction_ids),
            "payment_conflicts_count": len(self.conflict_transaction_ids),
        }


def apply_official_uber_payments(
    db: Session,
    user: User,
    transactions: list[UberFinancialTransaction],
) -> UberPaymentApplicationResult:
    result = UberPaymentApplicationResult()
    source_transactions = {
        transaction.id: transaction
        for transaction in transactions
        if transaction.id is not None and is_positive_payment(transaction)
    }
    if not source_transactions:
        return result

    restaurant_ids = {transaction.restaurant_id for transaction in source_transactions.values()}
    claims = list(
        db.scalars(select(ClaimOrder).where(ClaimOrder.restaurant_id.in_(restaurant_ids))).all()
    )
    disputes = list(
        db.scalars(
            select(UberCustomerRefundDispute).where(
                UberCustomerRefundDispute.restaurant_id.in_(restaurant_ids)
            )
        ).all()
    )
    snapshots = list(
        db.scalars(
            select(UberOrderSnapshot).where(UberOrderSnapshot.restaurant_id.in_(restaurant_ids))
        ).all()
    )
    positive_transactions = [
        transaction
        for transaction in db.scalars(
            select(UberFinancialTransaction).where(
                UberFinancialTransaction.restaurant_id.in_(restaurant_ids),
                UberFinancialTransaction.amount > 0,
            )
        ).all()
        if is_positive_payment(transaction)
    ]

    snapshot_display_keys = build_snapshot_display_key_index(snapshots)
    transaction_keys = {
        transaction.id: keys_for_transaction(transaction, snapshot_display_keys)
        for transaction in positive_transactions
        if transaction.id is not None
    }
    claims_by_restaurant = group_by_restaurant(claims)
    disputes_by_restaurant = group_by_restaurant(disputes)
    positive_by_restaurant = group_by_restaurant(positive_transactions)

    for transaction in source_transactions.values():
        source_keys = transaction_keys.get(transaction.id, set())
        candidate_claims = [
            claim
            for claim in claims_by_restaurant.get(transaction.restaurant_id, [])
            if source_keys & keys_for_claim(claim)
        ]
        candidate_disputes = [
            dispute
            for dispute in disputes_by_restaurant.get(transaction.restaurant_id, [])
            if source_keys & keys_for_dispute(dispute)
        ]
        linked_claim_ids = {
            dispute.claim_order_id
            for dispute in candidate_disputes
            if dispute.claim_order_id is not None
        }
        claim_ids = {claim.id for claim in candidate_claims} | linked_claim_ids
        if len(claim_ids) > 1 or (not claim_ids and len(candidate_disputes) > 1):
            result.conflict_transaction_ids.add(transaction.id)
            continue

        claim = next((item for item in candidate_claims if item.id in claim_ids), None)
        if claim is None and claim_ids:
            claim = next((item for item in claims if item.id in claim_ids), None)
        if claim is None and not candidate_disputes:
            result.unmatched_transaction_ids.add(transaction.id)
            continue

        related_disputes = [
            dispute
            for dispute in disputes_by_restaurant.get(transaction.restaurant_id, [])
            if (claim is not None and dispute.claim_order_id == claim.id)
            or bool(source_keys & keys_for_dispute(dispute))
        ]
        case_keys = set(source_keys)
        if claim is not None:
            case_keys.update(keys_for_claim(claim))
        for dispute in related_disputes:
            case_keys.update(keys_for_dispute(dispute))

        matched_transactions = [
            item
            for item in positive_by_restaurant.get(transaction.restaurant_id, [])
            if case_keys & transaction_keys.get(item.id, set())
        ]
        recovered_amount = sum((Decimal(item.amount) for item in matched_transactions), Decimal("0"))
        if recovered_amount <= 0 or exceeds_expected_amount(claim, related_disputes, recovered_amount):
            result.conflict_transaction_ids.add(transaction.id)
            continue

        matched_ids = sorted(item.id for item in matched_transactions if item.id is not None)
        if claim is not None:
            apply_payment_to_claim(db, user, claim, recovered_amount, matched_ids)
            result.applied_claim_ids.add(claim.id)
        for dispute in related_disputes:
            apply_payment_to_dispute(db, user, dispute, recovered_amount, matched_ids)
            result.applied_dispute_ids.add(dispute.id)
        result.applied_transaction_ids.add(transaction.id)

    return result


def apply_payment_to_claim(
    db: Session,
    user: User,
    claim: ClaimOrder,
    recovered_amount: Decimal,
    transaction_ids: list[int],
) -> None:
    old_value = {
        "status": claim.status,
        "result": claim.result,
        "recovered_amount": claim.recovered_amount,
        "next_action_at": claim.next_action_at,
    }
    claim.status = "payment_confirmed"
    claim.result = "payment_confirmed_from_uber_reporting"
    claim.recovered_amount = recovered_amount
    claim.next_action_at = None
    claim.updated_at = utc_now()

    now = utc_now()
    followups = db.scalars(
        select(FollowUpTask).where(
            FollowUpTask.order_id == claim.id,
            FollowUpTask.status.in_(OPEN_FOLLOWUP_STATUSES),
        )
    ).all()
    for followup in followups:
        followup.status = "cancelled"
        followup.skipped_at = now
        followup.skipped_by_user_id = user.id
        followup.skip_reason = "Paiement officiel confirme par le relevé Uber"

    workflows = db.scalars(
        select(AppealWorkflow).where(AppealWorkflow.claim_order_id == claim.id)
    ).all()
    for workflow in workflows:
        workflow.status = "payment_confirmed"
        workflow.next_action_at = None
        workflow.next_action_type = None
        workflow.updated_at = now

    add_audit_log(
        db,
        entity_type="claim_order",
        entity_id=claim.id,
        action="claim_order.payment_confirmed_from_uber_reporting",
        user_id=user.id,
        old_value=old_value,
        new_value={
            "status": claim.status,
            "result": claim.result,
            "recovered_amount": recovered_amount,
            "uber_financial_transaction_ids": transaction_ids,
        },
    )


def apply_payment_to_dispute(
    db: Session,
    user: User,
    dispute: UberCustomerRefundDispute,
    recovered_amount: Decimal,
    transaction_ids: list[int],
) -> None:
    old_value = {
        "status": dispute.status,
        "recovered_amount": dispute.recovered_amount,
        "expected_payment_date": dispute.expected_payment_date,
    }
    dispute.status = "payment_confirmed"
    dispute.recovered_amount = recovered_amount
    dispute.expected_payment_date = None
    dispute.last_reviewed_at = utc_now()
    dispute.last_reviewed_by_user_id = user.id
    dispute.updated_at = utc_now()

    workflows = db.scalars(
        select(AppealWorkflow).where(
            AppealWorkflow.customer_refund_dispute_id == dispute.id
        )
    ).all()
    for workflow in workflows:
        workflow.status = "payment_confirmed"
        workflow.next_action_at = None
        workflow.next_action_type = None
        workflow.updated_at = utc_now()

    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund.payment_confirmed_from_uber_reporting",
        user_id=user.id,
        old_value=old_value,
        new_value={
            "status": dispute.status,
            "recovered_amount": recovered_amount,
            "uber_financial_transaction_ids": transaction_ids,
        },
    )


def is_positive_payment(transaction: UberFinancialTransaction) -> bool:
    return (
        normalize_transaction_type(transaction.transaction_type) in PAID_TRANSACTION_TYPES
        and Decimal(transaction.amount) > 0
        and bool(normalize_order_key(transaction.uber_order_id))
    )


def normalize_transaction_type(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_order_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(character for character in str(value).upper() if character.isalnum())
    return normalized or None


def keys_for_claim(claim: ClaimOrder) -> set[str]:
    return normalized_keys(claim.uber_order_number, claim.internal_reference)


def keys_for_dispute(dispute: UberCustomerRefundDispute) -> set[str]:
    return normalized_keys(
        dispute.uber_order_id,
        dispute.display_id,
        dispute.customer_refund_reference,
    )


def keys_for_transaction(
    transaction: UberFinancialTransaction,
    snapshot_display_keys: dict[tuple[int, str, str], set[str]],
) -> set[str]:
    direct_key = normalize_order_key(transaction.uber_order_id)
    if direct_key is None:
        return set()
    keys = {direct_key}
    keys.update(
        snapshot_display_keys.get(
            (transaction.restaurant_id, transaction.uber_store_id, direct_key),
            set(),
        )
    )
    return keys


def build_snapshot_display_key_index(
    snapshots: list[UberOrderSnapshot],
) -> dict[tuple[int, str, str], set[str]]:
    index: dict[tuple[int, str, str], set[str]] = {}
    for snapshot in snapshots:
        order_key = normalize_order_key(snapshot.uber_order_id)
        display_key = normalize_order_key(snapshot.display_id)
        if order_key is None or display_key is None:
            continue
        index.setdefault(
            (snapshot.restaurant_id, snapshot.uber_store_id, order_key),
            set(),
        ).add(display_key)
    return index


def normalized_keys(*values: str | None) -> set[str]:
    return {
        key
        for key in (normalize_order_key(value) for value in values)
        if key is not None
    }


def group_by_restaurant(items: list[object]) -> dict[int, list]:
    grouped: dict[int, list] = {}
    for item in items:
        grouped.setdefault(item.restaurant_id, []).append(item)
    return grouped


def exceeds_expected_amount(
    claim: ClaimOrder | None,
    disputes: list[UberCustomerRefundDispute],
    recovered_amount: Decimal,
) -> bool:
    expected_amounts = [
        Decimal(value)
        for value in [
            claim.order_amount if claim is not None else None,
            *(dispute.customer_refund_amount for dispute in disputes),
        ]
        if value is not None and Decimal(value) > 0
    ]
    if not expected_amounts:
        return False
    return recovered_amount > max(expected_amounts) + Decimal("0.02")
