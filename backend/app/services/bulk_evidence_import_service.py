from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant
from app.core.config import get_settings
from app.models import ClaimOrder, EvidenceFile, EvidenceImportBatch, EvidenceImportedFile, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log

IGNORED_ZIP_NAMES = {".ds_store"}
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StoredImportedEvidence:
    original_filename: str
    internal_filename: str
    storage_backend: str
    storage_path: str
    mime_type: str | None
    file_size: int
    checksum_sha256: str


@dataclass(frozen=True)
class DuplicateEvidenceMatch:
    canonical_type: str
    canonical_id: int | None
    reason: str
    canonical_filename: str | None = None
    canonical_internal_filename: str | None = None
    canonical_storage_backend: str | None = None
    canonical_storage_path: str | None = None
    canonical_mime_type: str | None = None
    canonical_file_size: int | None = None


class BulkEvidenceImportError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def create_multi_file_import(
    db: Session,
    current_user: User,
    *,
    files: list[UploadFile],
    restaurant_id: int | None,
) -> EvidenceImportBatch:
    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one evidence file is required")
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)

    settings = get_settings()
    if len(files) > settings.bulk_evidence_max_files_per_batch:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too many files in evidence batch")

    batch = EvidenceImportBatch(
        uploaded_by_user_id=current_user.id,
        restaurant_id=restaurant_id,
        original_filename=None,
        source_type="multi_file_upload",
        status="uploaded",
    )
    db.add(batch)
    db.flush()

    errors: list[str] = []
    seen_checksums: dict[str, EvidenceImportedFile] = {}
    duplicate_messages: list[str] = []
    for upload in files:
        try:
            stored = store_imported_upload(batch, upload)
            duplicate = detect_duplicate_imported_evidence(
                db,
                batch=batch,
                current_user=current_user,
                stored=stored,
                seen_checksums=seen_checksums,
            )
            if duplicate is not None:
                remove_duplicate_stored_file(stored)
                record_duplicate_removed(db, batch, current_user, stored, duplicate)
                duplicate_messages.append(duplicate_message(stored.original_filename, duplicate))
                continue
            imported_file = add_imported_file(db, batch, current_user, stored)
            seen_checksums[stored.checksum_sha256] = imported_file
        except BulkEvidenceImportError as exc:
            batch.failed_files_count += 1
            errors.append(f"{upload.filename or 'file'}: {exc.message}")

    finalize_batch_counts(db, batch, total_files_count=len(files))
    batch.error_message = "\n".join([*errors, *duplicate_messages]) if errors or duplicate_messages else None
    add_import_audit_log(db, current_user, batch, errors)
    db.commit()
    db.refresh(batch)
    return batch


def create_zip_import(
    db: Session,
    current_user: User,
    *,
    file: UploadFile,
    restaurant_id: int | None,
) -> EvidenceImportBatch:
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)

    original_filename = safe_original_filename(file.filename)
    if Path(original_filename).suffix.lower() != ".zip":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ZIP import requires a .zip file")

    data = read_upload_bytes(file, get_settings().bulk_evidence_max_zip_size_mb * 1024 * 1024)
    batch = EvidenceImportBatch(
        uploaded_by_user_id=current_user.id,
        restaurant_id=restaurant_id,
        original_filename=original_filename,
        source_type="zip_upload",
        status="extracting",
    )
    db.add(batch)
    db.flush()

    errors: list[str] = []
    seen_checksums: dict[str, EvidenceImportedFile] = {}
    duplicate_messages: list[str] = []
    members_count = 0
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir() and not should_ignore_zip_member(member.filename)]
            members_count = len(members)
            if len(members) > get_settings().bulk_evidence_max_files_per_batch:
                raise BulkEvidenceImportError("ZIP contains too many files", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            for member in members:
                try:
                    validate_zip_member(member.filename)
                    member_data = archive.read(member)
                    stored = store_imported_bytes(batch, member.filename, member_data)
                    duplicate = detect_duplicate_imported_evidence(
                        db,
                        batch=batch,
                        current_user=current_user,
                        stored=stored,
                        seen_checksums=seen_checksums,
                    )
                    if duplicate is not None:
                        remove_duplicate_stored_file(stored)
                        record_duplicate_removed(db, batch, current_user, stored, duplicate)
                        duplicate_messages.append(duplicate_message(stored.original_filename, duplicate))
                        continue
                    imported_file = add_imported_file(db, batch, current_user, stored)
                    seen_checksums[stored.checksum_sha256] = imported_file
                except (BulkEvidenceImportError, RuntimeError) as exc:
                    if is_dangerous_zip_error(exc):
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
                    batch.failed_files_count += 1
                    errors.append(f"{member.filename}: {exc}")
    except BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ZIP file") from exc

    finalize_batch_counts(db, batch, total_files_count=members_count)
    batch.error_message = "\n".join([*errors, *duplicate_messages]) if errors or duplicate_messages else None
    add_import_audit_log(db, current_user, batch, errors)
    db.commit()
    db.refresh(batch)
    return batch


def add_imported_file(
    db: Session,
    batch: EvidenceImportBatch,
    current_user: User,
    stored: StoredImportedEvidence,
) -> EvidenceImportedFile:
    imported_file = EvidenceImportedFile(
        batch_id=batch.id,
        uploaded_by_user_id=current_user.id,
        original_filename=stored.original_filename,
        internal_filename=stored.internal_filename,
        storage_backend=stored.storage_backend,
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        checksum_sha256=stored.checksum_sha256,
        status="analysis_pending",
    )
    db.add(imported_file)
    db.flush()
    return imported_file


def finalize_batch_counts(db: Session, batch: EvidenceImportBatch, total_files_count: int | None = None) -> None:
    db.flush()
    imported_file_statuses = db.scalars(
        select(EvidenceImportedFile.status).where(EvidenceImportedFile.batch_id == batch.id)
    ).all()
    batch.total_files = (
        total_files_count if total_files_count is not None else len(imported_file_statuses) + batch.failed_files_count
    )
    batch.stored_files_count = len([file_status for file_status in imported_file_statuses if file_status != "ignored"])
    if batch.stored_files_count:
        batch.status = "stored"
    elif batch.duplicate_files_count and not batch.failed_files_count:
        batch.status = "analyzed"
        batch.completed_at = utc_now()
    else:
        batch.status = "failed"
        batch.completed_at = utc_now()
    batch.updated_at = utc_now()


def detect_duplicate_imported_evidence(
    db: Session,
    *,
    batch: EvidenceImportBatch,
    current_user: User,
    stored: StoredImportedEvidence,
    seen_checksums: dict[str, EvidenceImportedFile],
) -> DuplicateEvidenceMatch | None:
    current_batch_match = seen_checksums.get(stored.checksum_sha256)
    if current_batch_match is not None:
        return DuplicateEvidenceMatch(
            canonical_type="evidence_imported_file",
            canonical_id=current_batch_match.id,
            canonical_filename=current_batch_match.original_filename,
            canonical_internal_filename=current_batch_match.internal_filename,
            canonical_storage_backend=current_batch_match.storage_backend,
            canonical_storage_path=current_batch_match.storage_path,
            canonical_mime_type=current_batch_match.mime_type,
            canonical_file_size=current_batch_match.file_size,
            reason="duplicate_same_import_checksum",
        )

    existing_imported = find_existing_imported_file_duplicate(db, batch, current_user, stored.checksum_sha256)
    if existing_imported is not None:
        return DuplicateEvidenceMatch(
            canonical_type="evidence_imported_file",
            canonical_id=existing_imported.id,
            canonical_filename=existing_imported.original_filename,
            canonical_internal_filename=existing_imported.internal_filename,
            canonical_storage_backend=existing_imported.storage_backend,
            canonical_storage_path=existing_imported.storage_path,
            canonical_mime_type=existing_imported.mime_type,
            canonical_file_size=existing_imported.file_size,
            reason="duplicate_existing_import_checksum",
        )

    existing_evidence = find_existing_attached_evidence_duplicate(db, batch, current_user, stored.checksum_sha256)
    if existing_evidence is not None:
        return DuplicateEvidenceMatch(
            canonical_type="evidence_file",
            canonical_id=existing_evidence.id,
            canonical_filename=existing_evidence.original_filename,
            canonical_internal_filename=existing_evidence.original_filename,
            canonical_storage_backend=existing_evidence.storage_backend,
            canonical_storage_path=existing_evidence.storage_path,
            canonical_mime_type=existing_evidence.mime_type,
            canonical_file_size=existing_evidence.file_size,
            reason="duplicate_existing_attached_evidence_checksum",
        )

    return None


def find_existing_imported_file_duplicate(
    db: Session,
    batch: EvidenceImportBatch,
    current_user: User,
    checksum_sha256: str,
) -> EvidenceImportedFile | None:
    statement = (
        select(EvidenceImportedFile)
        .join(EvidenceImportBatch, EvidenceImportedFile.batch_id == EvidenceImportBatch.id)
        .where(
            EvidenceImportedFile.checksum_sha256 == checksum_sha256,
            EvidenceImportedFile.status != "ignored",
            EvidenceImportBatch.id != batch.id,
        )
        .order_by(EvidenceImportedFile.id.asc())
    )
    if batch.restaurant_id is not None:
        statement = statement.where(EvidenceImportBatch.restaurant_id == batch.restaurant_id)
    elif current_user.role == "owner":
        statement = statement.where(EvidenceImportBatch.restaurant_id.is_(None))
    else:
        statement = statement.where(
            EvidenceImportBatch.restaurant_id.is_(None),
            EvidenceImportedFile.uploaded_by_user_id == current_user.id,
        )
    return db.scalar(statement)


def find_existing_attached_evidence_duplicate(
    db: Session,
    batch: EvidenceImportBatch,
    current_user: User,
    checksum_sha256: str,
) -> EvidenceFile | None:
    statement = (
        select(EvidenceFile)
        .join(ClaimOrder, EvidenceFile.order_id == ClaimOrder.id)
        .where(EvidenceFile.checksum_sha256 == checksum_sha256, EvidenceFile.deleted_at.is_(None))
        .order_by(EvidenceFile.id.asc())
    )
    if batch.restaurant_id is not None:
        statement = statement.where(ClaimOrder.restaurant_id == batch.restaurant_id)
    elif current_user.role == "owner":
        return None
    else:
        statement = statement.where(EvidenceFile.uploaded_by_user_id == current_user.id)
    return db.scalar(statement)


def remove_duplicate_stored_file(stored: StoredImportedEvidence) -> None:
    if stored.storage_backend != "local":
        return
    storage_root = ensure_bulk_storage_root().resolve()
    target = (storage_root / stored.storage_path).resolve()
    if target.is_relative_to(storage_root) and target.exists() and target.is_file():
        target.unlink()


def record_duplicate_removed(
    db: Session,
    batch: EvidenceImportBatch,
    current_user: User,
    stored: StoredImportedEvidence,
    duplicate: DuplicateEvidenceMatch,
) -> None:
    batch.duplicate_files_count += 1
    if duplicate.canonical_storage_path:
        duplicate_placeholder = EvidenceImportedFile(
            uploaded_by_user_id=current_user.id,
            original_filename=stored.original_filename,
            internal_filename=duplicate.canonical_internal_filename
            or f"duplicate-of-{duplicate.canonical_type}-{duplicate.canonical_id or 'unknown'}",
            storage_backend=duplicate.canonical_storage_backend or stored.storage_backend,
            storage_path=duplicate.canonical_storage_path,
            mime_type=stored.mime_type or duplicate.canonical_mime_type,
            file_size=stored.file_size,
            checksum_sha256=stored.checksum_sha256,
            status="ignored",
        )
        batch.files.append(duplicate_placeholder)
    add_audit_log(
        db,
        user_id=current_user.id,
        entity_type="evidence_import_batch",
        entity_id=batch.id,
        action="evidence_import_file.duplicate_removed",
        new_value={
            "original_filename": stored.original_filename,
            "checksum_sha256": stored.checksum_sha256,
            "duplicate_reason": duplicate.reason,
            "canonical_type": duplicate.canonical_type,
            "canonical_id": duplicate.canonical_id,
            "canonical_filename": duplicate.canonical_filename,
        },
    )


def duplicate_message(filename: str, duplicate: DuplicateEvidenceMatch) -> str:
    canonical = f"{duplicate.canonical_type}#{duplicate.canonical_id}" if duplicate.canonical_id else duplicate.canonical_type
    return f"{filename}: duplicate_removed:{duplicate.reason}:{canonical}"


def store_imported_upload(batch: EvidenceImportBatch, upload: UploadFile) -> StoredImportedEvidence:
    original_filename = safe_original_filename(upload.filename)
    max_size = get_settings().bulk_evidence_max_file_size_mb * 1024 * 1024
    data = read_upload_bytes(upload, max_size)
    return store_imported_bytes(batch, original_filename, data, upload.content_type or None)


def store_imported_bytes(
    batch: EvidenceImportBatch,
    filename: str,
    data: bytes,
    mime_type: str | None = None,
) -> StoredImportedEvidence:
    original_filename = safe_original_filename(filename)
    if not data:
        raise BulkEvidenceImportError("Evidence file cannot be empty")
    max_size = get_settings().bulk_evidence_max_file_size_mb * 1024 * 1024
    if len(data) > max_size:
        raise BulkEvidenceImportError("Evidence file is too large", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    extension = Path(original_filename).suffix.lower()
    allowed = allowed_extensions()
    if extension not in allowed:
        raise BulkEvidenceImportError("Evidence file extension is not allowed", status.HTTP_422_UNPROCESSABLE_ENTITY)

    storage_root = ensure_bulk_storage_root()
    relative_dir = Path("bulk_imports") / f"batch_{batch.id}"
    target_dir = storage_root / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    internal_filename = f"{uuid4().hex}{extension}"
    relative_path = relative_dir / internal_filename
    target_path = storage_root / relative_path
    digest = sha256(data).hexdigest()
    target_path.write_bytes(data)
    return StoredImportedEvidence(
        original_filename=original_filename,
        internal_filename=internal_filename,
        storage_backend=get_settings().evidence_storage_backend,
        storage_path=relative_path.as_posix(),
        mime_type=mime_type or guess_type(original_filename)[0],
        file_size=len(data),
        checksum_sha256=digest,
    )


def resolve_imported_file_path(imported_file: EvidenceImportedFile) -> Path:
    if imported_file.storage_backend != "local":
        raise BulkEvidenceImportError("Only local imported evidence storage is available in V1.1", status.HTTP_404_NOT_FOUND)
    storage_root = ensure_bulk_storage_root().resolve()
    target = (storage_root / imported_file.storage_path).resolve()
    if not target.is_relative_to(storage_root):
        raise BulkEvidenceImportError("Imported evidence storage path is invalid", status.HTTP_404_NOT_FOUND)
    if not target.exists() or not target.is_file():
        raise BulkEvidenceImportError("Imported evidence file is missing", status.HTTP_404_NOT_FOUND)
    return target


def read_upload_bytes(upload: UploadFile, max_size: int) -> bytes:
    digest = bytearray()
    total = 0
    while chunk := upload.file.read(CHUNK_SIZE):
        total += len(chunk)
        if total > max_size:
            raise BulkEvidenceImportError("Upload is too large", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        digest.extend(chunk)
    if not digest:
        raise BulkEvidenceImportError("Upload cannot be empty")
    return bytes(digest)


def safe_original_filename(filename: str | None) -> str:
    if not filename:
        raise BulkEvidenceImportError("Filename is required")
    original = Path(filename).name.strip()
    if not original or original in {".", ".."}:
        raise BulkEvidenceImportError("Filename is invalid")
    return original


def validate_zip_member(filename: str) -> None:
    if filename.startswith("/") or filename.startswith("\\"):
        raise BulkEvidenceImportError("ZIP member absolute paths are not allowed")
    parts = Path(filename.replace("\\", "/")).parts
    if ".." in parts:
        raise BulkEvidenceImportError("ZIP path traversal is not allowed")
    if Path(filename).suffix.lower() == ".zip":
        raise BulkEvidenceImportError("Nested ZIP archives are not supported")


def is_dangerous_zip_error(exc: object) -> bool:
    message = str(exc)
    return any(
        token in message
        for token in (
            "absolute paths are not allowed",
            "path traversal is not allowed",
            "Nested ZIP archives are not supported",
        )
    )


def should_ignore_zip_member(filename: str) -> bool:
    lower = Path(filename).name.lower()
    return filename.startswith("__MACOSX/") or lower in IGNORED_ZIP_NAMES


def ensure_bulk_storage_root() -> Path:
    settings = get_settings()
    if settings.evidence_storage_backend != "local":
        raise BulkEvidenceImportError("Only local evidence storage is available in V1.1")
    settings.evidence_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings.evidence_storage_dir


def allowed_extensions() -> set[str]:
    configured = {item.strip().lower() for item in get_settings().bulk_evidence_allowed_extensions.split(",") if item.strip()}
    return configured | {".csv", ".xlsx"}


def add_import_audit_log(db: Session, user: User, batch: EvidenceImportBatch, errors: list[str]) -> None:
    add_audit_log(
        db,
        user_id=user.id,
        entity_type="evidence_import_batch",
        entity_id=batch.id,
        action="evidence_import_batch.created",
        new_value={
            "source_type": batch.source_type,
            "restaurant_id": batch.restaurant_id,
            "stored_files_count": batch.stored_files_count,
            "failed_files_count": batch.failed_files_count,
            "duplicate_files_count": batch.duplicate_files_count,
            "errors": errors,
        },
    )


def visible_batches_statement(db: Session, current_user: User):
    statement = select(EvidenceImportBatch).order_by(EvidenceImportBatch.id.desc())
    if current_user.role == "owner":
        return statement
    from app.core.auth import get_accessible_restaurant_ids

    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if not accessible_ids:
        return statement.where(EvidenceImportBatch.id == -1)
    return statement.where(
        (EvidenceImportBatch.restaurant_id.is_(None) & (EvidenceImportBatch.uploaded_by_user_id == current_user.id))
        | EvidenceImportBatch.restaurant_id.in_(accessible_ids)
    )
