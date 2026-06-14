from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.routes.email import get_gmail_provider
from app.models import User
from app.schemas.domain import WorkspaceMachineRunRequest, WorkspaceMachineRunResponse, WorkspaceNextActionsResponse
from app.services.email_provider import EmailProvider
from app.services.workspace_action_service import WorkspaceActionService
from app.services.workspace_machine_service import WorkspaceMachineError, WorkspaceMachineService

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])


@router.get("/next-actions", response_model=WorkspaceNextActionsResponse)
def workspace_next_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceNextActionsResponse:
    return WorkspaceActionService(db, current_user).next_actions()


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
