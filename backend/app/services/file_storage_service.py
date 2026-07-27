from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from fastapi import UploadFile, status

from app.core.config import get_settings
from app.models import ClaimOrder, EvidenceFile

ALLOWED_EVIDENCE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

ALLOWED_EVIDENCE_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
}

CHUNK_SIZE = 1024 * 1024


class FileStorageError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class StoredEvidenceFile:
    storage_backend: str
    storage_path: str
    original_filename: str
    mime_type: str | None
    file_size: int
    checksum_sha256: str


def ensure_evidence_storage() -> Path:
    settings = get_settings()
    if settings.evidence_storage_backend != "local":
        raise FileStorageError("Only local evidence storage is available in V1")

    root = settings.evidence_storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_evidence_upload(order: ClaimOrder, upload_file: UploadFile) -> StoredEvidenceFile:
    return _store_evidence_stream(
        order,
        original_filename=upload_file.filename,
        mime_type=upload_file.content_type or None,
        source=upload_file.file,
    )


def store_evidence_bytes(
    order: ClaimOrder,
    *,
    original_filename: str,
    mime_type: str | None,
    content: bytes,
) -> StoredEvidenceFile:
    return _store_evidence_stream(
        order,
        original_filename=original_filename,
        mime_type=mime_type,
        source=BytesIO(content),
    )


def _store_evidence_stream(
    order: ClaimOrder,
    *,
    original_filename: str | None,
    mime_type: str | None,
    source: BinaryIO,
) -> StoredEvidenceFile:
    settings = get_settings()
    if settings.evidence_storage_backend != "local":
        raise FileStorageError("Only local evidence storage is available in V1")

    original_filename = _safe_original_filename(original_filename)
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EVIDENCE_EXTENSIONS:
        raise FileStorageError("Evidence file extension is not allowed")

    if mime_type and mime_type not in ALLOWED_EVIDENCE_MIME_TYPES:
        raise FileStorageError("Evidence file MIME type is not allowed")

    storage_root = ensure_evidence_storage()
    relative_dir = Path(f"restaurant_{order.restaurant_id}") / f"order_{order.id}"
    target_dir = storage_root / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    internal_filename = f"{uuid4().hex}{extension}"
    relative_path = relative_dir / internal_filename
    target_path = storage_root / relative_path
    temporary_path = target_path.with_suffix(f"{target_path.suffix}.tmp")

    max_size = settings.max_evidence_file_size_mb * 1024 * 1024
    digest = sha256()
    file_size = 0

    try:
        with temporary_path.open("wb") as output_file:
            while chunk := source.read(CHUNK_SIZE):
                file_size += len(chunk)
                if file_size > max_size:
                    raise FileStorageError("Evidence file is too large")
                digest.update(chunk)
                output_file.write(chunk)

        if file_size == 0:
            raise FileStorageError("Evidence file cannot be empty")

        temporary_path.replace(target_path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        if target_path.exists():
            target_path.unlink()
        raise

    return StoredEvidenceFile(
        storage_backend=settings.evidence_storage_backend,
        storage_path=relative_path.as_posix(),
        original_filename=original_filename,
        mime_type=mime_type,
        file_size=file_size,
        checksum_sha256=digest.hexdigest(),
    )


def resolve_evidence_path(evidence_file: EvidenceFile) -> Path:
    if evidence_file.storage_backend != "local":
        raise FileStorageError("Only local evidence storage is available in V1", status.HTTP_404_NOT_FOUND)

    storage_root = ensure_evidence_storage().resolve()
    target_path = (storage_root / evidence_file.storage_path).resolve()
    if not target_path.is_relative_to(storage_root):
        raise FileStorageError("Evidence storage path is invalid", status.HTTP_404_NOT_FOUND)
    if not target_path.exists() or not target_path.is_file():
        raise FileStorageError("Evidence file is missing from storage", status.HTTP_404_NOT_FOUND)
    return target_path


def _safe_original_filename(filename: str | None) -> str:
    if not filename:
        raise FileStorageError("Evidence filename is required")
    original_filename = Path(filename).name.strip()
    if not original_filename or original_filename in {".", ".."}:
        raise FileStorageError("Evidence filename is invalid")
    return original_filename
