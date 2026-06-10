from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.domain import WorkspaceNextActionsResponse
from app.services.workspace_action_service import WorkspaceActionService

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])


@router.get("/next-actions", response_model=WorkspaceNextActionsResponse)
def workspace_next_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceNextActionsResponse:
    return WorkspaceActionService(db, current_user).next_actions()
