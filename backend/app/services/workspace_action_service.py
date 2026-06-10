from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import User
from app.schemas.domain import RecoveryAction, WorkspaceAction, WorkspaceNextActionsResponse
from app.services.recovery_cockpit_service import RecoveryCockpitService, RecoveryFilters

HIGH_VALUE_THRESHOLD = Decimal("100")


class WorkspaceActionService:
    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user

    def next_actions(self) -> WorkspaceNextActionsResponse:
        recovery_actions = RecoveryCockpitService(self.db, self.current_user, RecoveryFilters()).actions(limit=80, offset=0)
        workspace_actions = [self.from_recovery_action(action) for action in recovery_actions]
        if self.current_user.role in {"owner", "manager"}:
            workspace_actions.extend(self.owner_manager_guided_actions())
        return bucket_actions(workspace_actions)

    def from_recovery_action(self, action: RecoveryAction) -> WorkspaceAction:
        return WorkspaceAction(
            title=human_title(action.label),
            description=action_description(action),
            restaurant=action.restaurant_name,
            amount=action.amount,
            priority=action.priority,
            action_url=action.url,
            action_type=workspace_action_type(action),
        )

    def owner_manager_guided_actions(self) -> list[WorkspaceAction]:
        return [
            WorkspaceAction(
                title="Importer un rapport Uber",
                description="Deposez un export Uber sans le renommer, TENNET detecte le type et propose la suite.",
                restaurant=None,
                amount=None,
                priority="normal",
                action_url="/smart-import",
                action_type="review_import",
            ),
            WorkspaceAction(
                title="Verifier le cockpit recuperation",
                description="Voir les pertes detectees, les dossiers blocants et les montants a suivre.",
                restaurant=None,
                amount=None,
                priority="normal",
                action_url="/recovery",
                action_type="export_report",
            ),
            WorkspaceAction(
                title="Exporter les rapports",
                description="Controler les montants reclames, recuperes, en attente et refuses.",
                restaurant=None,
                amount=None,
                priority="normal",
                action_url="/reports",
                action_type="export_report",
            ),
            WorkspaceAction(
                title="Controler AutoPilot",
                description="Verifier les limites et garder les envois automatiques sous controle humain.",
                restaurant=None,
                amount=None,
                priority="normal",
                action_url="/autopilot",
                action_type="manual_review",
            ),
        ]


def bucket_actions(actions: list[WorkspaceAction]) -> WorkspaceNextActionsResponse:
    now = datetime.now(timezone.utc)
    response = WorkspaceNextActionsResponse()
    seen: set[tuple[str, str]] = set()
    for action in actions:
        key = (action.action_type, action.action_url)
        if key in seen:
            continue
        seen.add(key)
        if action.priority == "urgent":
            response.urgent.append(action)
        elif action.priority == "high":
            response.today.append(action)
        elif action.amount is not None and action.amount >= HIGH_VALUE_THRESHOLD:
            response.high_value.append(action)
        elif action.action_type in {"upload_evidence", "map_uber_store", "manual_review"}:
            response.blocked.append(action)
        else:
            response.this_week.append(action)
    response.urgent = sort_bucket(response.urgent, now)
    response.today = sort_bucket(response.today, now)
    response.this_week = sort_bucket(response.this_week, now)
    response.blocked = sort_bucket(response.blocked, now)
    response.high_value = sort_bucket(response.high_value, now)
    return response


def sort_bucket(actions: list[WorkspaceAction], _: datetime) -> list[WorkspaceAction]:
    return sorted(actions, key=lambda item: (priority_rank(item.priority), item.amount or Decimal("0")), reverse=True)[:12]


def workspace_action_type(action: RecoveryAction) -> str:
    if action.action_type == "upload_evidence":
        return "upload_evidence"
    if action.action_type in {"create_claim_order"}:
        return "create_claim_order"
    if action.action_type in {"create_draft", "create_appeal_draft"}:
        return "create_draft"
    if action.action_type in {"create_gmail_draft", "followup"}:
        return "send_manual"
    if action.action_type in {"review_refusal", "request_more_evidence", "escalation"}:
        return "appeal_refusal"
    if action.case_type == "customer_refund_dispute":
        return "review_customer_refund"
    return "manual_review"


def action_description(action: RecoveryAction) -> str:
    if action.action_type == "upload_evidence":
        return "Preuve attendue pour debloquer le dossier."
    if action.case_type == "customer_refund_dispute":
        return "Deduction Uber a verifier avec preuves avant contestation."
    if action.case_type == "appeal_workflow":
        return "Refus Uber a poursuivre avec appel controle."
    if action.action_type == "followup":
        return "Relance due, sans envoi automatique."
    return "Action priorisee par TENNET."


def human_title(label: str) -> str:
    return label.replace("_", " ").strip().capitalize()


def priority_rank(priority: str) -> int:
    return {"urgent": 4, "high": 3, "normal": 2, "low": 1}.get(priority, 0)
