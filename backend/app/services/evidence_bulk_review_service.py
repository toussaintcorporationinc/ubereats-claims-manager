from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, ensure_can_access_restaurant
from app.models import (
    ClaimOrder,
    EvidenceAttachmentDecision,
    EvidenceFile,
    EvidenceImportedFile,
    EvidenceMatchCandidate,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    UberReconciliationResult,
    User,
)
from app.models.domain import EVIDENCE_TYPES, utc_now
from app.schemas.domain import ClaimValidationResponse
from app.services.audit import add_audit_log
from app.services.claim_validation_service import validate_claim_order


@dataclass(frozen=True)
class EvidenceAttachResult:
    decision: EvidenceAttachmentDecision
    evidence_file: EvidenceFile | None
    validation: ClaimValidationResponse | None


def attach_imported_file(
    db: Session,
    current_user: User,
    imported_file: EvidenceImportedFile,
    *,
    candidate_type: str,
    candidate_id: int,
    evidence_type: str,
    decision_reason: str | None = None,
) -> EvidenceAttachResult:
    if evidence_type not in EVIDENCE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid evidence_type")
    order = resolve_candidate_order(db, current_user, candidate_type, candidate_id)
    ensure_can_access_order(db, current_user, order)

    existing = db.scalar(
        select(EvidenceAttachmentDecision).where(
            EvidenceAttachmentDecision.imported_file_id == imported_file.id,
            EvidenceAttachmentDecision.decision == "attached",
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Imported file is already attached")

    evidence_file = EvidenceFile(
        order_id=order.id,
        evidence_type=evidence_type,
        original_filename=imported_file.original_filename,
        storage_path=imported_file.storage_path,
        storage_backend=imported_file.storage_backend,
        mime_type=imported_file.mime_type,
        file_size=imported_file.file_size,
        checksum_sha256=imported_file.checksum_sha256,
        uploaded_by_user_id=current_user.id,
    )
    db.add(evidence_file)
    db.flush()

    decision = EvidenceAttachmentDecision(
        imported_file_id=imported_file.id,
        evidence_file_id=evidence_file.id,
        candidate_type=candidate_type,
        candidate_id=candidate_id,
        decision="attached",
        decided_by_user_id=current_user.id,
        reason=decision_reason,
    )
    db.add(decision)
    complete_related_task(db, current_user, candidate_type, candidate_id, evidence_file)
    validation = validate_claim_order(db, order.id, user_id=current_user.id)
    imported_file.status = "analyzed"
    imported_file.updated_at = utc_now()
    mark_candidates_for_attachment(db, imported_file, candidate_type, candidate_id, current_user.id)

    add_audit_log(
        db,
        entity_type="evidence_imported_file",
        entity_id=imported_file.id,
        action="bulk_evidence.attached",
        user_id=current_user.id,
        new_value={
            "evidence_file_id": evidence_file.id,
            "candidate_type": candidate_type,
            "candidate_id": candidate_id,
            "evidence_type": evidence_type,
            "order_id": order.id,
        },
    )
    db.flush()
    return EvidenceAttachResult(decision=decision, evidence_file=evidence_file, validation=validation)


def reject_candidate(
    db: Session,
    current_user: User,
    candidate: EvidenceMatchCandidate,
    reason: str,
) -> EvidenceMatchCandidate:
    ensure_candidate_access(db, current_user, candidate)
    candidate.status = "rejected"
    candidate.reviewed_by_user_id = current_user.id
    candidate.reviewed_at = utc_now()
    db.add(
        EvidenceAttachmentDecision(
            imported_file_id=candidate.imported_file_id,
            candidate_type=candidate.candidate_type,
            candidate_id=candidate.candidate_id,
            decision="rejected",
            decided_by_user_id=current_user.id,
            reason=reason,
        )
    )
    add_audit_log(
        db,
        entity_type="evidence_match_candidate",
        entity_id=candidate.id,
        action="bulk_evidence.candidate_rejected",
        user_id=current_user.id,
        new_value={"reason": reason},
    )
    return candidate


def ignore_imported_file(
    db: Session,
    current_user: User,
    imported_file: EvidenceImportedFile,
    reason: str,
) -> EvidenceAttachmentDecision:
    ensure_imported_file_access(db, current_user, imported_file)
    imported_file.status = "ignored"
    imported_file.updated_at = utc_now()
    decision = EvidenceAttachmentDecision(
        imported_file_id=imported_file.id,
        candidate_type="claim_order",
        candidate_id=0,
        decision="ignored",
        decided_by_user_id=current_user.id,
        reason=reason,
    )
    db.add(decision)
    add_audit_log(
        db,
        entity_type="evidence_imported_file",
        entity_id=imported_file.id,
        action="bulk_evidence.ignored",
        user_id=current_user.id,
        new_value={"reason": reason},
    )
    return decision


def bulk_accept_high_confidence(
    db: Session,
    current_user: User,
    batch_id: int,
    *,
    min_score,
) -> dict[str, object]:
    files = db.scalars(
        select(EvidenceImportedFile).where(EvidenceImportedFile.batch_id == batch_id).order_by(EvidenceImportedFile.id)
    ).all()
    accepted = 0
    skipped = 0
    errors: list[str] = []
    for imported_file in files:
        candidates = [candidate for candidate in imported_file.match_candidates if candidate.status in {"proposed", "manual_review"}]
        strong = [candidate for candidate in candidates if candidate.match_score >= min_score]
        if len(strong) != 1:
            skipped += 1
            continue
        latest_analysis = latest_analysis_result(imported_file)
        if latest_analysis is None or latest_analysis.detected_evidence_type == "unknown":
            skipped += 1
            continue
        try:
            attach_imported_file(
                db,
                current_user,
                imported_file,
                candidate_type=strong[0].candidate_type,
                candidate_id=strong[0].candidate_id,
                evidence_type=latest_analysis.detected_evidence_type,
                decision_reason="bulk_accept_high_confidence",
            )
            accepted += 1
        except HTTPException as exc:
            skipped += 1
            errors.append(f"file {imported_file.id}: {exc.detail}")
    return {"accepted_count": accepted, "skipped_count": skipped, "errors": errors}


def resolve_candidate_order(db: Session, current_user: User, candidate_type: str, candidate_id: int) -> ClaimOrder:
    if candidate_type == "claim_order":
        order = db.get(ClaimOrder, candidate_id)
    elif candidate_type == "evidence_task":
        task = db.get(EvidenceRequestTask, candidate_id)
        order = task.order if task is not None else None
    elif candidate_type == "customer_refund_dispute":
        dispute = db.get(UberCustomerRefundDispute, candidate_id)
        if dispute is None or dispute.claim_order_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer refund dispute has no linked ClaimOrder")
        order = db.get(ClaimOrder, dispute.claim_order_id)
    elif candidate_type == "reconciliation_result":
        result = db.get(UberReconciliationResult, candidate_id)
        if result is None or result.claim_order_id is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reconciliation result has no linked ClaimOrder")
        order = db.get(ClaimOrder, result.claim_order_id)
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid candidate_type")
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate order not found")
    return order


def complete_related_task(
    db: Session,
    current_user: User,
    candidate_type: str,
    candidate_id: int,
    evidence_file: EvidenceFile,
) -> None:
    task = db.get(EvidenceRequestTask, candidate_id) if candidate_type == "evidence_task" else None
    if task is None:
        task = db.scalar(
            select(EvidenceRequestTask).where(
                EvidenceRequestTask.order_id == evidence_file.order_id,
                EvidenceRequestTask.required_evidence_type == evidence_file.evidence_type,
                EvidenceRequestTask.status.in_(("pending", "uploaded")),
            )
        )
    if task is None:
        return
    previous_status = task.status
    task.status = "completed"
    task.completed_at = utc_now()
    task.completed_by_user_id = current_user.id
    task.last_upload_evidence_id = evidence_file.id
    if task.customer_refund_dispute_id is not None:
        from app.services.customer_refund_dispute_service import sync_requirement_from_evidence_task

        sync_requirement_from_evidence_task(db, task, evidence_file, current_user.id)
    add_audit_log(
        db,
        entity_type="evidence_request_task",
        entity_id=task.id,
        action="evidence_task.completed_by_bulk_import",
        user_id=current_user.id,
        old_value={"status": previous_status},
        new_value={"status": task.status, "evidence_file_id": evidence_file.id},
    )


def mark_candidates_for_attachment(
    db: Session,
    imported_file: EvidenceImportedFile,
    candidate_type: str,
    candidate_id: int,
    user_id: int,
) -> None:
    for candidate in imported_file.match_candidates:
        if candidate.candidate_type == candidate_type and candidate.candidate_id == candidate_id:
            candidate.status = "accepted"
            candidate.reviewed_by_user_id = user_id
            candidate.reviewed_at = utc_now()
        elif candidate.status == "proposed":
            candidate.status = "rejected"
            candidate.reviewed_by_user_id = user_id
            candidate.reviewed_at = utc_now()


def ensure_candidate_access(db: Session, current_user: User, candidate: EvidenceMatchCandidate) -> None:
    if candidate.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, candidate.restaurant_id)
    else:
        ensure_imported_file_access(db, current_user, candidate.imported_file)


def ensure_imported_file_access(db: Session, current_user: User, imported_file: EvidenceImportedFile) -> None:
    if imported_file.batch.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, imported_file.batch.restaurant_id)
    elif current_user.role != "owner" and imported_file.uploaded_by_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Imported evidence access denied")


def latest_analysis_result(imported_file: EvidenceImportedFile):
    if not imported_file.analysis_results:
        return None
    return sorted(imported_file.analysis_results, key=lambda item: item.id)[-1]
