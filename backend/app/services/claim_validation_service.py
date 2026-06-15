from sqlalchemy.orm import Session

from app.models import ClaimOrder, Restaurant
from app.schemas.domain import ClaimValidationResponse
from app.services.audit import add_audit_log

FINAL_CLAIM_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}


def get_claim_validation_gaps(db: Session, order: ClaimOrder) -> tuple[list[str], list[str]]:
    missing_items: list[str] = []
    blocking_reasons: list[str] = []

    if order.restaurant_id is None or db.get(Restaurant, order.restaurant_id) is None:
        missing_items.append("restaurant")
        blocking_reasons.append("missing_restaurant")

    if not order.uber_order_number:
        missing_items.append("uber_order_number")
        blocking_reasons.append("missing_uber_order_number")

    if order.order_amount is None:
        missing_items.append("order_amount")
        blocking_reasons.append("missing_order_amount")

    if not order.currency:
        missing_items.append("currency")
        blocking_reasons.append("missing_currency")

    evidence_types = {
        evidence.evidence_type
        for evidence in order.evidence_files
        if getattr(evidence, "deleted_at", None) is None
    }
    has_unified_order_proof = "receipt" in evidence_types
    has_legacy_proof_set = "cancellation_proof" in evidence_types and bool({"preparation_proof", "waste_photo"} & evidence_types)
    if not (has_unified_order_proof or has_legacy_proof_set):
        missing_items.append("receipt")
        blocking_reasons.append("missing_unified_order_proof")

    return missing_items, blocking_reasons


def validate_claim_order(db: Session, order_id: int, user_id: int | None = None) -> ClaimValidationResponse:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        return ClaimValidationResponse(
            order_id=order_id,
            is_complete=False,
            previous_status=None,
            new_status=None,
            missing_items=[],
            blocking_reasons=["order_not_found"],
        )

    previous_status = order.status
    if previous_status in FINAL_CLAIM_STATUSES:
        result = ClaimValidationResponse(
            order_id=order.id,
            is_complete=False,
            previous_status=previous_status,
            new_status=previous_status,
            missing_items=[],
            blocking_reasons=["final_status_cannot_be_validated"],
        )
        add_validation_audit_log(db, order, previous_status, result, user_id=user_id)
        return result

    missing_items, blocking_reasons = get_claim_validation_gaps(db, order)
    is_complete = not missing_items
    order.status = "ready_to_send" if is_complete else "missing_evidence"

    result = ClaimValidationResponse(
        order_id=order.id,
        is_complete=is_complete,
        previous_status=previous_status,
        new_status=order.status,
        missing_items=missing_items,
        blocking_reasons=blocking_reasons,
    )
    add_validation_audit_log(db, order, previous_status, result, user_id=user_id)
    return result


def add_validation_audit_log(
    db: Session,
    order: ClaimOrder,
    previous_status: str,
    result: ClaimValidationResponse,
    user_id: int | None = None,
) -> None:
    add_audit_log(
        db,
        entity_type="claim_order",
        entity_id=order.id,
        action="validate_claim_order",
        user_id=user_id,
        old_value={"status": previous_status},
        new_value={
            "status": result.new_status,
            "is_complete": result.is_complete,
            "missing_items": result.missing_items,
            "blocking_reasons": result.blocking_reasons,
        },
    )

