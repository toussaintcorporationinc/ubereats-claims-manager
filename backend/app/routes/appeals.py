from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, require_owner, require_owner_or_manager
from app.core.database import get_db
from app.models import AppealAttempt, AppealWorkflow, RefusalAnalysis, User
from app.schemas.domain import (
    AppealAttemptRead,
    AppealCreateDraftRequest,
    AppealDetailResponse,
    AppealManualCloseRequest,
    AppealPauseRequest,
    AppealRecalculateRequest,
    AppealRecalculateResponse,
    AppealWorkflowRead,
    AppealWorkflowStatus,
    AppealWorkflowSummary,
    AppealsResponse,
    EmailDraftRead,
    EvidenceRequestTaskSummary,
    RefusalAnalysisRead,
)
from app.services.appeal_workflow_service import (
    AppealWorkflowError,
    accessible_workflow_statement,
    create_appeal_draft,
    create_appeal_gmail_draft,
    create_refusal_analysis,
    email_history_for_workflow,
    evidence_tasks_for_workflow,
    mark_appeal_sent,
    manual_close_workflow,
    pause_workflow,
    recalculate_appeal_workflows,
    reopen_workflow,
    workflow_amount,
    workflow_currency,
    workflow_order_number,
    workflow_restaurant_name,
)

router = APIRouter(prefix="/v1/appeals", tags=["appeals"])


@router.get("", response_model=AppealsResponse)
def list_appeals(
    restaurant_id: int | None = Query(default=None),
    status_filter: AppealWorkflowStatus | None = Query(default=None, alias="status"),
    case_type: str | None = Query(default=None),
    next_action_type: str | None = Query(default=None),
    min_refusal_count: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealsResponse:
    statement = accessible_workflow_statement(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(AppealWorkflow.restaurant_id == restaurant_id)
    if status_filter:
        statement = statement.where(AppealWorkflow.status == status_filter)
    if case_type:
        statement = statement.where(AppealWorkflow.case_type == case_type)
    if next_action_type:
        statement = statement.where(AppealWorkflow.next_action_type == next_action_type)
    if min_refusal_count is not None:
        statement = statement.where(AppealWorkflow.refusal_count >= min_refusal_count)
    workflows = db.scalars(statement.limit(limit).offset(offset)).all()
    return AppealsResponse(
        workflows=[build_workflow_summary(db, workflow) for workflow in workflows],
        limit=limit,
        offset=offset,
    )


@router.get("/{workflow_id}", response_model=AppealDetailResponse)
def get_appeal(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealDetailResponse:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    return build_workflow_detail(db, workflow)


@router.post("/recalculate", response_model=AppealRecalculateResponse)
def recalculate_appeals(
    payload: AppealRecalculateRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealRecalculateResponse:
    payload = payload or AppealRecalculateRequest()
    try:
        result = recalculate_appeal_workflows(db, current_user, restaurant_id=payload.restaurant_id)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    return AppealRecalculateResponse(**result.__dict__)


@router.post("/{workflow_id}/analyze-refusal", response_model=RefusalAnalysisRead, status_code=status.HTTP_201_CREATED)
def analyze_refusal(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> RefusalAnalysisRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    try:
        analysis = create_refusal_analysis(db, workflow=workflow, user=current_user)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(analysis)
    return RefusalAnalysisRead.model_validate(analysis)


@router.post("/{workflow_id}/create-draft", response_model=AppealAttemptRead, status_code=status.HTTP_201_CREATED)
def create_draft(
    workflow_id: int,
    payload: AppealCreateDraftRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealAttemptRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    payload = payload or AppealCreateDraftRequest()
    try:
        attempt = create_appeal_draft(db, workflow=workflow, user=current_user, appeal_type=payload.appeal_type)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(attempt)
    return AppealAttemptRead.model_validate(attempt)


@router.post("/{workflow_id}/create-gmail-draft", response_model=AppealAttemptRead, status_code=status.HTTP_201_CREATED)
def create_gmail_draft(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealAttemptRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    try:
        attempt = create_appeal_gmail_draft(db, workflow=workflow, user=current_user)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(attempt)
    return AppealAttemptRead.model_validate(attempt)


@router.post("/{workflow_id}/mark-sent", response_model=AppealAttemptRead)
def mark_sent(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealAttemptRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    try:
        attempt = mark_appeal_sent(db, workflow=workflow, user=current_user)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(attempt)
    return AppealAttemptRead.model_validate(attempt)


@router.post("/{workflow_id}/pause", response_model=AppealWorkflowRead)
def pause(
    workflow_id: int,
    payload: AppealPauseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AppealWorkflowRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    try:
        workflow = pause_workflow(db, workflow=workflow, user=current_user, reason=payload.reason)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(workflow)
    return AppealWorkflowRead.model_validate(workflow)


@router.post("/{workflow_id}/manual-close", response_model=AppealWorkflowRead)
def manual_close(
    workflow_id: int,
    payload: AppealManualCloseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> AppealWorkflowRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    try:
        workflow = manual_close_workflow(db, workflow=workflow, user=current_user, reason=payload.reason)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(workflow)
    return AppealWorkflowRead.model_validate(workflow)


@router.post("/{workflow_id}/reopen", response_model=AppealWorkflowRead)
def reopen(
    workflow_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> AppealWorkflowRead:
    workflow = get_workflow_or_404(db, current_user, workflow_id)
    try:
        workflow = reopen_workflow(db, workflow=workflow, user=current_user)
    except AppealWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(workflow)
    return AppealWorkflowRead.model_validate(workflow)


def get_workflow_or_404(db: Session, current_user: User, workflow_id: int) -> AppealWorkflow:
    workflow = db.get(AppealWorkflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal workflow not found")
    ensure_can_access_restaurant(db, current_user, workflow.restaurant_id)
    return workflow


def build_workflow_summary(db: Session, workflow: AppealWorkflow) -> AppealWorkflowSummary:
    return AppealWorkflowSummary(
        id=workflow.id,
        case_type=workflow.case_type,
        case_id=workflow.case_id,
        restaurant_id=workflow.restaurant_id,
        restaurant_name=workflow_restaurant_name(db, workflow),
        uber_order_number=workflow_order_number(workflow),
        amount=Decimal(str(workflow_amount(workflow))),
        currency=workflow_currency(workflow),
        status=workflow.status,
        next_action_type=workflow.next_action_type,
        next_action_at=workflow.next_action_at,
        refusal_count=workflow.refusal_count,
        appeal_attempt_count=workflow.appeal_attempt_count,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def build_workflow_detail(db: Session, workflow: AppealWorkflow) -> AppealDetailResponse:
    from app.routes.evidence_tasks import build_task_summary

    attempts = db.scalars(
        select(AppealAttempt)
        .where(AppealAttempt.workflow_id == workflow.id)
        .order_by(AppealAttempt.id.desc())
    ).all()
    analyses = db.scalars(
        select(RefusalAnalysis)
        .where(RefusalAnalysis.workflow_id == workflow.id)
        .order_by(RefusalAnalysis.id.desc())
    ).all()
    return AppealDetailResponse(
        workflow=AppealWorkflowRead.model_validate(workflow),
        case_summary=build_case_summary(db, workflow),
        attempts=[AppealAttemptRead.model_validate(attempt) for attempt in attempts],
        refusal_analyses=[RefusalAnalysisRead.model_validate(analysis) for analysis in analyses],
        evidence_tasks=[
            EvidenceRequestTaskSummary.model_validate(build_task_summary(task))
            for task in evidence_tasks_for_workflow(db, workflow)
        ],
        email_history=[EmailDraftRead.model_validate(draft) for draft in email_history_for_workflow(db, workflow)],
    )


def build_case_summary(db: Session, workflow: AppealWorkflow) -> dict[str, object]:
    return {
        "case_type": workflow.case_type,
        "case_id": workflow.case_id,
        "restaurant_id": workflow.restaurant_id,
        "restaurant_name": workflow_restaurant_name(db, workflow),
        "uber_order_number": workflow_order_number(workflow),
        "amount": workflow_amount(workflow),
        "currency": workflow_currency(workflow),
        "status": related_case_status(workflow),
        "link_url": related_case_url(workflow),
    }


def related_case_status(workflow: AppealWorkflow) -> str | None:
    if workflow.claim_order is not None:
        return workflow.claim_order.status
    if workflow.customer_refund_dispute is not None:
        return workflow.customer_refund_dispute.status
    if workflow.reconciliation_result is not None:
        return workflow.reconciliation_result.status
    return None


def related_case_url(workflow: AppealWorkflow) -> str:
    if workflow.claim_order_id is not None:
        return f"/orders/{workflow.claim_order_id}"
    if workflow.customer_refund_dispute_id is not None:
        return f"/customer-refunds/{workflow.customer_refund_dispute_id}"
    if workflow.reconciliation_result_id is not None:
        return f"/uber/reconciliation/results/{workflow.reconciliation_result_id}"
    return "/recovery"
