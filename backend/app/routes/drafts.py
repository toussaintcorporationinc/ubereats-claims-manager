from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_accessible_restaurant_ids, get_current_user
from app.core.database import get_db
from app.models import ClaimOrder, EmailDraft, EmailProviderDraft, Restaurant, User
from app.schemas.domain import EmailDraftSummaryRead

router = APIRouter(prefix="/v1/drafts", tags=["drafts"])


@router.get("", response_model=list[EmailDraftSummaryRead])
def list_all_drafts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EmailDraftSummaryRead]:
    statement = (
        select(
            EmailDraft.id,
            EmailDraft.order_id,
            EmailDraft.draft_type,
            EmailDraft.subject,
            EmailDraft.status,
            EmailDraft.created_at,
            Restaurant.name.label("restaurant_name"),
            ClaimOrder.uber_order_number,
        )
        .join(ClaimOrder, EmailDraft.order_id == ClaimOrder.id)
        .join(Restaurant, ClaimOrder.restaurant_id == Restaurant.id)
        .order_by(EmailDraft.created_at.desc(), EmailDraft.id.desc())
    )
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return []
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    rows = db.execute(statement).all()

    return [build_draft_summary(db, row) for row in rows]


def build_draft_summary(db: Session, row: object) -> EmailDraftSummaryRead:
    provider_draft = db.scalar(
        select(EmailProviderDraft)
        .where(EmailProviderDraft.email_draft_id == row.id)
        .order_by(EmailProviderDraft.id.desc())
    )
    return EmailDraftSummaryRead(
        id=row.id,
        order_id=row.order_id,
        draft_type=row.draft_type,
        subject=row.subject,
        status=row.status,
        created_at=row.created_at,
        restaurant_name=row.restaurant_name,
        uber_order_number=row.uber_order_number,
        provider=provider_draft.provider if provider_draft else None,
        provider_status=provider_draft.status if provider_draft else None,
        provider_draft_id=provider_draft.provider_draft_id if provider_draft else None,
    )
