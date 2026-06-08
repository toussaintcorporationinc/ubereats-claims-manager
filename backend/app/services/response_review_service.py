from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClaimOrder, ClaimResponseReview, EmailAccount, InboundEmailMessage, User
from app.models.domain import utc_now
from app.schemas.domain import ClaimResponseReviewCreate
from app.services.audit import add_audit_log

PROTECTED_ORDER_STATUSES = {"payment_confirmed", "closed"}
REVIEW_STATUS_TRANSITIONS = {
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
class ResponseReviewError(Exception):
    message: str
    status_code: int


def create_response_review(
    db: Session,
    *,
    order: ClaimOrder,
    user: User,
    payload: ClaimResponseReviewCreate,
) -> ClaimResponseReview:
    previous_status = order.status
    if previous_status in PROTECTED_ORDER_STATUSES and payload.review_type != "ignored":
        raise ResponseReviewError("Final order status cannot be changed by a response review", 409)

    inbound_message = resolve_inbound_message(db, order=order, user=user, inbound_message_id=payload.inbound_message_id)
    new_status = get_new_status(previous_status, payload.review_type)

    review = ClaimResponseReview(
        order_id=order.id,
        inbound_message_id=inbound_message.id if inbound_message else None,
        reviewed_by_user_id=user.id,
        review_type=payload.review_type,
        previous_order_status=previous_status,
        new_order_status=new_status,
        recovered_amount=payload.recovered_amount,
        expected_payment_date=payload.expected_payment_date,
        refusal_reason=payload.refusal_reason,
        evidence_requested=True if payload.review_type == "evidence_requested" else payload.evidence_requested,
        notes=payload.notes,
    )
    db.add(review)

    if payload.review_type != "ignored":
        order.status = new_status
        order.result = payload.review_type
        if payload.recovered_amount is not None:
            order.recovered_amount = payload.recovered_amount
        order.updated_at = utc_now()

    if inbound_message is not None:
        inbound_message.review_status = "ignored" if payload.review_type == "ignored" else "reviewed"
        inbound_message.reviewed_at = utc_now()
        inbound_message.reviewed_by_user_id = user.id
        inbound_message.updated_at = utc_now()

    db.flush()
    add_audit_log(
        db,
        entity_type="claim_response_review",
        entity_id=review.id,
        action="response_review_created",
        user_id=user.id,
        new_value={
            "order_id": order.id,
            "inbound_message_id": review.inbound_message_id,
            "review_type": review.review_type,
            "previous_order_status": previous_status,
            "new_order_status": new_status,
        },
    )
    if payload.review_type != "ignored" and previous_status != new_status:
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=order.id,
            action="order_status_changed_from_response_review",
            user_id=user.id,
            old_value={"status": previous_status},
            new_value={"status": new_status, "review_id": review.id, "review_type": payload.review_type},
        )
    if inbound_message is not None:
        add_audit_log(
            db,
            entity_type="inbound_email_message",
            entity_id=inbound_message.id,
            action="inbound_message_marked_reviewed",
            user_id=user.id,
            old_value={"review_status": "unreviewed"},
            new_value={"review_status": inbound_message.review_status, "review_id": review.id},
        )
    return review


def get_new_status(previous_status: str, review_type: str) -> str:
    if review_type == "ignored":
        return previous_status
    return REVIEW_STATUS_TRANSITIONS[review_type]


def resolve_inbound_message(
    db: Session,
    *,
    order: ClaimOrder,
    user: User,
    inbound_message_id: int | None,
) -> InboundEmailMessage | None:
    if inbound_message_id is None:
        return None
    inbound_message = db.get(InboundEmailMessage, inbound_message_id)
    if inbound_message is None:
        raise ResponseReviewError("Inbound message not found", 404)
    if inbound_message.order_id == order.id:
        return inbound_message
    if inbound_message.order_id is not None:
        raise ResponseReviewError("Inbound message is linked to another order", 409)
    if user.role != "owner" and not user_owns_message_account(db, user, inbound_message):
        raise ResponseReviewError("Inbound message access denied", 403)

    inbound_message.order_id = order.id
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
