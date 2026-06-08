from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, get_accessible_restaurant_ids, get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.models import ClaimOrder, ClaimResponseReview, User
from app.schemas.domain import ClaimResponseReviewCreate, ClaimResponseReviewRead, ResponseReviewsResponse
from app.services.response_review_service import ResponseReviewError, create_response_review

router = APIRouter(tags=["response reviews"])


@router.post("/v1/orders/{order_id}/response-reviews", response_model=ClaimResponseReviewRead, status_code=201)
def create_order_response_review(
    order_id: int,
    payload: ClaimResponseReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ClaimResponseReviewRead:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    ensure_can_access_order(db, current_user, order)
    try:
        review = create_response_review(db, order=order, user=current_user, payload=payload)
    except ResponseReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(review)
    db.refresh(order)
    return build_review_response(review, order.status)


@router.get("/v1/orders/{order_id}/response-reviews", response_model=list[ClaimResponseReviewRead])
def list_order_response_reviews(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ClaimResponseReviewRead]:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    ensure_can_access_order(db, current_user, order)
    reviews = db.scalars(
        select(ClaimResponseReview)
        .where(ClaimResponseReview.order_id == order_id)
        .order_by(ClaimResponseReview.created_at.desc(), ClaimResponseReview.id.desc())
    ).all()
    return [build_review_response(review, order.status) for review in reviews]


@router.get("/v1/response-reviews", response_model=ResponseReviewsResponse)
def list_response_reviews(
    review_type: str | None = Query(default=None),
    restaurant_id: int | None = Query(default=None),
    order_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ResponseReviewsResponse:
    query = select(ClaimResponseReview, ClaimOrder.status).join(ClaimOrder, ClaimResponseReview.order_id == ClaimOrder.id)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return ResponseReviewsResponse(reviews=[], limit=limit, offset=offset)
        query = query.where(ClaimOrder.restaurant_id.in_(accessible_ids))
    if restaurant_id is not None:
        if accessible_ids is not None and restaurant_id not in accessible_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")
        query = query.where(ClaimOrder.restaurant_id == restaurant_id)
    if order_id is not None:
        order = db.get(ClaimOrder, order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        ensure_can_access_order(db, current_user, order)
        query = query.where(ClaimResponseReview.order_id == order_id)
    if review_type:
        query = query.where(ClaimResponseReview.review_type == review_type)

    rows = db.execute(
        query.order_by(ClaimResponseReview.created_at.desc(), ClaimResponseReview.id.desc()).limit(limit).offset(offset)
    ).all()
    return ResponseReviewsResponse(
        reviews=[build_review_response(review, order_status) for review, order_status in rows],
        limit=limit,
        offset=offset,
    )


def build_review_response(review: ClaimResponseReview, order_status: str) -> ClaimResponseReviewRead:
    return ClaimResponseReviewRead(
        id=review.id,
        order_id=review.order_id,
        inbound_message_id=review.inbound_message_id,
        reviewed_by_user_id=review.reviewed_by_user_id,
        review_type=review.review_type,
        previous_order_status=review.previous_order_status,
        new_order_status=review.new_order_status,
        recovered_amount=review.recovered_amount,
        expected_payment_date=review.expected_payment_date,
        refusal_reason=review.refusal_reason,
        evidence_requested=review.evidence_requested,
        notes=review.notes,
        order_status=order_status,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )
