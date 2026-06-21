from __future__ import annotations

from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from app.models import Base
from app.models.domain import utc_now
from app.services.audit import add_audit_log

RESET_CONFIRMATION = "RESET_TENNET_BUSINESS_HISTORY"
PRESERVED_TABLES = {
    "users",
    "restaurants",
    "user_restaurant_access",
    "email_accounts",
    "email_account_restaurant_mappings",
    "uber_store_mappings",
    "uber_integration_accounts",
    "audit_logs",
}
IGNORED_TABLES = {"alembic_version"}


class BusinessHistoryResetError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def reset_business_history(db: Session, *, user_id: int, confirmation: str) -> dict[str, int]:
    if confirmation != RESET_CONFIRMATION:
        raise BusinessHistoryResetError("Confirmation phrase is invalid", 400)
    counts: dict[str, int] = {}
    for table in reset_order():
        counts[table.name] = int(db.scalar(select(func.count()).select_from(table)) or 0)
        db.execute(table.delete())
    add_audit_log(
        db,
        entity_type="business_history_reset",
        entity_id=user_id,
        action="business_history.reset",
        user_id=user_id,
        new_value={
            "preserved": sorted(PRESERVED_TABLES),
            "deleted_counts": counts,
            "reset_at": utc_now().isoformat(),
        },
    )
    db.commit()
    return counts


def reset_order() -> list[Table]:
    return [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if table.name not in PRESERVED_TABLES and table.name not in IGNORED_TABLES
    ]
