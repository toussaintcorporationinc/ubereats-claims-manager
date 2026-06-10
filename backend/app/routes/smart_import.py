from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from app.core.auth import require_owner_or_manager
from app.core.database import get_db
from app.models import SmartImportPreviewBatch, User
from app.schemas.domain import (
    SmartImportConfirmRequest,
    SmartImportConfirmResponse,
    SmartImportFilePreviewRead,
    SmartImportPreviewResponse,
)
from app.services.smart_import_classifier_service import create_smart_import_preview
from app.services.smart_import_cleanup_service import cleanup_expired_smart_import_previews
from app.services.smart_import_routing_service import (
    SmartImportDecision,
    cancel_smart_import_preview,
    route_smart_import_preview,
)

router = APIRouter(prefix="/v1/smart-import", tags=["smart-import"])


@router.post("/preview", response_model=SmartImportPreviewResponse, status_code=status.HTTP_201_CREATED)
async def preview_smart_import(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> SmartImportPreviewResponse:
    batch = await create_smart_import_preview(db, current_user, files)
    return smart_import_response(batch)


@router.get("/previews/{batch_id}", response_model=SmartImportPreviewResponse)
def get_smart_import_preview(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> SmartImportPreviewResponse:
    batch = get_batch_or_404(db, batch_id, current_user)
    return smart_import_response(batch)


@router.post("/confirm", response_model=SmartImportConfirmResponse)
def confirm_smart_import(
    payload: SmartImportConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> SmartImportConfirmResponse:
    batch = get_batch_or_404(db, payload.batch_preview_id, current_user)
    result = route_smart_import_preview(
        db,
        current_user,
        batch,
        [
            SmartImportDecision(
                file_id=decision.file_id,
                action=decision.action,
                report_type=decision.report_type,
                restaurant_id=decision.restaurant_id,
            )
            for decision in payload.files
        ],
    )
    return SmartImportConfirmResponse(**result)


@router.post("/previews/{batch_id}/cancel", response_model=SmartImportPreviewResponse)
def cancel_smart_import(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> SmartImportPreviewResponse:
    batch = get_batch_or_404(db, batch_id, current_user)
    cancelled = cancel_smart_import_preview(db, current_user, batch)
    return smart_import_response(cancelled)


@router.post("/cleanup-expired")
def cleanup_expired_smart_import(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, int]:
    if current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return cleanup_expired_smart_import_previews(db, current_user)


def get_batch_or_404(db: Session, batch_id: int, current_user: User) -> SmartImportPreviewBatch:
    batch = db.get(SmartImportPreviewBatch, batch_id, options=[selectinload(SmartImportPreviewBatch.files)])
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart import preview not found")
    if current_user.role != "owner" and batch.uploaded_by_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Smart import preview access denied")
    return batch


def smart_import_response(batch: SmartImportPreviewBatch) -> SmartImportPreviewResponse:
    return SmartImportPreviewResponse(
        batch_preview_id=batch.id,
        status=batch.status,
        files=[SmartImportFilePreviewRead.model_validate(file) for file in batch.files],
    )
