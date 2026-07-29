from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, require_owner_or_manager
from app.core.database import get_db
from app.models import AutopilotAction, AutopilotRun, User
from app.routes.email import get_gmail_provider
from app.schemas.domain import (
    AutopilotActionsResponse,
    AutopilotRunDetailResponse,
    AutopilotRunRead,
    AutopilotRunRequest,
    AutopilotRunsResponse,
    AutopilotSettingsRead,
    AutopilotStatusResponse,
)
from app.services.autopilot_service import (
    AutopilotError,
    autopilot_is_emergency_stopped,
    create_emergency_resume,
    create_emergency_stop,
    run_autopilot,
    sent_today_count,
    settings_snapshot,
)
from app.services.email_provider import EmailProvider

router = APIRouter(prefix="/v1/autopilot", tags=["autopilot"])


@router.get("/status", response_model=AutopilotStatusResponse)
def get_autopilot_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> AutopilotStatusResponse:
    connection = provider.get_connection_status(db, current_user)
    snapshot = settings_snapshot()
    sent_count = sent_today_count(db)
    daily_limit = int(snapshot["daily_send_limit"])
    return AutopilotStatusResponse(
        settings=AutopilotSettingsRead(
            enabled=bool(snapshot["enabled"]),
            initial_claims_enabled=bool(snapshot["initial_claims_enabled"]),
            followups_enabled=bool(snapshot["followups_enabled"]),
            appeals_enabled=bool(snapshot["appeals_enabled"]),
            daily_send_limit=daily_limit,
            per_restaurant_daily_limit=int(snapshot["per_restaurant_daily_limit"]),
            min_amount=Decimal(snapshot["min_amount"]),
            max_amount_without_owner_review=Decimal(snapshot["max_amount_without_owner_review"]),
            require_complete_evidence=bool(snapshot["require_complete_evidence"]),
            require_complete_restaurant_signature=bool(snapshot["require_complete_restaurant_signature"]),
            require_gmail_connected=bool(snapshot["require_gmail_connected"]),
            cooldown_hours=int(snapshot["cooldown_hours"]),
            refusal_retry_enabled=bool(snapshot["refusal_retry_enabled"]),
            max_appeal_attempts=int(snapshot["max_appeal_attempts"]),
            never_close_on_refusal=bool(snapshot["never_close_on_refusal"]),
        ),
        gmail_provider_enabled=connection.enabled,
        gmail_connected=connection.connected,
        gmail_email_address=connection.email_address,
        emergency_stopped=autopilot_is_emergency_stopped(db),
        sent_today_count=sent_count,
        remaining_today_count=max(daily_limit - sent_count, 0),
    )


@router.post("/dry-run", response_model=AutopilotRunDetailResponse, status_code=status.HTTP_201_CREATED)
def dry_run_autopilot(
    payload: AutopilotRunRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> AutopilotRunDetailResponse:
    payload = payload or AutopilotRunRequest()
    try:
        result = run_autopilot(
            db,
            current_user,
            mode=payload.mode,
            restaurant_id=payload.restaurant_id,
            dry_run=True,
            provider=provider,
        )
    except AutopilotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(result.run)
    return AutopilotRunDetailResponse(
        run=AutopilotRunRead.model_validate(result.run),
        actions=[action for action in result.actions],
    )


@router.post("/run", response_model=AutopilotRunDetailResponse, status_code=status.HTTP_201_CREATED)
def execute_autopilot(
    payload: AutopilotRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> AutopilotRunDetailResponse:
    try:
        result = run_autopilot(
            db,
            current_user,
            mode=payload.mode,
            restaurant_id=payload.restaurant_id,
            dry_run=payload.dry_run,
            provider=provider,
        )
    except AutopilotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(result.run)
    return AutopilotRunDetailResponse(
        run=AutopilotRunRead.model_validate(result.run),
        actions=[action for action in result.actions],
    )


@router.post("/stop", response_model=AutopilotRunRead, status_code=status.HTTP_201_CREATED)
def stop_autopilot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AutopilotRunRead:
    run = create_emergency_stop(db, current_user)
    db.commit()
    db.refresh(run)
    return AutopilotRunRead.model_validate(run)


@router.post("/resume", response_model=AutopilotRunRead, status_code=status.HTTP_201_CREATED)
def resume_autopilot(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AutopilotRunRead:
    try:
        run = create_emergency_resume(db, current_user)
    except AutopilotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    db.refresh(run)
    return AutopilotRunRead.model_validate(run)


@router.get("/runs", response_model=AutopilotRunsResponse)
def list_autopilot_runs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AutopilotRunsResponse:
    statement = select(AutopilotRun).order_by(AutopilotRun.id.desc()).limit(limit).offset(offset)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return AutopilotRunsResponse(runs=[], limit=limit, offset=offset)
        statement = statement.where(
            AutopilotRun.id.in_(
                select(AutopilotAction.run_id).where(AutopilotAction.restaurant_id.in_(accessible_ids))
            )
        )
    runs = db.scalars(statement).all()
    return AutopilotRunsResponse(runs=[AutopilotRunRead.model_validate(run) for run in runs], limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=AutopilotRunDetailResponse)
def get_autopilot_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AutopilotRunDetailResponse:
    run = db.get(AutopilotRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AutoPilot run not found")
    actions = db.scalars(select(AutopilotAction).where(AutopilotAction.run_id == run.id).order_by(AutopilotAction.id)).all()
    for action in actions:
        ensure_can_access_restaurant(db, current_user, action.restaurant_id)
    return AutopilotRunDetailResponse(
        run=AutopilotRunRead.model_validate(run),
        actions=list(actions),
    )


@router.get("/actions", response_model=AutopilotActionsResponse)
def list_autopilot_actions(
    restaurant_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    action_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> AutopilotActionsResponse:
    statement = select(AutopilotAction).order_by(AutopilotAction.id.desc())
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(AutopilotAction.restaurant_id == restaurant_id)
    if status_filter:
        statement = statement.where(AutopilotAction.status == status_filter)
    if action_type:
        statement = statement.where(AutopilotAction.action_type == action_type)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return AutopilotActionsResponse(actions=[], limit=limit, offset=offset)
        statement = statement.where(AutopilotAction.restaurant_id.in_(accessible_ids))
    actions = db.scalars(statement.limit(limit).offset(offset)).all()
    for action in actions:
        ensure_can_access_restaurant(db, current_user, action.restaurant_id)
    return AutopilotActionsResponse(actions=list(actions), limit=limit, offset=offset)
