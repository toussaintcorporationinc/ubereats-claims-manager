from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_owner, require_owner_or_manager
from app.core.database import get_db
from app.routes.email import get_gmail_provider
from app.models import User
from app.schemas.domain import (
    BusinessHistoryResetRequest,
    BusinessHistoryResetResponse,
    RecoveryMachineResponse,
    WorkspaceMachineRunRequest,
    WorkspaceMachineRunResponse,
    WorkspaceNextActionsResponse,
    WorkspaceUnclassifiedResponse,
)
from app.services.email_provider import EmailProvider
from app.services.business_history_reset_service import BusinessHistoryResetError, reset_business_history
from app.services.workspace_action_service import WorkspaceActionService
from app.services.workspace_machine_service import WorkspaceMachineError, WorkspaceMachineService
from app.services.workspace_unclassified_service import WorkspaceUnclassifiedService
from app.services.recovery_machine_service import RecoveryMachineService

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])


@router.get("/next-actions", response_model=WorkspaceNextActionsResponse)
def workspace_next_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceNextActionsResponse:
    return WorkspaceActionService(db, current_user).next_actions()


@router.get("/unclassified", response_model=WorkspaceUnclassifiedResponse)
def workspace_unclassified(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceUnclassifiedResponse:
    return WorkspaceUnclassifiedService(db, current_user).list_items()


@router.get("/recovery-machine", response_model=RecoveryMachineResponse)
def workspace_recovery_machine(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecoveryMachineResponse:
    return RecoveryMachineService(db, current_user).summary()


@router.post("/machine/run", response_model=WorkspaceMachineRunResponse)
def run_workspace_machine(
    payload: WorkspaceMachineRunRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> WorkspaceMachineRunResponse:
    request_payload = payload or WorkspaceMachineRunRequest()
    try:
        return WorkspaceMachineService(db, current_user, provider).run(request_payload)
    except WorkspaceMachineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/reset-business-history", response_model=BusinessHistoryResetResponse)
def reset_workspace_business_history(
    payload: BusinessHistoryResetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> BusinessHistoryResetResponse:
    try:
        deleted_counts = reset_business_history(db, user_id=current_user.id, confirmation=payload.confirmation)
    except BusinessHistoryResetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return BusinessHistoryResetResponse(
        status="reset",
        deleted_counts=deleted_counts,
        preserved=[
            "users",
            "restaurants",
            "user_restaurant_access",
            "email_accounts",
            "email_account_restaurant_mappings",
            "uber_store_mappings",
            "uber_integration_accounts",
        ],
    )
