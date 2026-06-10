from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import SmartImportPreviewBatch, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.smart_import_classifier_service import ensure_smart_import_storage_root


def cleanup_expired_smart_import_previews(db: Session, current_user: User) -> dict[str, int]:
    now = utc_now()
    batches = db.scalars(
        select(SmartImportPreviewBatch)
        .options(selectinload(SmartImportPreviewBatch.files))
        .where(
            SmartImportPreviewBatch.status == "previewed",
            SmartImportPreviewBatch.expires_at.is_not(None),
            SmartImportPreviewBatch.expires_at < now,
        )
    ).all()
    removed_files = 0
    expired_files = 0
    storage_root = ensure_smart_import_storage_root().resolve()

    for batch in batches:
        batch.status = "expired"
        for preview_file in batch.files:
            if preview_file.status != "previewed":
                continue
            preview_file.status = "expired"
            expired_files += 1
            if preview_file.temp_storage_path and preview_file.destination_type is None:
                removed_files += int(remove_preview_file(storage_root, preview_file.temp_storage_path))
        add_audit_log(
            db,
            entity_type="smart_import_preview_batch",
            entity_id=batch.id,
            action="smart_import_preview.expired",
            user_id=current_user.id,
            new_value={"expired_files": expired_files},
        )
    db.commit()
    return {"expired_batches": len(batches), "expired_files": expired_files, "removed_files": removed_files}


def remove_preview_file(storage_root: Path, relative_path: str) -> bool:
    target = (storage_root / relative_path).resolve()
    if not target.is_relative_to(storage_root) or not target.exists() or not target.is_file():
        return False
    target.unlink()
    return True
