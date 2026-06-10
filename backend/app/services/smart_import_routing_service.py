from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.models import SmartImportPreviewBatch, SmartImportPreviewFile, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.bulk_evidence_import_service import create_multi_file_import, create_zip_import
from app.services.smart_import_classifier_service import resolve_preview_file_path
from app.services.uber_reporting_import_service import REPORT_TYPES, create_uber_reporting_preview_from_content


@dataclass(frozen=True)
class SmartImportDecision:
    file_id: int
    action: str | None = None
    report_type: str | None = None
    restaurant_id: int | None = None


def route_smart_import_preview(
    db: Session,
    current_user: User,
    batch: SmartImportPreviewBatch,
    decisions: list[SmartImportDecision],
) -> dict[str, Any]:
    ensure_batch_confirmable(db, current_user, batch)
    decision_map = {decision.file_id: decision for decision in decisions}
    files = sorted(batch.files, key=lambda item: item.id)

    routed_files: list[dict[str, Any]] = []
    manual_review_files: list[dict[str, Any]] = []
    ignored_files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    evidence_groups: dict[int | None, list[tuple[SmartImportPreviewFile, SmartImportDecision]]] = {}

    for preview_file in files:
        decision = decision_map.get(preview_file.id) or SmartImportDecision(file_id=preview_file.id)
        action = decision.action or preview_file.recommended_action
        try:
            if action == "import_uber_reporting":
                routed_files.append(route_uber_reporting_file(db, current_user, preview_file, decision))
            elif action == "import_evidence_bulk":
                if preview_file.file_type == "zip":
                    routed_files.append(route_evidence_zip_file(db, current_user, preview_file, decision))
                else:
                    evidence_groups.setdefault(decision.restaurant_id, []).append((preview_file, decision))
            elif action == "manual_review":
                preview_file.status = "manual_review"
                preview_file.destination_type = "manual_review"
                preview_file.destination_url = f"/smart-import?preview={batch.id}"
                manual_review_files.append(result_payload(preview_file, "manual_review"))
            elif action == "ignore":
                preview_file.status = "ignored"
                preview_file.destination_type = "ignored"
                ignored_files.append(result_payload(preview_file, "ignore"))
                add_audit_log(
                    db,
                    entity_type="smart_import_preview_file",
                    entity_id=preview_file.id,
                    action="smart_import_file.ignored",
                    user_id=current_user.id,
                    new_value={"filename": preview_file.original_filename},
                )
            else:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported smart import action: {action}")
        except HTTPException as exc:
            preview_file.status = "failed"
            preview_file.error_message = str(exc.detail)
            errors.append({"file_id": preview_file.id, "original_filename": preview_file.original_filename, "error": exc.detail})

    for restaurant_id, group in evidence_groups.items():
        try:
            routed_files.extend(route_evidence_files_group(db, current_user, group, restaurant_id))
        except HTTPException as exc:
            for preview_file, _decision in group:
                preview_file.status = "failed"
                preview_file.error_message = str(exc.detail)
                errors.append({"file_id": preview_file.id, "original_filename": preview_file.original_filename, "error": exc.detail})

    batch.status = "confirmed"
    batch.confirmed_at = utc_now()
    add_audit_log(
        db,
        entity_type="smart_import_preview_batch",
        entity_id=batch.id,
        action="smart_import_confirm_routed",
        user_id=current_user.id,
        new_value={
            "routed_files": len(routed_files),
            "manual_review_files": len(manual_review_files),
            "ignored_files": len(ignored_files),
            "errors": len(errors),
        },
    )
    db.commit()
    db.refresh(batch)
    return {
        "batch_preview_id": batch.id,
        "status": batch.status,
        "routed_files": routed_files,
        "manual_review_files": manual_review_files,
        "ignored_files": ignored_files,
        "errors": errors,
    }


def ensure_batch_confirmable(db: Session, current_user: User, batch: SmartImportPreviewBatch) -> None:
    if batch.uploaded_by_user_id != current_user.id and current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Smart import preview access denied")
    if batch.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Smart import preview already confirmed")
    if batch.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Smart import preview cancelled")
    if batch.expires_at and batch.expires_at < _aware_utc_now(batch.expires_at):
        batch.status = "expired"
        for preview_file in batch.files:
            if preview_file.status == "previewed":
                preview_file.status = "expired"
        db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Smart import preview expired")


def _aware_utc_now(reference: datetime) -> datetime:
    now = utc_now()
    if reference.tzinfo is None:
        return now.replace(tzinfo=None)
    return now


def route_uber_reporting_file(
    db: Session,
    current_user: User,
    preview_file: SmartImportPreviewFile,
    decision: SmartImportDecision,
) -> dict[str, Any]:
    report_type = decision.report_type or preview_file.detected_report_type or "combined_report"
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported Uber report type")
    content = resolve_preview_file_path(preview_file).read_bytes()
    batch = create_uber_reporting_preview_from_content(
        db,
        current_user,
        filename=preview_file.original_filename,
        content=content,
        report_type=report_type,
    )
    preview_file.status = "routed"
    preview_file.destination_type = "uber_reporting_batch"
    preview_file.destination_id = batch.id
    preview_file.destination_url = f"/uber/reporting/{batch.id}"
    add_audit_log(
        db,
        entity_type="smart_import_preview_file",
        entity_id=preview_file.id,
        action="smart_import_file.routed_uber_reporting",
        user_id=current_user.id,
        new_value={"uber_reporting_batch_id": batch.id, "report_type": report_type},
    )
    return result_payload(preview_file, "import_uber_reporting")


def route_evidence_zip_file(
    db: Session,
    current_user: User,
    preview_file: SmartImportPreviewFile,
    decision: SmartImportDecision,
) -> dict[str, Any]:
    content = resolve_preview_file_path(preview_file).read_bytes()
    upload = upload_from_bytes(preview_file.original_filename, content, preview_file.mime_type)
    batch = create_zip_import(db, current_user, file=upload, restaurant_id=decision.restaurant_id)
    preview_file.status = "routed"
    preview_file.destination_type = "evidence_import_batch"
    preview_file.destination_id = batch.id
    preview_file.destination_url = f"/evidence-imports/{batch.id}"
    add_audit_log(
        db,
        entity_type="smart_import_preview_file",
        entity_id=preview_file.id,
        action="smart_import_file.routed_evidence_zip",
        user_id=current_user.id,
        new_value={"evidence_import_batch_id": batch.id, "restaurant_id": decision.restaurant_id},
    )
    return result_payload(preview_file, "import_evidence_bulk")


def route_evidence_files_group(
    db: Session,
    current_user: User,
    group: list[tuple[SmartImportPreviewFile, SmartImportDecision]],
    restaurant_id: int | None,
) -> list[dict[str, Any]]:
    uploads = [
        upload_from_bytes(preview_file.original_filename, resolve_preview_file_path(preview_file).read_bytes(), preview_file.mime_type)
        for preview_file, _decision in group
    ]
    batch = create_multi_file_import(db, current_user, files=uploads, restaurant_id=restaurant_id)
    results: list[dict[str, Any]] = []
    for preview_file, _decision in group:
        preview_file.status = "routed"
        preview_file.destination_type = "evidence_import_batch"
        preview_file.destination_id = batch.id
        preview_file.destination_url = f"/evidence-imports/{batch.id}"
        add_audit_log(
            db,
            entity_type="smart_import_preview_file",
            entity_id=preview_file.id,
            action="smart_import_file.routed_evidence_bulk",
            user_id=current_user.id,
            new_value={"evidence_import_batch_id": batch.id, "restaurant_id": restaurant_id},
        )
        results.append(result_payload(preview_file, "import_evidence_bulk"))
    return results


def upload_from_bytes(filename: str, content: bytes, mime_type: str | None) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers=Headers({"content-type": mime_type or "application/octet-stream"}),
    )


def result_payload(preview_file: SmartImportPreviewFile, action: str) -> dict[str, Any]:
    return {
        "file_id": preview_file.id,
        "original_filename": preview_file.original_filename,
        "action": action,
        "destination_type": preview_file.destination_type,
        "destination_id": preview_file.destination_id,
        "destination_url": preview_file.destination_url,
    }


def cancel_smart_import_preview(db: Session, current_user: User, batch: SmartImportPreviewBatch) -> SmartImportPreviewBatch:
    if batch.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Smart import preview already confirmed")
    if batch.uploaded_by_user_id != current_user.id and current_user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Smart import preview access denied")
    batch.status = "cancelled"
    for preview_file in batch.files:
        if preview_file.status == "previewed":
            preview_file.status = "ignored"
    add_audit_log(
        db,
        entity_type="smart_import_preview_batch",
        entity_id=batch.id,
        action="smart_import_preview.cancelled",
        user_id=current_user.id,
        new_value={"status": "cancelled"},
    )
    db.commit()
    db.refresh(batch)
    return batch
