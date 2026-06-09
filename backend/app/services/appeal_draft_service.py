from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppealWorkflow, ClaimOrder, EmailDraft, RefusalAnalysis
from app.services.audit import add_audit_log
from app.services.email_draft_service import format_amount
from app.services.refusal_policy_service import template_type_for_policy

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "emails"

APPEAL_SUBJECTS = {
    "appeal_generic_refusal": "Demande de reexamen - refus Uber Eats - {uber_order_number}",
    "appeal_missing_evidence_reply": "Elements complementaires - refus Uber Eats - {uber_order_number}",
    "appeal_order_prepared_before_cancellation": "Reexamen - commande preparee avant annulation - {uber_order_number}",
    "appeal_order_not_received_delivery_proof": "Reexamen - preuve de livraison/preparation - {uber_order_number}",
    "appeal_missing_item_preparation_proof": "Reexamen - article manquant conteste - {uber_order_number}",
    "appeal_escalation": "Escalade - dossier Uber Eats refuse - {uber_order_number}",
    "appeal_payment_verification": "Verification paiement - dossier Uber Eats - {uber_order_number}",
}


class AppealDraftError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def create_appeal_email_draft(
    db: Session,
    *,
    workflow: AppealWorkflow,
    appeal_type: str,
    analysis: RefusalAnalysis | None,
    user_id: int | None,
) -> EmailDraft:
    order = resolve_order(workflow)
    if order is None:
        raise AppealDraftError("Appeal draft requires a linked TENNET claim order", 409)

    recommended_action = analysis.recommended_next_action if analysis else "challenge_generic_refusal"
    template_type = template_type_for_policy(recommended_action, appeal_type)
    context = build_appeal_context(workflow, order, analysis, appeal_type)
    subject = APPEAL_SUBJECTS[template_type].format(uber_order_number=order.uber_order_number)
    body = render_template(template_type, context)

    draft = EmailDraft(
        order_id=order.id,
        draft_type=template_type,
        subject=subject,
        body=body,
        status="created",
    )
    db.add(draft)
    db.flush()

    add_audit_log(
        db,
        entity_type="email_draft",
        entity_id=draft.id,
        action="create_appeal_email_draft",
        user_id=user_id,
        new_value={
            "workflow_id": workflow.id,
            "draft_type": template_type,
            "appeal_type": appeal_type,
            "order_id": order.id,
        },
    )
    return draft


def resolve_order(workflow: AppealWorkflow) -> ClaimOrder | None:
    if workflow.claim_order is not None:
        return workflow.claim_order
    if workflow.customer_refund_dispute is not None:
        return workflow.customer_refund_dispute.claim_order
    if workflow.reconciliation_result is not None:
        return workflow.reconciliation_result.claim_order
    return None


def build_appeal_context(
    workflow: AppealWorkflow,
    order: ClaimOrder,
    analysis: RefusalAnalysis | None,
    appeal_type: str,
) -> dict[str, Any]:
    restaurant = order.restaurant
    evidence_list = "\n".join(
        f"- {item.evidence_type}: {item.original_filename}"
        for item in sorted(order.evidence_files, key=lambda evidence: evidence.id)
    )
    if not evidence_list:
        evidence_list = "- Aucune preuve rattachee dans TENNET a ce stade."

    required_evidence = analysis.required_evidence_types_json if analysis else []
    required_evidence_text = "\n".join(f"- {item}" for item in required_evidence or [])
    if not required_evidence_text:
        required_evidence_text = "- Aucune nouvelle preuve obligatoire identifiee par TENNET."

    refusal_reason = analysis.refusal_reason if analysis else "Refus a reexaminer"
    refusal_excerpt = analysis.refusal_text_excerpt if analysis and analysis.refusal_text_excerpt else "Non renseigne"

    return {
        "restaurant_name": restaurant.name if restaurant else f"Restaurant #{order.restaurant_id}",
        "uber_order_number": order.uber_order_number,
        "order_amount": format_amount(order.order_amount or 0),
        "currency": order.currency,
        "appeal_type": appeal_type,
        "refusal_count": workflow.refusal_count,
        "appeal_attempt_count": workflow.appeal_attempt_count,
        "refusal_reason": refusal_reason,
        "refusal_excerpt": refusal_excerpt,
        "evidence_list": evidence_list,
        "required_evidence_list": required_evidence_text,
        "signature": restaurant.name if restaurant else "TENNET",
    }


def render_template(draft_type: str, context: dict[str, Any]) -> str:
    template_path = TEMPLATE_DIR / f"{draft_type}.txt"
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)
