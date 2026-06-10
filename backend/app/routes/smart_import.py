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
from app.services.smart_import_classifier_service import confirm_smart_import_preview, create_smart_import_preview

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
    confirmed = confirm_smart_import_preview(db, current_user, batch)
    return SmartImportConfirmResponse(
        batch_preview_id=confirmed.id,
        status=confirmed.status,
        recommended_actions=[file.recommended_action for file in confirmed.files],
    )


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
