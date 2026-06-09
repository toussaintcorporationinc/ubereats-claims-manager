from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order
from app.models import (
    ClaimOrder,
    CustomerRefundDisputeReview,
    EmailAccount,
    InboundEmailMessage,
    UberCustomerRefundDispute,
    User,
)
from app.models.domain import utc_now
from app.schemas.domain import CustomerRefundDisputeReviewCreate
from app.services.audit import add_audit_log
from app.services.customer_refund_dispute_service import recalculate_dispute_evidence

PROTECTED_DISPUTE_STATUSES = {"payment_confirmed", "ignored"}
REVIEW_STATUS_TRANSITIONS = {
    "accepted": "accepted",
    "payment_to_verify": "payment_to_verify",
    "payment_confirmed": "payment_confirmed",
    "refused": "refused",
    "evidence_requested": "needs_evidence",
    "information_requested": "manual_review",
    "followup_needed": "manual_review",
    "ignored": "ignored",
    "manual_review": "manual_review",
}
CLAIM_ORDER_STATUS_TRANSITIONS = {
    "accepted": "accepted",
    "payment_to_verify": "payment_to_verify",
    "payment_confirmed": "payment_confirmed",
    "refused": "refused",
    "evidence_requested": "manual_review",
    "information_requested": "manual_review",
    "followup_needed": "manual_review",
    "manual_review": "manual_review",
}


@dataclass(frozen=True)
class CustomerRefundReviewError(Exception):
    message: str
    status_code: int


def create_customer_refund_review(
    db: Session,
    *,
    dispute: UberCustomerRefundDispute,
    user: User,
    payload: CustomerRefundDisputeReviewCreate,
) -> CustomerRefundDisputeReview:
    previous_dispute_status = dispute.status
    if previous_dispute_status in PROTECTED_DISPUTE_STATUSES:
        raise CustomerRefundReviewError("Protected customer refund dispute status cannot be changed", 409)

    inbound_message = resolve_inbound_message(db, dispute=dispute, user=user, inbound_message_id=payload.inbound_message_id)
    claim_order = db.get(ClaimOrder, dispute.claim_order_id) if dispute.claim_order_id is not None else None
    previous_claim_order_status = claim_order.status if claim_order is not None else None

    new_dispute_status = REVIEW_STATUS_TRANSITIONS[payload.review_type]
    new_claim_order_status = (
        CLAIM_ORDER_STATUS_TRANSITIONS[payload.review_type]
        if claim_order is not None and payload.review_type in CLAIM_ORDER_STATUS_TRANSITIONS
        else previous_claim_order_status
    )

    review = CustomerRefundDisputeReview(
        dispute_id=dispute.id,
        inbound_message_id=inbound_message.id if inbound_message else None,
        reviewed_by_user_id=user.id,
        review_type=payload.review_type,
        previous_dispute_status=previous_dispute_status,
        new_dispute_status=new_dispute_status,
        previous_claim_order_status=previous_claim_order_status,
        new_claim_order_status=new_claim_order_status,
        recovered_amount=payload.recovered_amount,
        expected_payment_date=payload.expected_payment_date,
        refusal_reason=payload.refusal_reason,
        evidence_requested=True if payload.review_type == "evidence_requested" else payload.evidence_requested,
        notes=payload.notes,
    )
    db.add(review)

    apply_dispute_transition(db, dispute, user, payload, new_dispute_status)
    if claim_order is not None and payload.review_type != "ignored":
        apply_claim_order_transition(claim_order, payload, new_claim_order_status)
    review.new_dispute_status = dispute.status
    review.new_claim_order_status = claim_order.status if claim_order is not None else None

    if inbound_message is not None:
        inbound_message.review_status = "ignored" if payload.review_type == "ignored" else "reviewed"
        inbound_message.reviewed_at = utc_now()
        inbound_message.reviewed_by_user_id = user.id
        inbound_message.updated_at = utc_now()

    dispute.last_reviewed_at = utc_now()
    dispute.last_reviewed_by_user_id = user.id
    dispute.updated_at = utc_now()

    db.flush()
    add_review_audit_logs(
        db,
        review=review,
        dispute=dispute,
        user=user,
        inbound_message=inbound_message,
        previous_dispute_status=previous_dispute_status,
        previous_claim_order_status=previous_claim_order_status,
        claim_order=claim_order,
    )
    return review


def apply_dispute_transition(
    db: Session,
    dispute: UberCustomerRefundDispute,
    user: User,
    payload: CustomerRefundDisputeReviewCreate,
    new_status: str,
) -> None:
    dispute.status = new_status
    if payload.recovered_amount is not None:
        dispute.recovered_amount = payload.recovered_amount
    if payload.expected_payment_date is not None:
        dispute.expected_payment_date = payload.expected_payment_date
    if payload.review_type == "ignored":
        dispute.ignored_at = utc_now()
        dispute.ignored_by_user_id = user.id
        dispute.ignore_reason = payload.notes or payload.refusal_reason or "Ignored after customer refund review"
    if payload.review_type == "evidence_requested":
        recalculate_dispute_evidence(db, user, dispute, create_tasks=True)
        if dispute.evidence_status in {"missing", "partial", "manual_review"}:
            dispute.status = "needs_evidence"
        else:
            dispute.status = "evidence_ready"


def apply_claim_order_transition(
    claim_order: ClaimOrder,
    payload: CustomerRefundDisputeReviewCreate,
    new_status: str | None,
) -> None:
    if new_status is None:
        return
    claim_order.status = new_status
    claim_order.result = payload.review_type
    if payload.recovered_amount is not None:
        claim_order.recovered_amount = payload.recovered_amount
    claim_order.updated_at = utc_now()


def resolve_inbound_message(
    db: Session,
    *,
    dispute: UberCustomerRefundDispute,
    user: User,
    inbound_message_id: int | None,
) -> InboundEmailMessage | None:
    if inbound_message_id is None:
        return None
    inbound_message = db.get(InboundEmailMessage, inbound_message_id)
    if inbound_message is None:
        raise CustomerRefundReviewError("Inbound message not found", 404)
    if inbound_message.order_id is not None:
        order = db.get(ClaimOrder, inbound_message.order_id)
        if order is None:
            raise CustomerRefundReviewError("Linked inbound message order not found", 404)
        ensure_can_access_order(db, user, order)
        if order.restaurant_id != dispute.restaurant_id:
            raise CustomerRefundReviewError("Inbound message is linked to another restaurant", 409)
        if dispute.claim_order_id is not None and order.id != dispute.claim_order_id:
            raise CustomerRefundReviewError("Inbound message is linked to another order", 409)
        return inbound_message

    if user.role != "owner" and not user_owns_message_account(db, user, inbound_message):
        raise CustomerRefundReviewError("Inbound message access denied", 403)

    if dispute.claim_order_id is not None:
        inbound_message.order_id = dispute.claim_order_id
        inbound_message.match_status = "linked"
        inbound_message.match_reason = "manual_link"
        inbound_message.updated_at = utc_now()
    return inbound_message


def user_owns_message_account(db: Session, user: User, inbound_message: InboundEmailMessage) -> bool:
    return (
        db.scalar(
            select(EmailAccount.id).where(
                EmailAccount.id == inbound_message.email_account_id,
                EmailAccount.user_id == user.id,
            )
        )
        is not None
    )


def add_review_audit_logs(
    db: Session,
    *,
    review: CustomerRefundDisputeReview,
    dispute: UberCustomerRefundDispute,
    user: User,
    inbound_message: InboundEmailMessage | None,
    previous_dispute_status: str,
    previous_claim_order_status: str | None,
    claim_order: ClaimOrder | None,
) -> None:
    add_audit_log(
        db,
        entity_type="customer_refund_dispute_review",
        entity_id=review.id,
        action="customer_refund_dispute.review_created",
        user_id=user.id,
        new_value={
            "dispute_id": dispute.id,
            "inbound_message_id": review.inbound_message_id,
            "review_type": review.review_type,
            "previous_dispute_status": previous_dispute_status,
            "new_dispute_status": dispute.status,
        },
    )
    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund_dispute.status_changed_from_review",
        user_id=user.id,
        old_value={"status": previous_dispute_status},
        new_value={"status": dispute.status, "review_id": review.id, "review_type": review.review_type},
    )
    if claim_order is not None and previous_claim_order_status != claim_order.status:
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=claim_order.id,
            action="claim_order.status_changed_from_customer_refund_review",
            user_id=user.id,
            old_value={"status": previous_claim_order_status},
            new_value={"status": claim_order.status, "review_id": review.id, "review_type": review.review_type},
        )
    if inbound_message is not None:
        add_audit_log(
            db,
            entity_type="inbound_email_message",
            entity_id=inbound_message.id,
            action="inbound_message_marked_reviewed",
            user_id=user.id,
            new_value={"review_status": inbound_message.review_status, "review_id": review.id},
        )
