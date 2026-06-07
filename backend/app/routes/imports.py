from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import ImportBatch, ImportRow, User
from app.schemas.domain import (
    ImportBatchRead,
    ImportConfirmResponse,
    ImportPreviewResponse,
    ImportRowsResponse,
    ImportRowStatus,
)
from app.services.order_import_service import (
    PREVIEW_ROW_LIMIT,
    OrderImportError,
    cancel_order_import_batch,
    confirm_order_import_batch,
    create_order_import_preview,
)

router = APIRouter(prefix="/v1/imports", tags=["imports"])


def get_batch_or_404(batch_id: int, db: Session) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found")
    return batch


def ensure_can_access_batch(batch: ImportBatch, current_user: User) -> None:
    if current_user.role == "owner":
        return
    if batch.uploaded_by_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Import batch access denied")


def preview_response(batch: ImportBatch, db: Session) -> ImportPreviewResponse:
    rows_preview = list(
        db.scalars(
            select(ImportRow)
            .where(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.id)
            .limit(PREVIEW_ROW_LIMIT)
        ).all()
    )
    return ImportPreviewResponse.model_validate(
        {
            **batch.__dict__,
            "batch_id": batch.id,
            "rows_preview": rows_preview,
        }
    )


@router.post("/orders/preview", response_model=ImportPreviewResponse, status_code=status.HTTP_201_CREATED)
def preview_order_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportPreviewResponse:
    try:
        batch = create_order_import_preview(db, current_user, file)
    except OrderImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(batch)
    return preview_response(batch, db)


@router.get("", response_model=list[ImportBatchRead])
def list_import_batches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ImportBatch]:
    statement = select(ImportBatch).order_by(ImportBatch.id.desc()).limit(50)
    if current_user.role != "owner":
        statement = statement.where(ImportBatch.uploaded_by_user_id == current_user.id)
    return list(db.scalars(statement).all())


@router.get("/{batch_id}", response_model=ImportBatchRead)
def get_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportBatch:
    batch = get_batch_or_404(batch_id, db)
    ensure_can_access_batch(batch, current_user)
    return batch


@router.get("/{batch_id}/rows", response_model=ImportRowsResponse)
def get_import_rows(
    batch_id: int,
    status_filter: ImportRowStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportRowsResponse:
    batch = get_batch_or_404(batch_id, db)
    ensure_can_access_batch(batch, current_user)
    statement = select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.id)
    if status_filter:
        statement = statement.where(ImportRow.status == status_filter)
    rows = list(db.scalars(statement.offset(offset).limit(limit)).all())
    return ImportRowsResponse(rows=rows, limit=limit, offset=offset)


@router.post("/{batch_id}/confirm", response_model=ImportConfirmResponse)
def confirm_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportConfirmResponse:
    batch = get_batch_or_404(batch_id, db)
    ensure_can_access_batch(batch, current_user)
    try:
        created_orders_count, skipped_rows, errors = confirm_order_import_batch(db, batch, current_user)
    except OrderImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(batch)
    return ImportConfirmResponse(
        batch_id=batch.id,
        status=batch.status,
        created_orders_count=created_orders_count,
        skipped_rows=skipped_rows,
        errors=errors,
    )


@router.post("/{batch_id}/cancel", response_model=ImportBatchRead)
def cancel_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportBatch:
    batch = get_batch_or_404(batch_id, db)
    ensure_can_access_batch(batch, current_user)
    try:
        cancel_order_import_batch(db, batch, current_user)
    except OrderImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(batch)
    return batch
