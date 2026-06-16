from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.models import (
    ClaimOrder,
    CustomerRefundDisputeReview,
    EmailDraft,
    EvidenceFile,
    EvidenceRequestTask,
    Restaurant,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    User,
)
from app.schemas.domain import (
    ClaimOrderRead,
    CustomerRefundBulkRequest,
    CustomerRefundBulkResponse,
    CustomerRefundDetectRequest,
    CustomerRefundDetectResponse,
    CustomerRefundDisputeDetail,
    CustomerRefundDisputeReviewCreate,
    CustomerRefundDisputeReviewRead,
    CustomerRefundDisputeReviewResponse,
    CustomerRefundDisputeReviewsResponse,
    CustomerRefundDisputeSummary,
    CustomerRefundDisputesResponse,
    CustomerRefundDisputeStatus,
    CustomerRefundDisputeType,
    CustomerRefundEvidenceRequirementRead,
    CustomerRefundEvidenceStatus,
    CustomerRefundIgnoreRequest,
    EmailDraftRead,
    EmailProviderDraftRead,
    EvidenceFileRead,
    UberCustomerRefundDisputeRead,
)
from app.services.customer_refund_detection_service import detect_customer_refund_disputes
from app.services.customer_refund_dispute_service import (
    create_claim_order_from_dispute,
    create_claim_orders_bulk,
    create_customer_refund_draft,
    create_customer_refund_gmail_draft,
    create_drafts_bulk,
    ignore_customer_refund_dispute,
    recalculate_dispute_evidence,
)
from app.services.customer_refund_review_service import CustomerRefundReviewError, create_customer_refund_review
from app.services.email_provider import EmailProvider
from app.services.gmail_email_provider import GmailEmailProvider

router = APIRouter(prefix="/v1/customer-refunds", tags=["customer-refunds"])
reviews_router = APIRouter(tags=["customer-refunds"])


def get_gmail_provider() -> EmailProvider:
    return GmailEmailProvider()


@router.post("/detect", response_model=CustomerRefundDetectResponse)
def detect_customer_refunds(
    payload: CustomerRefundDetectRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> CustomerRefundDetectResponse:
    payload = payload or CustomerRefundDetectRequest()
    result = detect_customer_refund_disputes(
        db,
        current_user,
        restaurant_id=payload.restaurant_id,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    return CustomerRefundDetectResponse(**result.__dict__)


@router.get("", response_model=CustomerRefundDisputesResponse)
def list_customer_refunds(
    restaurant_id: int | None = Query(default=None),
    dispute_type: CustomerRefundDisputeType | None = None,
    status_filter: CustomerRefundDisputeStatus | None = Query(default=None, alias="status"),
    evidence_status: CustomerRefundEvidenceStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: Decimal | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CustomerRefundDisputesResponse:
    if current_user.role == "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    statement = select(UberCustomerRefundDispute).order_by(UberCustomerRefundDispute.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(UberCustomerRefundDispute.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        statement = statement.where(UberCustomerRefundDispute.restaurant_id.in_(accessible_ids))
    if dispute_type:
        statement = statement.where(UberCustomerRefundDispute.dispute_type == dispute_type)
    if status_filter:
        statement = statement.where(UberCustomerRefundDispute.status == status_filter)
    if evidence_status:
        statement = statement.where(UberCustomerRefundDispute.evidence_status == evidence_status)
    if date_from is not None:
        statement = statement.where(UberCustomerRefundDispute.deducted_at >= date_from)
    if date_to is not None:
        statement = statement.where(UberCustomerRefundDispute.deducted_at <= date_to)
    if min_amount is not None:
        statement = statement.where(UberCustomerRefundDispute.customer_refund_amount >= min_amount)

    disputes = list(db.scalars(statement.limit(limit).offset(offset)).all())
    return CustomerRefundDisputesResponse(
        disputes=[build_dispute_summary(db, dispute) for dispute in disputes],
        limit=limit,
        offset=offset,
    )


@router.get("/{dispute_id}", response_model=CustomerRefundDisputeDetail)
def get_customer_refund(
    dispute_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> CustomerRefundDisputeDetail:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    return build_dispute_detail(db, dispute)


@router.post("/{dispute_id}/recalculate-evidence", response_model=UberCustomerRefundDisputeRead)
def recalculate_customer_refund_evidence(
    dispute_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberCustomerRefundDispute:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    dispute = recalculate_dispute_evidence(db, current_user, dispute, create_tasks=True)
    db.commit()
    db.refresh(dispute)
    return dispute


@router.post("/{dispute_id}/create-claim-order", response_model=ClaimOrderRead, status_code=status.HTTP_201_CREATED)
def create_claim_order(
    dispute_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ClaimOrder:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    return create_claim_order_from_dispute(db, current_user, dispute)


@router.post("/{dispute_id}/create-draft", response_model=EmailDraftRead, status_code=status.HTTP_201_CREATED)
def create_draft(
    dispute_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EmailDraft:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    return create_customer_refund_draft(db, current_user, dispute)


@router.post("/{dispute_id}/create-gmail-draft", response_model=EmailProviderDraftRead, status_code=status.HTTP_201_CREATED)
def create_gmail_draft(
    dispute_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> EmailProviderDraftRead:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    provider_draft = create_customer_refund_gmail_draft(db, current_user, dispute, provider)
    return EmailProviderDraftRead.model_validate(provider_draft)


@router.post("/{dispute_id}/ignore", response_model=UberCustomerRefundDisputeRead)
def ignore_dispute(
    dispute_id: int,
    payload: CustomerRefundIgnoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberCustomerRefundDispute:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    return ignore_customer_refund_dispute(db, current_user, dispute, payload.reason)


@router.post("/{dispute_id}/reviews", response_model=CustomerRefundDisputeReviewResponse, status_code=status.HTTP_201_CREATED)
def create_dispute_review(
    dispute_id: int,
    payload: CustomerRefundDisputeReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> CustomerRefundDisputeReviewResponse:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    try:
        review = create_customer_refund_review(db, dispute=dispute, user=current_user, payload=payload)
    except CustomerRefundReviewError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(review)
    db.refresh(dispute)
    claim_order_status = None
    if dispute.claim_order_id is not None:
        claim_order = db.get(ClaimOrder, dispute.claim_order_id)
        claim_order_status = claim_order.status if claim_order is not None else None
    return CustomerRefundDisputeReviewResponse(
        review=CustomerRefundDisputeReviewRead.model_validate(review),
        dispute_status=dispute.status,
        claim_order_status=claim_order_status,
    )


@router.get("/{dispute_id}/reviews", response_model=list[CustomerRefundDisputeReviewRead])
def list_dispute_reviews(
    dispute_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> list[CustomerRefundDisputeReviewRead]:
    dispute = get_dispute_or_404(db, current_user, dispute_id)
    reviews = db.scalars(
        select(CustomerRefundDisputeReview)
        .where(CustomerRefundDisputeReview.dispute_id == dispute.id)
        .order_by(CustomerRefundDisputeReview.created_at.desc(), CustomerRefundDisputeReview.id.desc())
    ).all()
    return [CustomerRefundDisputeReviewRead.model_validate(review) for review in reviews]


@reviews_router.get("/v1/customer-refund-reviews", response_model=CustomerRefundDisputeReviewsResponse)
def list_customer_refund_reviews(
    restaurant_id: int | None = Query(default=None),
    review_type: str | None = Query(default=None),
    dispute_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> CustomerRefundDisputeReviewsResponse:
    statement = (
        select(CustomerRefundDisputeReview)
        .join(UberCustomerRefundDispute, CustomerRefundDisputeReview.dispute_id == UberCustomerRefundDispute.id)
        .order_by(CustomerRefundDisputeReview.created_at.desc(), CustomerRefundDisputeReview.id.desc())
    )
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(UberCustomerRefundDispute.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        statement = statement.where(UberCustomerRefundDispute.restaurant_id.in_(accessible_ids))
    if review_type:
        statement = statement.where(CustomerRefundDisputeReview.review_type == review_type)
    if dispute_id is not None:
        dispute = get_dispute_or_404(db, current_user, dispute_id)
        statement = statement.where(CustomerRefundDisputeReview.dispute_id == dispute.id)
    if date_from is not None:
        statement = statement.where(CustomerRefundDisputeReview.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(CustomerRefundDisputeReview.created_at <= date_to)
    reviews = db.scalars(statement.limit(limit).offset(offset)).all()
    return CustomerRefundDisputeReviewsResponse(
        reviews=[CustomerRefundDisputeReviewRead.model_validate(review) for review in reviews],
        limit=limit,
        offset=offset,
    )


@router.post("/bulk-create-claim-orders", response_model=CustomerRefundBulkResponse)
def bulk_create_claim_orders(
    payload: CustomerRefundBulkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    return create_claim_orders_bulk(db, current_user, payload.dispute_ids)


@router.post("/bulk-create-drafts", response_model=CustomerRefundBulkResponse)
def bulk_create_drafts(
    payload: CustomerRefundBulkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    return create_drafts_bulk(db, current_user, payload.dispute_ids)


def get_dispute_or_404(db: Session, current_user: User, dispute_id: int) -> UberCustomerRefundDispute:
    dispute = db.get(UberCustomerRefundDispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer refund dispute not found")
    ensure_can_access_restaurant(db, current_user, dispute.restaurant_id)
    return dispute


def build_dispute_summary(db: Session, dispute: UberCustomerRefundDispute) -> CustomerRefundDisputeSummary:
    restaurant_name = db.scalar(select(Restaurant.name).where(Restaurant.id == dispute.restaurant_id)) or f"#{dispute.restaurant_id}"
    requirements = list(dispute.evidence_requirements)
    pending_count = len([item for item in requirements if item.status == "pending"])
    return CustomerRefundDisputeSummary(
        id=dispute.id,
        restaurant_id=dispute.restaurant_id,
        restaurant_name=restaurant_name,
        uber_order_id=dispute.uber_order_id,
        display_id=dispute.display_id,
        claim_order_id=dispute.claim_order_id,
        dispute_type=dispute.dispute_type,
        reason=dispute.reason,
        status=dispute.status,
        customer_refund_amount=dispute.customer_refund_amount,
        currency=dispute.currency,
        deducted_at=dispute.deducted_at,
        evidence_status=dispute.evidence_status,
        requirements_count=len(requirements),
        pending_requirements_count=pending_count,
        created_at=dispute.created_at,
    )


def build_dispute_detail(db: Session, dispute: UberCustomerRefundDispute) -> CustomerRefundDisputeDetail:
    restaurant_name = db.scalar(select(Restaurant.name).where(Restaurant.id == dispute.restaurant_id)) or f"#{dispute.restaurant_id}"
    snapshot = None
    if dispute.uber_order_id:
        snapshot_row = db.scalar(
            select(UberOrderSnapshot)
            .where(
                UberOrderSnapshot.restaurant_id == dispute.restaurant_id,
                UberOrderSnapshot.uber_order_id == dispute.uber_order_id,
            )
            .order_by(UberOrderSnapshot.id.desc())
        )
        snapshot = snapshot_to_dict(snapshot_row) if snapshot_row else None
    transaction = db.get(UberFinancialTransaction, dispute.financial_transaction_id) if dispute.financial_transaction_id else None
    claim_order = db.get(ClaimOrder, dispute.claim_order_id) if dispute.claim_order_id else None
    evidence_files = []
    evidence_tasks = []
    if dispute.claim_order_id is not None:
        evidence_files = list(db.scalars(select(EvidenceFile).where(EvidenceFile.order_id == dispute.claim_order_id)).all())
        tasks = list(
            db.scalars(
                select(EvidenceRequestTask).where(EvidenceRequestTask.customer_refund_dispute_id == dispute.id)
            ).all()
        )
        from app.routes.evidence_tasks import build_task_summary

        evidence_tasks = [
            build_task_summary(task, allow_import_fallback=False, allow_payload_fallback=False)
            for task in tasks
        ]
    return CustomerRefundDisputeDetail(
        dispute=UberCustomerRefundDisputeRead.model_validate(dispute),
        restaurant_name=restaurant_name,
        order_snapshot=snapshot,
        financial_transaction=transaction_to_dict(transaction) if transaction else None,
        claim_order=ClaimOrderRead.model_validate(claim_order) if claim_order else None,
        evidence_requirements=[CustomerRefundEvidenceRequirementRead.model_validate(item) for item in dispute.evidence_requirements],
        evidence_files=[EvidenceFileRead.model_validate(item) for item in evidence_files],
        evidence_tasks=evidence_tasks,
        reviews=[
            CustomerRefundDisputeReviewRead.model_validate(review)
            for review in sorted(dispute.reviews, key=lambda item: item.id, reverse=True)
        ],
    )


def snapshot_to_dict(snapshot: UberOrderSnapshot | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "id": snapshot.id,
        "uber_store_id": snapshot.uber_store_id,
        "uber_order_id": snapshot.uber_order_id,
        "display_id": snapshot.display_id,
        "current_state": snapshot.current_state,
        "order_total_amount": snapshot.order_total_amount,
        "currency": snapshot.currency,
    }


def transaction_to_dict(transaction: UberFinancialTransaction) -> dict[str, object]:
    return {
        "id": transaction.id,
        "uber_store_id": transaction.uber_store_id,
        "uber_order_id": transaction.uber_order_id,
        "transaction_type": transaction.transaction_type,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "transaction_date": transaction.transaction_date,
        "payout_reference": transaction.payout_reference,
    }
