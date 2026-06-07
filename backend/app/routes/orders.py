from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import (
    ensure_can_access_order,
    ensure_can_access_restaurant,
    get_accessible_restaurant_ids,
    get_current_user,
    require_owner_or_manager,
)
from app.core.database import get_db
from app.models import ClaimOrder, EmailDraft, EvidenceFile, Restaurant, User
from app.models.domain import EVIDENCE_TYPES
from app.schemas.domain import (
    ClaimOrderCreate,
    ClaimOrderRead,
    ClaimOrderUpdate,
    ClaimValidationResponse,
    EmailDraftCreate,
    EmailDraftRead,
    EvidenceFileCreate,
    EvidenceFileRead,
)
from app.services.audit import add_audit_log
from app.services.claim_validation_service import validate_claim_order
from app.services.email_draft_service import (
    EmailDraftBusinessError,
    EmailDraftNotFoundError,
    create_email_draft,
)
from app.services.file_storage_service import FileStorageError, store_evidence_upload

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
def list_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ClaimOrder]:
    statement = select(ClaimOrder).order_by(ClaimOrder.id)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return []
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
    return list(db.scalars(statement).all())


@router.post("", response_model=ClaimOrderRead, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: ClaimOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClaimOrder:
    ensure_restaurant_exists(payload.restaurant_id, db)
    ensure_can_access_restaurant(db, current_user, payload.restaurant_id)
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
        user_id=current_user.id,
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
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClaimOrder:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)
    return order


@router.patch("/{order_id}", response_model=ClaimOrderRead)
def update_order(
    order_id: int,
    payload: ClaimOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ClaimOrder:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(order, field, value)

    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/validate", response_model=ClaimValidationResponse)
def validate_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ClaimValidationResponse | JSONResponse:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        result = validate_claim_order(db, order_id, user_id=current_user.id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=jsonable_encoder(result))
    ensure_can_access_order(db, current_user, order)
    result = validate_claim_order(db, order_id, user_id=current_user.id)

    if "order_not_found" in result.blocking_reasons:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=jsonable_encoder(result))

    db.commit()

    if "final_status_cannot_be_validated" in result.blocking_reasons:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=jsonable_encoder(result))

    return result


@router.get("/{order_id}/evidence", response_model=list[EvidenceFileRead])
def list_evidence(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EvidenceFile]:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)
    return list(
        db.scalars(
            select(EvidenceFile)
            .where(EvidenceFile.order_id == order_id, EvidenceFile.deleted_at.is_(None))
            .order_by(EvidenceFile.id)
        ).all()
    )


@router.post("/{order_id}/evidence", response_model=EvidenceFileRead, status_code=status.HTTP_201_CREATED)
def add_evidence(
    order_id: int,
    payload: EvidenceFileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceFile:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)
    evidence_file = EvidenceFile(
        order_id=order_id,
        uploaded_by_user_id=current_user.id,
        storage_backend="local",
        **payload.model_dump(),
    )
    db.add(evidence_file)
    db.flush()
    add_audit_log(
        db,
        entity_type="evidence_file",
        entity_id=evidence_file.id,
        action="evidence_file.created",
        user_id=current_user.id,
        new_value={
            "order_id": evidence_file.order_id,
            "evidence_type": evidence_file.evidence_type,
            "original_filename": evidence_file.original_filename,
        },
    )
    db.commit()
    db.refresh(evidence_file)
    return evidence_file


@router.post("/{order_id}/evidence/upload", response_model=EvidenceFileRead, status_code=status.HTTP_201_CREATED)
def upload_evidence(
    order_id: int,
    evidence_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceFile:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)
    if evidence_type not in EVIDENCE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid evidence_type")

    try:
        stored_file = store_evidence_upload(order, file)
    except FileStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    evidence_file = EvidenceFile(
        order_id=order_id,
        evidence_type=evidence_type,
        original_filename=stored_file.original_filename,
        storage_path=stored_file.storage_path,
        storage_backend=stored_file.storage_backend,
        mime_type=stored_file.mime_type,
        file_size=stored_file.file_size,
        checksum_sha256=stored_file.checksum_sha256,
        uploaded_by_user_id=current_user.id,
    )
    db.add(evidence_file)
    db.flush()
    add_audit_log(
        db,
        entity_type="evidence_file",
        entity_id=evidence_file.id,
        action="evidence_file.uploaded",
        user_id=current_user.id,
        new_value={
            "order_id": evidence_file.order_id,
            "evidence_type": evidence_file.evidence_type,
            "original_filename": evidence_file.original_filename,
            "mime_type": evidence_file.mime_type,
            "file_size": evidence_file.file_size,
            "checksum_sha256": evidence_file.checksum_sha256,
        },
    )
    db.commit()
    db.refresh(evidence_file)
    return evidence_file


@router.get("/{order_id}/drafts", response_model=list[EmailDraftRead])
def list_drafts(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EmailDraft]:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)
    return list(db.scalars(select(EmailDraft).where(EmailDraft.order_id == order_id).order_by(EmailDraft.id)).all())


@router.post("/{order_id}/drafts", response_model=EmailDraftRead, status_code=status.HTTP_201_CREATED)
def create_draft(
    order_id: int,
    payload: EmailDraftCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EmailDraft:
    order = get_order_or_404(order_id, db)
    ensure_can_access_order(db, current_user, order)
    try:
        draft = create_email_draft(db, order_id, payload.draft_type, user_id=current_user.id)
    except EmailDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found") from exc
    except EmailDraftBusinessError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": exc.message, "blocking_reasons": exc.blocking_reasons},
        ) from exc

    db.commit()
    db.refresh(draft)
    return draft
