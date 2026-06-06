import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def add_audit_log(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> AuditLog:
    audit_log = AuditLog(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=json.dumps(old_value, default=str) if old_value is not None else None,
        new_value=json.dumps(new_value, default=str) if new_value is not None else None,
    )
    db.add(audit_log)
    return audit_log

