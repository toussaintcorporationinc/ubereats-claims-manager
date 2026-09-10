from dataclasses import asdict
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncService

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])


def _require_runtime_authorization(authorization: str | None) -> None:
    settings = get_settings()
    secrets_to_try = [value for value in (settings.tennet_cron_secret, settings.cron_secret) if value]
    if not secrets_to_try:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime sync is not configured",
        )

    if authorization is None or not any(
        compare_digest(authorization, f"Bearer {secret}") for secret in secrets_to_try
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime token")


def _run_gmail_sync(
    authorization: str | None,
    db: Session,
) -> dict[str, object]:
    _require_runtime_authorization(authorization)
    result = GmailInboundAutoSyncService(settings=get_settings()).sync_due_accounts(db)
    db.commit()
    return asdict(result)


@router.api_route("/gmail-sync", methods=["GET", "POST"])
def run_gmail_sync(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _run_gmail_sync(authorization, db)
