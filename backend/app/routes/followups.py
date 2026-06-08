from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner_or_manager
from app.core.config import get_settings
from app.core.database import get_db
from app.models import ClaimOrder, FollowUpTask, Restaurant, User
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.schemas.domain import (
    FollowUpRecalculateRequest,
    FollowUpRecalculateResponse,
    FollowUpSkipRequest,
    FollowUpTaskRead,
    FollowUpTaskSummary,
    FollowUpsResponse,
)
from app.services.audit import add_audit_log
from app.services.email_draft_service import EmailDraftBusinessError, EmailDraftNotFoundError, create_email_draft
from app.services.email_provider import EmailProvider, EmailProviderError
from app.services.followup_policy_service import (
    FOLLOWUP_DRAFT_TYPES,
    FOLLOWUP_ELIGIBLE_STATUSES,
    FollowUpPolicyService,
    apply_followup_completion_effects,
)

router = APIRouter(prefix="/v1/followups", tags=["followups"])


@router.get("/due", response_model=FollowUpsResponse)
def list_due_followups(
    restaurant_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    task_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpsResponse:
    statement = (
        select(FollowUpTask, ClaimOrder, Restaurant)
        .join(ClaimOrder, FollowUpTask.order_id == ClaimOrder.id)
        .join(Restaurant, ClaimOrder.restaurant_id == Restaurant.id)
        .order_by(FollowUpTask.due_at.asc(), FollowUpTask.id.asc())
    )
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return FollowUpsResponse(tasks=[], limit=limit, offset=offset)
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
    if status_filter:
        statement = statement.where(FollowUpTask.status == status_filter)
    if task_type:
        statement = statement.where(FollowUpTask.task_type == task_type)

    rows = db.execute(statement.limit(limit).offset(offset)).all()
    return FollowUpsResponse(
        tasks=[build_followup_summary(task, order, restaurant) for task, order, restaurant in rows],
        limit=limit,
        offset=offset,
    )


@router.post("/recalculate", response_model=FollowUpRecalculateResponse)
def recalculate_followups(
    payload: FollowUpRecalculateRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> FollowUpRecalculateResponse:
    request_payload = payload or FollowUpRecalculateRequest()
    statement = select(ClaimOrder).where(ClaimOrder.status.in_(FOLLOWUP_ELIGIBLE_STATUSES))
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if request_payload.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, request_payload.restaurant_id)
        statement = statement.where(ClaimOrder.restaurant_id == request_payload.restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return FollowUpRecalculateResponse(created_tasks=0, skipped_orders=0, manual_review_orders=0, errors=[])
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    result = FollowUpPolicyService().recalculate(
        db,
        current_user,
        statement.order_by(ClaimOrder.id),
        dry_run=request_payload.dry_run,
    )
    add_audit_log(
        db,
        entity_type="followup_task",
        entity_id=current_user.id,
        action="followup_task.recalculate",
        user_id=current_user.id,
        new_value={
            "restaurant_id": request_payload.restaurant_id,
            "dry_run": request_payload.dry_run,
            "created_tasks": result.created_tasks,
            "skipped_orders": result.skipped_orders,
            "manual_review_orders": result.manual_review_orders,
            "errors": result.errors,
        },
    )
    db.commit()
    return FollowUpRecalculateResponse(**result.__dict__)


@router.post("/{task_id}/create-draft", response_model=FollowUpTaskRead)
def create_followup_draft(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> FollowUpTaskRead:
    task = get_task_or_404(db, task_id)
    ensure_can_access_order(db, current_user, task.order)
    if task.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Follow-up task is not pending")

    old_status = task.status
    if task.task_type == "manual_review":
        task.status = "completed"
        task.completed_by_user_id = current_user.id
        task.completed_at = utc_now()
        task.order.status = "manual_review"
        task.order.next_action_at = None
        task.updated_at = utc_now()
        add_audit_log(
            db,
            entity_type="followup_task",
            entity_id=task.id,
            action="followup_task.manual_review_created",
            user_id=current_user.id,
            old_value={"status": old_status, "order_status": task.order.status},
            new_value={"status": task.status, "order_status": task.order.status},
        )
        db.commit()
        db.refresh(task)
        return FollowUpTaskRead.model_validate(task)

    if task.task_type not in FOLLOWUP_DRAFT_TYPES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This follow-up task does not generate an email draft")

    try:
        draft = create_email_draft(db, task.order_id, task.task_type, user_id=current_user.id)
    except EmailDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmailDraftBusinessError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc

    task.status = "draft_created"
    task.generated_email_draft_id = draft.id
    task.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="followup_task",
        entity_id=task.id,
        action="followup_task.email_draft_created",
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": task.status, "email_draft_id": draft.id, "task_type": task.task_type},
    )
    db.commit()
    db.refresh(task)
    return FollowUpTaskRead.model_validate(task)


@router.post("/{task_id}/create-gmail-draft", response_model=FollowUpTaskRead)
def create_followup_gmail_draft(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> FollowUpTaskRead:
    task = get_task_or_404(db, task_id)
    ensure_can_access_order(db, current_user, task.order)
    if task.status != "draft_created":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Follow-up task needs an internal draft first")
    if task.generated_email_draft is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Follow-up task has no generated email draft")

    try:
        provider_draft = provider.create_draft(
            db,
            current_user,
            task.generated_email_draft,
            to_email=get_settings().default_uber_eats_support_email,
            include_evidence=True,
        )
    except EmailProviderError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    old_status = task.status
    task.status = "provider_draft_created"
    task.generated_provider_draft_id = provider_draft.id
    task.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="followup_task",
        entity_id=task.id,
        action="followup_task.gmail_draft_created",
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": task.status, "provider_draft_id": provider_draft.id},
    )
    db.commit()
    db.refresh(task)
    return FollowUpTaskRead.model_validate(task)


@router.post("/{task_id}/skip", response_model=FollowUpTaskRead)
def skip_followup_task(
    task_id: int,
    payload: FollowUpSkipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> FollowUpTaskRead:
    task = get_task_or_404(db, task_id)
    ensure_can_access_order(db, current_user, task.order)
    if task.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Completed follow-up task cannot be skipped")
    old_status = task.status
    task.status = "skipped"
    task.skipped_by_user_id = current_user.id
    task.skipped_at = utc_now()
    task.skip_reason = payload.skip_reason
    task.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="followup_task",
        entity_id=task.id,
        action="followup_task.skipped",
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": task.status, "skip_reason": task.skip_reason},
    )
    db.commit()
    db.refresh(task)
    return FollowUpTaskRead.model_validate(task)


@router.post("/{task_id}/complete", response_model=FollowUpTaskRead)
def complete_followup_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> FollowUpTaskRead:
    task = get_task_or_404(db, task_id)
    ensure_can_access_order(db, current_user, task.order)
    if task.status in {"skipped", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skipped or cancelled follow-up task cannot be completed")
    apply_followup_completion_effects(db, task, current_user)
    db.commit()
    db.refresh(task)
    return FollowUpTaskRead.model_validate(task)


def get_task_or_404(db: Session, task_id: int) -> FollowUpTask:
    task = db.get(FollowUpTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Follow-up task not found")
    return task


def build_followup_summary(task: FollowUpTask, order: ClaimOrder, restaurant: Restaurant) -> FollowUpTaskSummary:
    return FollowUpTaskSummary(
        id=task.id,
        order_id=order.id,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        uber_order_number=order.uber_order_number,
        order_amount=order.order_amount,
        currency=order.currency,
        claim_status=order.status,
        retry_count=order.retry_count,
        next_action_at=order.next_action_at,
        last_followup_sent_at=order.last_followup_sent_at,
        task_type=task.task_type,
        status=task.status,
        due_at=task.due_at,
        generated_email_draft_id=task.generated_email_draft_id,
        generated_provider_draft_id=task.generated_provider_draft_id,
    )
