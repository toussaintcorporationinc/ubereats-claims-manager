from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, get_current_user
from app.core.database import get_db
from app.models import EvidenceFile, User
from app.services.file_storage_service import FileStorageError, resolve_evidence_path

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


@router.get("/{evidence_id}/download")
def download_evidence(
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    evidence_file = db.get(EvidenceFile, evidence_id)
    if evidence_file is None or evidence_file.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    ensure_can_access_order(db, current_user, evidence_file.order)
    try:
        file_path = resolve_evidence_path(evidence_file)
    except FileStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return FileResponse(
        path=file_path,
        media_type=evidence_file.mime_type or "application/octet-stream",
        filename=evidence_file.original_filename,
    )
