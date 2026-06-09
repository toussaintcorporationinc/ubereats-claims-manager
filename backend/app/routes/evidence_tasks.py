from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.models import ClaimOrder, EvidenceRequestTask, EvidenceUploadLink, User
from app.schemas.domain import (
    EvidenceRequestPriority,
    EvidenceRequestRecalculateRequest,
    EvidenceRequestRecalculateResponse,
    EvidenceRequestSkipRequest,
    EvidenceRequestTaskRead,
    EvidenceRequestTaskStatus,
    EvidenceRequestTasksResponse,
    EvidenceRequestTaskSummary,
    EvidenceTaskUploadResponse,
    EvidenceType,
    EvidenceUploadLinkCreateRequest,
    EvidenceUploadLinkCreateResponse,
    EvidenceUploadLinkRead,
    PublicEvidenceUploadLinkRead,
)
from app.services.evidence_request_service import (
    complete_evidence_task,
    create_upload_link,
    get_valid_upload_link_by_token,
    recalculate_evidence_tasks,
    revoke_upload_link,
    skip_evidence_task,
    upload_evidence_for_task,
    upload_evidence_with_link,
)

router = APIRouter(tags=["evidence-tasks"])


@router.post("/v1/evidence-tasks/recalculate", response_model=EvidenceRequestRecalculateResponse)
def recalculate_tasks(
    payload: EvidenceRequestRecalculateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    result = recalculate_evidence_tasks(
        db,
        current_user,
        restaurant_id=payload.restaurant_id,
        order_id=payload.order_id,
        dry_run=payload.dry_run,
    )
    db.commit()
    return result


@router.get("/v1/evidence-tasks", response_model=EvidenceRequestTasksResponse)
def list_tasks(
    restaurant_id: int | None = Query(default=None),
    status_filter: EvidenceRequestTaskStatus | None = Query(default=None, alias="status"),
    required_evidence_type: EvidenceType | None = Query(default=None),
    priority: EvidenceRequestPriority | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceRequestTasksResponse:
    statement = select(EvidenceRequestTask).join(ClaimOrder).order_by(EvidenceRequestTask.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return EvidenceRequestTasksResponse(tasks=[], limit=limit, offset=offset)
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
    if status_filter:
        statement = statement.where(EvidenceRequestTask.status == status_filter)
    if required_evidence_type:
        statement = statement.where(EvidenceRequestTask.required_evidence_type == required_evidence_type)
    if priority:
        statement = statement.where(EvidenceRequestTask.priority == priority)
    if assigned_to_me:
        statement = statement.where(EvidenceRequestTask.assigned_to_user_id == current_user.id)

    tasks = db.scalars(statement.offset(offset).limit(limit)).all()
    return EvidenceRequestTasksResponse(tasks=[build_task_summary(task) for task in tasks], limit=limit, offset=offset)


@router.get("/v1/evidence-tasks/{task_id}", response_model=EvidenceRequestTaskRead)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceRequestTask:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    return task


@router.post("/v1/evidence-tasks/{task_id}/upload", response_model=EvidenceTaskUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_task_evidence(
    task_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceTaskUploadResponse:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    result = upload_evidence_for_task(db, task, file, user_id=current_user.id)
    db.commit()
    db.refresh(result.task)
    db.refresh(result.evidence_file)
    return EvidenceTaskUploadResponse(task=result.task, evidence_file=result.evidence_file, validation=result.validation)


@router.post("/v1/evidence-tasks/{task_id}/skip", response_model=EvidenceRequestTaskRead)
def skip_task(
    task_id: int,
    payload: EvidenceRequestSkipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceRequestTask:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    task = skip_evidence_task(db, task, current_user, payload.skip_reason)
    db.commit()
    db.refresh(task)
    return task


@router.post("/v1/evidence-tasks/{task_id}/complete", response_model=EvidenceRequestTaskRead)
def complete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceRequestTask:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    task = complete_evidence_task(db, task, current_user)
    db.commit()
    db.refresh(task)
    return task


@router.post("/v1/evidence-tasks/{task_id}/upload-link", response_model=EvidenceUploadLinkCreateResponse, status_code=status.HTTP_201_CREATED)
def create_task_upload_link(
    task_id: int,
    payload: EvidenceUploadLinkCreateRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceUploadLinkCreateResponse:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    payload = payload or EvidenceUploadLinkCreateRequest()
    upload_link, token, upload_url = create_upload_link(
        db,
        task,
        current_user,
        expires_in_hours=payload.expires_in_hours,
        max_uses=payload.max_uses,
    )
    db.commit()
    db.refresh(upload_link)
    link_read = EvidenceUploadLinkRead.model_validate(upload_link)
    return EvidenceUploadLinkCreateResponse(**link_read.model_dump(), token=token, upload_url=upload_url)


@router.get("/v1/evidence-upload-links/{token}", response_model=PublicEvidenceUploadLinkRead)
def get_public_upload_link(
    token: str,
    db: Session = Depends(get_db),
) -> PublicEvidenceUploadLinkRead:
    upload_link = get_valid_upload_link_by_token(db, token)
    db.commit()
    return build_public_link_response(upload_link)


@router.post("/v1/evidence-upload-links/{token}/upload", response_model=EvidenceTaskUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_public_link_evidence(
    token: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> EvidenceTaskUploadResponse:
    upload_link = get_valid_upload_link_by_token(db, token)
    result = upload_evidence_with_link(db, upload_link, file)
    db.commit()
    db.refresh(result.task)
    db.refresh(result.evidence_file)
    return EvidenceTaskUploadResponse(task=result.task, evidence_file=result.evidence_file, validation=result.validation)


@router.post("/v1/evidence-upload-links/{link_id}/revoke", response_model=EvidenceUploadLinkRead)
def revoke_public_upload_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceUploadLink:
    upload_link = db.get(EvidenceUploadLink, link_id)
    if upload_link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence upload link not found")
    ensure_can_access_order(db, current_user, upload_link.task.order)
    upload_link = revoke_upload_link(db, upload_link, current_user)
    db.commit()
    db.refresh(upload_link)
    return upload_link


def get_task_or_404(task_id: int, db: Session) -> EvidenceRequestTask:
    task = db.get(EvidenceRequestTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence task not found")
    return task


def build_task_summary(task: EvidenceRequestTask) -> EvidenceRequestTaskSummary:
    order = task.order
    return EvidenceRequestTaskSummary(
        id=task.id,
        order_id=task.order_id,
        restaurant_id=order.restaurant_id,
        restaurant_name=order.restaurant.name,
        uber_order_number=order.uber_order_number,
        order_amount=order.order_amount,
        currency=order.currency,
        claim_status=order.status,
        task_type=task.task_type,
        required_evidence_type=task.required_evidence_type,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        title=task.title,
        description=task.description,
        reason=task.reason,
        reconciliation_result_id=task.reconciliation_result_id,
        customer_refund_dispute_id=task.customer_refund_dispute_id,
        last_upload_evidence_id=task.last_upload_evidence_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def build_public_link_response(upload_link: EvidenceUploadLink) -> PublicEvidenceUploadLinkRead:
    task = upload_link.task
    order = task.order
    return PublicEvidenceUploadLinkRead(
        id=upload_link.id,
        task_id=task.id,
        order_id=order.id,
        restaurant_name=order.restaurant.name,
        uber_order_number=mask_order_number(order.uber_order_number),
        task_type=task.task_type,
        required_evidence_type=task.required_evidence_type,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        title=task.title,
        description=task.description,
        reason=task.reason,
        expires_at=upload_link.expires_at,
        max_uses=upload_link.max_uses,
        use_count=upload_link.use_count,
    )


def mask_order_number(order_number: str) -> str:
    if len(order_number) <= 8:
        return "****"
    return f"{order_number[:4]}...{order_number[-4:]}"
