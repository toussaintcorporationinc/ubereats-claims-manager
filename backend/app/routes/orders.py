from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ClaimOrder, EmailDraft, EvidenceFile, Restaurant
from app.schemas.domain import (
    ClaimOrderCreate,
    ClaimOrderRead,
    ClaimOrderUpdate,
    ClaimValidationResponse,
    EmailDraftRead,
    EvidenceFileCreate,
    EvidenceFileRead,
)
from app.services.audit import add_audit_log
from app.services.claim_validation_service import validate_claim_order

router = APIRouter(prefix="/v1/orders", tags=["orders"])


def get_order_or_404(order_id: int, db: Session) -> ClaimOrder:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def ensure_restaurant_exists(restaurant_id: int, db: Session) -> None:
    if db.get(Restaurant, restaurant_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")


def ensure_order_not_duplicate(restaurant_id: int, uber_order_number: str, db: Session) -> None:
    existing_order_id = db.scalar(
        select(ClaimOrder.id).where(
            ClaimOrder.restaurant_id == restaurant_id,
            ClaimOrder.uber_order_number == uber_order_number,
        )
    )
    if existing_order_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Uber order number already exists for this restaurant",
        )


@router.get("", response_model=list[ClaimOrderRead])
def list_orders(db: Session = Depends(get_db)) -> list[ClaimOrder]:
    return list(db.scalars(select(ClaimOrder).order_by(ClaimOrder.id)).all())


@router.post("", response_model=ClaimOrderRead, status_code=status.HTTP_201_CREATED)
def create_order(payload: ClaimOrderCreate, db: Session = Depends(get_db)) -> ClaimOrder:
    ensure_restaurant_exists(payload.restaurant_id, db)
    ensure_order_not_duplicate(payload.restaurant_id, payload.uber_order_number, db)

    order = ClaimOrder(**payload.model_dump())
    db.add(order)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Uber order number already exists for this restaurant",
        ) from exc

    add_audit_log(
        db,
        entity_type="claim_order",
        entity_id=order.id,
        action="claim_order.created",
        new_value={
            "restaurant_id": order.restaurant_id,
            "uber_order_number": order.uber_order_number,
            "order_amount": order.order_amount,
            "currency": order.currency,
            "status": order.status,
        },
    )
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=ClaimOrderRead)
def get_order(order_id: int, db: Session = Depends(get_db)) -> ClaimOrder:
    return get_order_or_404(order_id, db)


@router.patch("/{order_id}", response_model=ClaimOrderRead)
def update_order(order_id: int, payload: ClaimOrderUpdate, db: Session = Depends(get_db)) -> ClaimOrder:
    order = get_order_or_404(order_id, db)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, field, value)

    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/validate", response_model=ClaimValidationResponse)
def validate_order(order_id: int, db: Session = Depends(get_db)) -> ClaimValidationResponse | JSONResponse:
    result = validate_claim_order(db, order_id)

    if "order_not_found" in result.blocking_reasons:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=jsonable_encoder(result))

    db.commit()

    if "final_status_cannot_be_validated" in result.blocking_reasons:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=jsonable_encoder(result))

    return result


@router.get("/{order_id}/evidence", response_model=list[EvidenceFileRead])
def list_evidence(order_id: int, db: Session = Depends(get_db)) -> list[EvidenceFile]:
    get_order_or_404(order_id, db)
    return list(db.scalars(select(EvidenceFile).where(EvidenceFile.order_id == order_id).order_by(EvidenceFile.id)).all())


@router.post("/{order_id}/evidence", response_model=EvidenceFileRead, status_code=status.HTTP_201_CREATED)
def add_evidence(order_id: int, payload: EvidenceFileCreate, db: Session = Depends(get_db)) -> EvidenceFile:
    get_order_or_404(order_id, db)
    evidence_file = EvidenceFile(order_id=order_id, **payload.model_dump())
    db.add(evidence_file)
    db.flush()
    add_audit_log(
        db,
        entity_type="evidence_file",
        entity_id=evidence_file.id,
        action="evidence_file.created",
        new_value={
            "order_id": evidence_file.order_id,
            "evidence_type": evidence_file.evidence_type,
            "original_filename": evidence_file.original_filename,
        },
    )
    db.commit()
    db.refresh(evidence_file)
    return evidence_file


@router.get("/{order_id}/drafts", response_model=list[EmailDraftRead])
def list_drafts(order_id: int, db: Session = Depends(get_db)) -> list[EmailDraft]:
    get_order_or_404(order_id, db)
    return list(db.scalars(select(EmailDraft).where(EmailDraft.order_id == order_id).order_by(EmailDraft.id)).all())
