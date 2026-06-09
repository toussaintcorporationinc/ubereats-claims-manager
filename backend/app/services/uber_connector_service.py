from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import UberIntegrationAccount, UberStoreMapping, User


class UberConnectorService:
    """Official Uber Eats API connector placeholder.

    Mission 18 intentionally does not call Uber. This service keeps the future
    API boundary explicit while reports/imports provide the production fallback.
    """

    provider = "uber_eats"

    def get_status(self, db: Session, current_user: User) -> dict[str, object]:
        account = db.scalar(
            select(UberIntegrationAccount)
            .where(UberIntegrationAccount.provider == self.provider)
            .order_by(UberIntegrationAccount.id.desc())
        )
        mappings_count = db.scalar(select(func.count(UberStoreMapping.id))) or 0
        return {
            "provider": self.provider,
            "status": account.status if account else "not_configured",
            "official_api_enabled": False,
            "approval_required": True,
            "scopes": account.scopes if account else None,
            "store_mappings_count": mappings_count if current_user.role == "owner" else 0,
        }

