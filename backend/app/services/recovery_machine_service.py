from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models import User
from app.schemas.domain import (
    RecoveryAction,
    RecoveryCase,
    RecoveryMachineRailKey,
    RecoveryMachineRailRead,
    RecoveryMachineResponse,
    RecoveryMachineStageRead,
)
from app.services.recovery_cockpit_service import RecoveryCockpitService, RecoveryFilters


REFUND_CATEGORIES = {
    "customer_refund",
    "order_not_received",
    "missing_item",
    "incorrect_item",
    "order_error_adjustment",
    "chargeback",
    "manual_review",
}
CANCELLATION_CATEGORIES = {"cancellation_not_compensated"}
EVIDENCE_MISSING_STAGES = {"needs_evidence", "missing_evidence"}
EVIDENCE_READY_STAGES = {
    "evidence_ready",
    "draft_created",
    "gmail_draft_created",
    "sent",
    "under_appeal",
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
}
EMAIL_PIPELINE_STAGES = {
    "draft_created",
    "gmail_draft_created",
    "sent",
    "under_appeal",
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
}


class RecoveryMachineService:
    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user

    def summary(self) -> RecoveryMachineResponse:
        cockpit = RecoveryCockpitService(self.db, self.current_user, RecoveryFilters())
        cases = cockpit.cases(limit=None, offset=0)
        actions = cockpit.actions(limit=None, offset=0)
        rails = [
            self.build_rail(
                key="refunds",
                title="Remboursements",
                short_title="Remboursements",
                description="Demandes client, articles manquants, commandes non recues, qualite et ajustements Uber.",
                href="/remboursements",
                primary_action_label="Deposer remboursements",
                primary_action_href="/smart-import",
                cases=[case for case in cases if case.loss_category in REFUND_CATEGORIES],
                actions=[action for action in actions if action_belongs_to_refunds(action)],
            ),
            self.build_rail(
                key="cancellations",
                title="Annulations",
                short_title="Annulations",
                description="Commandes annulees, non compensees ou partiellement compensees apres preparation.",
                href="/annulations",
                primary_action_label="Deposer annulations",
                primary_action_href="/smart-import",
                cases=[case for case in cases if case.loss_category in CANCELLATION_CATEGORIES],
                actions=[action for action in actions if action_belongs_to_cancellations(action)],
            ),
        ]
        total_detected = sum_money(rail.detected_amount for rail in rails)
        total_recovered = sum_money(rail.recovered_amount for rail in rails)
        total_actions = sum(rail.missing_evidence_count + rail.followup_or_appeal_count for rail in rails)
        return RecoveryMachineResponse(
            subtitle="Depose les fichiers. TENNET classe, prouve, prepare, envoie selon tes regles, relance et comptabilise les paiements.",
            global_progress_percent=weighted_progress(rails),
            total_detected_amount=total_detected,
            total_recovered_amount=total_recovered,
            total_actions_count=total_actions,
            rails=rails,
        )

    def build_rail(
        self,
        *,
        key: RecoveryMachineRailKey,
        title: str,
        short_title: str,
        description: str,
        href: str,
        primary_action_label: str,
        primary_action_href: str,
        cases: list[RecoveryCase],
        actions: list[RecoveryAction],
    ) -> RecoveryMachineRailRead:
        detected_count = len(cases)
        detected_amount = sum_money(case.detected_amount for case in cases)
        claimable_amount = sum_money(case.claimable_amount for case in cases)
        missing_evidence_cases = [
            case
            for case in cases
            if case.recovery_stage in EVIDENCE_MISSING_STAGES or case.evidence_status in {"missing", "partial"}
        ]
        evidence_ready_cases = [
            case
            for case in cases
            if case.recovery_stage in EVIDENCE_READY_STAGES or case.evidence_status in {"complete", "not_required"}
        ]
        email_pipeline_cases = [case for case in cases if case.recovery_stage in EMAIL_PIPELINE_STAGES]
        recovered_cases = [case for case in cases if case.recovered_amount > 0 or case.recovery_stage == "payment_confirmed"]
        followup_or_appeal_count = len(
            [
                action
                for action in actions
                if action.action_type in {"followup", "review_refusal", "request_more_evidence", "create_appeal_draft", "escalation"}
            ]
        ) + len([case for case in cases if case.recovery_stage == "under_appeal"])
        recovered_amount = sum_money(case.recovered_amount for case in recovered_cases)
        progress = rail_progress(
            detected_count=detected_count,
            missing_evidence_count=len(missing_evidence_cases),
            evidence_ready_count=len(evidence_ready_cases),
            email_pipeline_count=len(email_pipeline_cases),
            recovered_count=len(recovered_cases),
        )
        health = rail_health(detected_count, len(missing_evidence_cases), followup_or_appeal_count, progress)
        next_action_label, next_action_href = next_action_for_rail(
            missing_evidence_count=len(missing_evidence_cases),
            followup_or_appeal_count=followup_or_appeal_count,
            detected_count=detected_count,
            href=href,
            primary_action_label=primary_action_label,
            primary_action_href=primary_action_href,
        )
        stages = [
            RecoveryMachineStageRead(
                key="smart_import",
                label="Import massif",
                description="TENNET lit les exports et sources officielles sans renommage.",
                count=detected_count,
                amount=detected_amount,
                status="done" if detected_count else "ready",
                href="/smart-import",
            ),
            RecoveryMachineStageRead(
                key="evidence_needed",
                label="Preuves attendues",
                description=evidence_needed_description(key, len(missing_evidence_cases)),
                count=len(missing_evidence_cases),
                amount=sum_money(case.detected_amount for case in missing_evidence_cases),
                status="attention" if missing_evidence_cases else ("done" if detected_count else "empty"),
                href="/evidence-tasks",
            ),
            RecoveryMachineStageRead(
                key="evidence_received",
                label="Preuves recues",
                description="Tickets, preparation, gaspillage, captures ou livraison deja rattaches.",
                count=len(evidence_ready_cases),
                amount=sum_money(case.detected_amount for case in evidence_ready_cases),
                status="done" if evidence_ready_cases else ("ready" if detected_count else "empty"),
                href="/evidence-imports",
            ),
            RecoveryMachineStageRead(
                key="uber_emails",
                label="Mails Uber",
                description="Brouillons, Gmail drafts et dossiers envoyes a Uber selon les regles.",
                count=len(email_pipeline_cases),
                amount=sum_money(case.detected_amount for case in email_pipeline_cases),
                status="working" if email_pipeline_cases else ("ready" if evidence_ready_cases else "empty"),
                href="/drafts",
            ),
            RecoveryMachineStageRead(
                key="followups",
                label="Relances et appels",
                description="Refus, relances dues et appels actifs restent suivis sans boucle infinie.",
                count=followup_or_appeal_count,
                amount=sum_money(action.amount for action in actions),
                status="attention" if followup_or_appeal_count else ("done" if email_pipeline_cases else "empty"),
                href="/recovery/actions",
            ),
            RecoveryMachineStageRead(
                key="payments",
                label="Paiements",
                description="Paiements confirmes, montants recuperes et dossiers a verifier.",
                count=len(recovered_cases),
                amount=recovered_amount,
                status="done" if recovered_cases else ("ready" if email_pipeline_cases else "empty"),
                href="/reports",
            ),
        ]
        return RecoveryMachineRailRead(
            key=key,
            title=title,
            short_title=short_title,
            description=description,
            href=href,
            primary_action_label=primary_action_label,
            primary_action_href=primary_action_href,
            detected_count=detected_count,
            detected_amount=detected_amount,
            claimable_amount=claimable_amount,
            missing_evidence_count=len(missing_evidence_cases),
            evidence_ready_count=len(evidence_ready_cases),
            email_pipeline_count=len(email_pipeline_cases),
            followup_or_appeal_count=followup_or_appeal_count,
            recovered_count=len(recovered_cases),
            recovered_amount=recovered_amount,
            progress_percent=progress,
            health=health,
            next_action_label=next_action_label,
            next_action_href=next_action_href,
            stages=stages,
        )


def action_belongs_to_refunds(action: RecoveryAction) -> bool:
    text = f"{action.case_type} {action.label} {action.url}".lower()
    return "customer_refund" in text or "remboursement" in text or "/customer-refunds" in text


def action_belongs_to_cancellations(action: RecoveryAction) -> bool:
    text = f"{action.case_type} {action.label} {action.url}".lower()
    if action_belongs_to_refunds(action):
        return False
    return "annulation" in text or "/uber/reconciliation" in text or "/orders" in text or action.case_type in {
        "followup_task",
        "appeal_workflow",
    }


def evidence_needed_description(rail_key: str, count: int) -> str:
    if rail_key == "refunds":
        return (
            "Preuves de contestation de remboursement a fournir."
            if count
            else "Aucune preuve de remboursement urgente."
        )
    return (
        "Preuves de contestation d'annulation a fournir."
        if count
        else "Aucune preuve d'annulation urgente."
    )


def next_action_for_rail(
    *,
    missing_evidence_count: int,
    followup_or_appeal_count: int,
    detected_count: int,
    href: str,
    primary_action_label: str,
    primary_action_href: str,
) -> tuple[str, str]:
    if missing_evidence_count:
        return "Completer les preuves ciblees", "/evidence-tasks"
    if followup_or_appeal_count:
        return "Traiter les relances et appels", "/recovery/actions"
    if detected_count:
        return "Ouvrir le parcours", href
    return primary_action_label, primary_action_href


def rail_health(detected_count: int, missing_evidence_count: int, followup_or_appeal_count: int, progress: int) -> str:
    if detected_count == 0:
        return "empty"
    if missing_evidence_count or followup_or_appeal_count:
        return "attention"
    if progress >= 80:
        return "good"
    return "working"


def rail_progress(
    *,
    detected_count: int,
    missing_evidence_count: int,
    evidence_ready_count: int,
    email_pipeline_count: int,
    recovered_count: int,
) -> int:
    if detected_count <= 0:
        return 0
    score = 12
    if missing_evidence_count == 0:
        score += 22
    else:
        score += max(0, round(22 * (1 - (missing_evidence_count / detected_count))))
    score += round(22 * min(evidence_ready_count / detected_count, 1))
    score += round(24 * min(email_pipeline_count / detected_count, 1))
    score += round(20 * min(recovered_count / detected_count, 1))
    return max(0, min(score, 100))


def weighted_progress(rails: list[RecoveryMachineRailRead]) -> int:
    total_cases = sum(rail.detected_count for rail in rails)
    if total_cases == 0:
        return 0
    weighted = sum(rail.progress_percent * rail.detected_count for rail in rails)
    return round(weighted / total_cases)


def sum_money(values) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += Decimal(str(value))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
