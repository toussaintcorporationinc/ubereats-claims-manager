from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.models import (
    EvidenceAnalysisResult,
    EvidenceImportBatch,
    EvidenceImportedFile,
    EvidenceMatchCandidate,
    User,
)
from app.schemas.domain import (
    EvidenceAttachResponse,
    EvidenceAttachmentDecisionRead,
    EvidenceAnalysisResultRead,
    EvidenceBulkAcceptRequest,
    EvidenceBulkAcceptResponse,
    EvidenceCandidateRejectRequest,
    EvidenceImportAnalyzeRequest,
    EvidenceImportAnalyzeResponse,
    EvidenceImportBatchRead,
    EvidenceImportedFileAttachRequest,
    EvidenceImportedFileDetail,
    EvidenceImportedFileIgnoreRequest,
    EvidenceImportedFileRead,
    EvidenceImportFilesResponse,
    EvidenceImportsResponse,
    EvidenceMatchCandidateRead,
)
from app.services.bulk_evidence_import_service import (
    BulkEvidenceImportError,
    create_multi_file_import,
    create_zip_import,
    resolve_imported_file_path,
    visible_batches_statement,
)
from app.services.evidence_ai_analysis_service import EvidenceAIAnalysisService
from app.services.evidence_bulk_review_service import (
    attach_imported_file,
    bulk_accept_high_confidence,
    ignore_imported_file,
    reject_candidate,
)

router = APIRouter(tags=["evidence-imports"])


@router.post("/v1/evidence-imports", response_model=EvidenceImportBatchRead, status_code=status.HTTP_201_CREATED)
def create_import(
    files: list[UploadFile] = File(...),
    restaurant_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportBatchRead:
    batch = create_multi_file_import(db, current_user, files=files, restaurant_id=restaurant_id)
    return EvidenceImportBatchRead.model_validate(batch)


@router.post("/v1/evidence-imports/zip", response_model=EvidenceImportBatchRead, status_code=status.HTTP_201_CREATED)
def create_zip(
    file: UploadFile = File(...),
    restaurant_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportBatchRead:
    batch = create_zip_import(db, current_user, file=file, restaurant_id=restaurant_id)
    return EvidenceImportBatchRead.model_validate(batch)


@router.get("/v1/evidence-imports", response_model=EvidenceImportsResponse)
def list_imports(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportsResponse:
    batches = db.scalars(visible_batches_statement(db, current_user).limit(limit).offset(offset)).all()
    return EvidenceImportsResponse(
        batches=[EvidenceImportBatchRead.model_validate(batch) for batch in batches],
        limit=limit,
        offset=offset,
    )


@router.get("/v1/evidence-imports/{batch_id}", response_model=EvidenceImportBatchRead)
def get_import(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportBatchRead:
    batch = get_batch_or_404(db, current_user, batch_id)
    return EvidenceImportBatchRead.model_validate(batch)


@router.get("/v1/evidence-imports/{batch_id}/files", response_model=EvidenceImportFilesResponse)
def list_import_files(
    batch_id: int,
    status_filter: str | None = Query(default=None, alias="status"),
    detected_evidence_type: str | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportFilesResponse:
    batch = get_batch_or_404(db, current_user, batch_id)
    statement = select(EvidenceImportedFile).where(EvidenceImportedFile.batch_id == batch.id)
    if status_filter:
        statement = statement.where(EvidenceImportedFile.status == status_filter)
    if detected_evidence_type:
        statement = (
            statement.join(EvidenceAnalysisResult)
            .where(EvidenceAnalysisResult.detected_evidence_type == detected_evidence_type)
            .distinct()
        )
    if needs_review is True:
        statement = statement.where(EvidenceImportedFile.status.in_(("analysis_pending", "analyzed", "failed")))
    statement = statement.order_by(EvidenceImportedFile.id.desc())
    files = db.scalars(statement.limit(limit).offset(offset)).all()
    return EvidenceImportFilesResponse(
        files=[EvidenceImportedFileRead.model_validate(imported_file) for imported_file in files],
        limit=limit,
        offset=offset,
    )


@router.post("/v1/evidence-imports/{batch_id}/analyze", response_model=EvidenceImportAnalyzeResponse)
def analyze_import(
    batch_id: int,
    payload: EvidenceImportAnalyzeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceImportAnalyzeResponse:
    payload = payload or EvidenceImportAnalyzeRequest()
    batch = get_batch_or_404(db, current_user, batch_id)
    result = EvidenceAIAnalysisService().analyze_batch(
        db,
        current_user,
        batch,
        provider=payload.provider,
        limit=payload.limit,
    )
    db.commit()
    db.refresh(batch)
    return EvidenceImportAnalyzeResponse(**result)


@router.post("/v1/evidence-imports/{batch_id}/bulk-accept-high-confidence", response_model=EvidenceBulkAcceptResponse)
def bulk_accept(
    batch_id: int,
    payload: EvidenceBulkAcceptRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceBulkAcceptResponse:
    payload = payload or EvidenceBulkAcceptRequest()
    get_batch_or_404(db, current_user, batch_id)
    result = bulk_accept_high_confidence(db, current_user, batch_id, min_score=Decimal(str(payload.min_score)))
    db.commit()
    return EvidenceBulkAcceptResponse(**result)


@router.get("/v1/evidence-imported-files/{file_id}", response_model=EvidenceImportedFileDetail)
def get_imported_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportedFileDetail:
    imported_file = get_imported_file_or_404(db, current_user, file_id)
    analyses = sorted(imported_file.analysis_results, key=lambda item: item.id, reverse=True)
    candidates = sorted(imported_file.match_candidates, key=lambda item: item.match_score, reverse=True)
    return EvidenceImportedFileDetail(
        file=EvidenceImportedFileRead.model_validate(imported_file),
        analysis_results=[EvidenceAnalysisResultRead.model_validate(item) for item in analyses],
        candidates=[EvidenceMatchCandidateRead.model_validate(item) for item in candidates],
    )


@router.get("/v1/evidence-imported-files/{file_id}/preview")
def preview_imported_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    imported_file = get_imported_file_or_404(db, current_user, file_id)
    try:
        path = resolve_imported_file_path(imported_file)
    except BulkEvidenceImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(path, media_type=imported_file.mime_type, filename=imported_file.original_filename)


@router.post("/v1/evidence-imported-files/{file_id}/attach", response_model=EvidenceAttachResponse)
def attach_file(
    file_id: int,
    payload: EvidenceImportedFileAttachRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceAttachResponse:
    imported_file = get_imported_file_or_404(db, current_user, file_id)
    result = attach_imported_file(
        db,
        current_user,
        imported_file,
        candidate_type=payload.candidate_type,
        candidate_id=payload.candidate_id,
        evidence_type=payload.evidence_type,
        decision_reason="manual_bulk_review",
    )
    db.commit()
    db.refresh(result.decision)
    return EvidenceAttachResponse(
        decision=EvidenceAttachmentDecisionRead.model_validate(result.decision),
        evidence_file=result.evidence_file,
        validation=result.validation,
    )


@router.post("/v1/evidence-match-candidates/{candidate_id}/accept", response_model=EvidenceAttachResponse)
def accept_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceAttachResponse:
    candidate = get_candidate_or_404(db, current_user, candidate_id)
    analysis = latest_analysis(candidate.imported_file)
    if analysis is None or analysis.detected_evidence_type == "unknown":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate requires a detected evidence type")
    result = attach_imported_file(
        db,
        current_user,
        candidate.imported_file,
        candidate_type=candidate.candidate_type,
        candidate_id=candidate.candidate_id,
        evidence_type=analysis.detected_evidence_type,
        decision_reason="candidate_accept",
    )
    db.commit()
    db.refresh(result.decision)
    return EvidenceAttachResponse(
        decision=EvidenceAttachmentDecisionRead.model_validate(result.decision),
        evidence_file=result.evidence_file,
        validation=result.validation,
    )


@router.post("/v1/evidence-match-candidates/{candidate_id}/reject", response_model=EvidenceMatchCandidateRead)
def reject(
    candidate_id: int,
    payload: EvidenceCandidateRejectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceMatchCandidateRead:
    candidate = get_candidate_or_404(db, current_user, candidate_id)
    candidate = reject_candidate(db, current_user, candidate, payload.reason)
    db.commit()
    db.refresh(candidate)
    return EvidenceMatchCandidateRead.model_validate(candidate)


@router.post("/v1/evidence-imported-files/{file_id}/ignore", response_model=EvidenceAttachmentDecisionRead)
def ignore_file(
    file_id: int,
    payload: EvidenceImportedFileIgnoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceAttachmentDecisionRead:
    imported_file = get_imported_file_or_404(db, current_user, file_id)
    decision = ignore_imported_file(db, current_user, imported_file, payload.reason)
    db.commit()
    db.refresh(decision)
    return EvidenceAttachmentDecisionRead.model_validate(decision)


def get_batch_or_404(db: Session, current_user: User, batch_id: int) -> EvidenceImportBatch:
    batch = db.get(EvidenceImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence import batch not found")
    if batch.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, batch.restaurant_id)
    elif current_user.role != "owner" and batch.uploaded_by_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Evidence import batch access denied")
    return batch


def get_imported_file_or_404(db: Session, current_user: User, file_id: int) -> EvidenceImportedFile:
    imported_file = db.get(EvidenceImportedFile, file_id)
    if imported_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence imported file not found")
    get_batch_or_404(db, current_user, imported_file.batch_id)
    return imported_file


def get_candidate_or_404(db: Session, current_user: User, candidate_id: int) -> EvidenceMatchCandidate:
    candidate = db.get(EvidenceMatchCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence match candidate not found")
    get_imported_file_or_404(db, current_user, candidate.imported_file_id)
    if candidate.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, candidate.restaurant_id)
    return candidate


def latest_analysis(imported_file: EvidenceImportedFile) -> EvidenceAnalysisResult | None:
    if not imported_file.analysis_results:
        return None
    return sorted(imported_file.analysis_results, key=lambda item: item.id)[-1]
