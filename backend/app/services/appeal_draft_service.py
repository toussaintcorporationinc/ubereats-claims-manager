from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppealWorkflow, ClaimOrder, EmailDraft, RefusalAnalysis
from app.services.audit import add_audit_log
from app.services.email_draft_service import (
    build_order_identity_phrase,
    display_order_number,
    format_amount,
    format_display_date,
    format_restaurant_signature,
)
from app.services.refusal_policy_service import template_type_for_policy

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "emails"

APPEAL_SUBJECTS = {
    "appeal_generic_refusal": "Reexamen contestation commande Uber Eats - {uber_order_number}",
    "appeal_missing_evidence_reply": "Preuves complementaires - commande Uber Eats - {uber_order_number}",
    "appeal_order_prepared_before_cancellation": "Reexamen annulation de commande - {uber_order_number}",
    "appeal_order_not_received_delivery_proof": "Reexamen commande non recue - {uber_order_number}",
    "appeal_missing_item_preparation_proof": "Reexamen article manquant conteste - {uber_order_number}",
    "appeal_escalation": "Reexamen prioritaire commande Uber Eats - {uber_order_number}",
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
        raise AppealDraftError("Appeal draft requires a linked claim order", 409)

    recommended_action = analysis.recommended_next_action if analysis else "challenge_generic_refusal"
    template_type = template_type_for_policy(recommended_action, appeal_type)
    context = build_appeal_context(workflow, order, analysis, appeal_type)
    subject = APPEAL_SUBJECTS[template_type].format(uber_order_number=display_order_number(order))
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
        f"- {item.original_filename}"
        for item in sorted(order.evidence_files, key=lambda evidence: evidence.id)
    )
    if not evidence_list:
        evidence_list = "- Aucune piece jointe pour le moment."

    required_evidence = analysis.required_evidence_types_json if analysis else []
    required_evidence_text = "\n".join(f"- {item}" for item in required_evidence or [])
    if not required_evidence_text:
        required_evidence_text = "- Aucun element complementaire precis n'a ete demande."

    refusal_reason = analysis.refusal_reason if analysis else "Refus a reexaminer"
    refusal_excerpt = analysis.refusal_text_excerpt if analysis and analysis.refusal_text_excerpt else "Non renseigne"
    appeal_argument = build_appeal_argument(
        action=analysis.recommended_next_action if analysis else "challenge_generic_refusal",
        appeal_type=appeal_type,
        refusal_count=workflow.refusal_count,
        attempt_count=workflow.appeal_attempt_count,
        evidence_list=evidence_list,
    )

    return {
        "restaurant_name": restaurant.name if restaurant else f"Restaurant #{order.restaurant_id}",
        "uber_order_number": display_order_number(order),
        "order_identity_phrase": build_order_identity_phrase(order),
        "customer_name_line": optional_line("Client", order.customer_name),
        "order_date_line": optional_line("Date de commande", format_display_date(order.order_date)),
        "order_amount": format_amount(order.order_amount or 0),
        "currency": order.currency,
        "appeal_type": appeal_type,
        "refusal_count": workflow.refusal_count,
        "appeal_attempt_count": workflow.appeal_attempt_count,
        "refusal_reason": refusal_reason,
        "refusal_excerpt": refusal_excerpt,
        "appeal_argument": appeal_argument,
        "evidence_list": evidence_list,
        "required_evidence_list": required_evidence_text,
        "signature": format_restaurant_signature(restaurant) if restaurant else "Restaurant",
    }


def optional_line(label: str, value: object | None) -> str:
    if value is None or value == "":
        return ""
    return f"{label} : {value}\n"


def build_appeal_argument(
    *,
    action: str,
    appeal_type: str,
    refusal_count: int,
    attempt_count: int,
    evidence_list: str,
) -> str:
    has_evidence = "Aucune piece jointe" not in evidence_list
    repeated = refusal_count > 1 or attempt_count > 0
    if action == "provide_missing_evidence" or appeal_type == "evidence_reply":
        if has_evidence:
            return (
                "Je vous joins les elements disponibles pour permettre une nouvelle verification du dossier. "
                "Si une piece precise reste manquante, merci de l'indiquer clairement afin que le restaurant puisse "
                "la fournir sans ouvrir un nouveau dossier."
            )
        return (
            "Votre reponse semble demander des justificatifs complementaires. Merci d'indiquer precisement les pieces "
            "attendues pour que le restaurant puisse completer le dossier correctement."
        )
    if action == "clarify_delivery_proof":
        return (
            "La commande a ete preparee et suivie dans le parcours habituel. Merci de verifier les elements transmis "
            "et de preciser exactement quelle information de livraison manquerait si le refus est maintenu."
        )
    if action == "clarify_order_prepared":
        return (
            "La commande avait ete preparee avant l'annulation. Le restaurant a supporte une perte et du gaspillage; "
            "merci de reexaminer le dossier avec les pieces jointes."
        )
    if action == "payment_verification":
        return (
            "Merci de verifier si un paiement ou une regularisation existe deja pour cette commande. Si le paiement "
            "a ete accorde, merci de confirmer le montant et la reference de versement."
        )
    if action == "request_escalation" or appeal_type == "escalation" or repeated:
        return (
            "Le refus ne permet pas de comprendre clairement la raison du rejet. Je vous demande une nouvelle revue "
            "du dossier et, si necessaire, une transmission a un niveau de traitement superieur avec le motif detaille."
        )
    return (
        "Le refus ne donne pas d'element suffisamment precis pour justifier le maintien de la deduction. "
        "Merci de reexaminer la commande et les pieces jointes, puis de confirmer la regularisation ou le motif exact "
        "si le refus est maintenu."
    )


def render_template(draft_type: str, context: dict[str, Any]) -> str:
    template_path = TEMPLATE_DIR / f"{draft_type}.txt"
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)
