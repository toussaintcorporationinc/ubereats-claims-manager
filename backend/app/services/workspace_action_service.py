from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import User
from app.schemas.domain import RecoveryAction, WorkspaceAction, WorkspaceNextActionsResponse
from app.services.recovery_cockpit_service import RecoveryCockpitService, RecoveryFilters
from app.services.workspace_unclassified_service import WorkspaceUnclassifiedService

HIGH_VALUE_THRESHOLD = Decimal("100")


class WorkspaceActionService:
    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user

    def next_actions(self) -> WorkspaceNextActionsResponse:
        recovery_actions = RecoveryCockpitService(
            self.db,
            self.current_user,
            RecoveryFilters(),
            max_source_rows=1000,
        ).actions(limit=80, offset=0)
        workspace_actions = [self.from_recovery_action(action) for action in recovery_actions]
        workspace_actions.extend(self.unclassified_actions())
        if self.current_user.role in {"owner", "manager"}:
            workspace_actions.extend(self.owner_manager_guided_actions())
        return bucket_actions(workspace_actions)

    def from_recovery_action(self, action: RecoveryAction) -> WorkspaceAction:
        return WorkspaceAction(
            title=action_title(action),
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

    def unclassified_actions(self) -> list[WorkspaceAction]:
        items = WorkspaceUnclassifiedService(self.db, self.current_user).list_items(limit=12).items
        return [
            WorkspaceAction(
                title=f"Non classe - {item.original_filename}",
                description=item.description,
                restaurant=item.restaurant,
                amount=None,
                priority="high" if item.reason in {"missing_identity", "ambiguous_matches"} else "normal",
                action_url=item.action_url,
                action_type="manual_review",
            )
            for item in items
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
        if action.case_type == "customer_refund_dispute":
            return "Ajoutez les tickets, photos ou captures demandes pour debloquer la contestation."
        if "remboursement" in action.label.lower():
            return "Ajoutez les preuves de remboursement demandees avant envoi Uber."
        return "Ajoutez les preuves d'annulation demandees avant envoi Uber."
    if action.case_type == "customer_refund_dispute":
        return "Deduction Uber detectee. TENNET attend les preuves fiables avant contestation."
    if action.case_type == "appeal_workflow":
        return "Refus Uber a reprendre avec un nouvel argument, une preuve ou une escalation."
    if action.action_type == "followup":
        return "Relance due si aucune reponse positive n'a ete comptabilisee."
    if action.action_type == "create_claim_order":
        return "Perte detectee. TENNET peut creer le dossier sans doublon."
    if action.action_type in {"create_draft", "create_gmail_draft"}:
        return "Dossier pret. TENNET prepare l'email Uber avec les preuves disponibles."
    return "Action priorisee par TENNET."


def action_title(action: RecoveryAction) -> str:
    if action.action_type == "upload_evidence":
        if action.case_type == "customer_refund_dispute" or "remboursement" in action.label.lower():
            return "Preuves remboursement a fournir"
        return "Preuves annulation a fournir"
    if action.action_type == "create_claim_order":
        if action.case_type == "customer_refund_dispute":
            return "Creer dossier remboursement"
        return "Creer dossier annulation"
    if action.action_type in {"create_draft", "create_gmail_draft"}:
        if action.case_type == "customer_refund_dispute":
            return "Email remboursement a preparer"
        return "Email annulation a preparer"
    if action.action_type in {"review_refusal", "request_more_evidence", "escalation"}:
        return "Refus Uber a reprendre"
    if action.action_type == "followup":
        return "Relance Uber a traiter"
    if action.case_type == "customer_refund_dispute":
        return "Remboursement Uber a verifier"
    return human_title(action.label)


def human_title(label: str) -> str:
    return label.replace("_", " ").strip().capitalize()


def priority_rank(priority: str) -> int:
    return {"urgent": 4, "high": 3, "normal": 2, "low": 1}.get(priority, 0)
