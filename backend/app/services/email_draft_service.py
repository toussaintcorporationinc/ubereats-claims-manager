import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClaimOrder, EmailDraft
from app.services.audit import add_audit_log
from app.services.claim_validation_service import FINAL_CLAIM_STATUSES, get_claim_validation_gaps

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "emails"

DRAFT_SUBJECTS = {
    "initial_claim": "Contestation d'annulation de commande - {uber_order_number}",
    "followup_1": "Relance - contestation commande Uber Eats - {uber_order_number}",
    "followup_2": "Relance - contestation commande Uber Eats - {uber_order_number}",
    "escalation": "Demande de reexamen - commande Uber Eats - {uber_order_number}",
    "proof_reply": "Preuves complementaires - commande Uber Eats - {uber_order_number}",
}

FOLLOWUP_ALLOWED_STATUSES = {
    "draft_email_created",
    "sent",
    "waiting_uber_response",
    "response_received",
    "followup_1_sent",
    "followup_2_sent",
    "escalation_sent",
}


class EmailDraftNotFoundError(Exception):
    pass


class EmailDraftBusinessError(Exception):
    def __init__(self, message: str, blocking_reasons: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.blocking_reasons = blocking_reasons or []


def create_email_draft(db: Session, order_id: int, draft_type: str, user_id: int | None = None) -> EmailDraft:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        raise EmailDraftNotFoundError("Order not found")

    previous_status = order.status
    if previous_status in FINAL_CLAIM_STATUSES:
        raise EmailDraftBusinessError(
            "Email draft generation is not allowed for a final claim status",
            ["final_status_cannot_generate_email_draft"],
        )

    if draft_type == "initial_claim":
        ensure_initial_claim_allowed(db, order)
        new_order_status = "draft_email_created"
    elif draft_type == "followup_1":
        ensure_followup_1_allowed(db, order)
        new_order_status = order.status
    elif draft_type == "followup_2":
        ensure_followup_2_allowed(db, order)
        new_order_status = order.status
    elif draft_type == "escalation":
        ensure_initial_draft_exists(db, order)
        new_order_status = order.status
    elif draft_type == "proof_reply":
        ensure_base_order_data(db, order)
        ensure_order_has_evidence(order)
        new_order_status = order.status
    else:
        raise EmailDraftBusinessError("Unsupported email draft type", ["unsupported_email_draft_type"])

    subject = build_subject(order, draft_type)
    body = render_template(draft_type, build_template_context(order))

    draft = EmailDraft(
        order_id=order.id,
        draft_type=draft_type,
        subject=subject,
        body=body,
        status="created",
    )
    db.add(draft)
    db.flush()

    if draft_type == "initial_claim":
        order.status = new_order_status

    add_audit_log(
        db,
        entity_type="email_draft",
        entity_id=draft.id,
        action="create_email_draft",
        user_id=user_id,
        old_value={"order_status": previous_status},
        new_value={
            "draft_id": draft.id,
            "draft_type": draft.draft_type,
            "order_id": order.id,
            "order_status": order.status,
        },
    )
    return draft


def ensure_initial_claim_allowed(db: Session, order: ClaimOrder) -> None:
    if order.status != "ready_to_send":
        raise EmailDraftBusinessError(
            "Initial claim draft requires a ready_to_send claim order",
            ["initial_claim_requires_ready_to_send"],
        )

    missing_items, blocking_reasons = get_claim_validation_gaps(db, order)
    if missing_items:
        raise EmailDraftBusinessError(
            "Initial claim draft requires a complete claim order",
            blocking_reasons,
        )


def ensure_followup_1_allowed(db: Session, order: ClaimOrder) -> None:
    ensure_base_order_data(db, order)
    if order.status not in FOLLOWUP_ALLOWED_STATUSES:
        raise EmailDraftBusinessError(
            "Followup 1 draft requires an order already claimed or waiting for Uber",
            ["followup_1_status_not_allowed"],
        )
    ensure_initial_draft_exists(db, order)


def ensure_followup_2_allowed(db: Session, order: ClaimOrder) -> None:
    ensure_base_order_data(db, order)
    ensure_initial_draft_exists(db, order)
    ensure_draft_type_exists(db, order, "followup_1")


def ensure_initial_draft_exists(db: Session, order: ClaimOrder) -> None:
    ensure_base_order_data(db, order)
    ensure_draft_type_exists(db, order, "initial_claim")


def ensure_draft_type_exists(db: Session, order: ClaimOrder, draft_type: str) -> None:
    existing_draft_id = db.scalar(
        select(EmailDraft.id).where(
            EmailDraft.order_id == order.id,
            EmailDraft.draft_type == draft_type,
        )
    )
    if existing_draft_id is None:
        raise EmailDraftBusinessError(
            f"{draft_type} draft is required before this draft type",
            [f"missing_{draft_type}_draft"],
        )


def ensure_base_order_data(db: Session, order: ClaimOrder) -> None:
    missing_items, blocking_reasons = get_claim_validation_gaps(db, order)
    base_blocking_reasons = [
        reason
        for reason in blocking_reasons
        if reason
        in {
            "missing_restaurant",
            "missing_uber_order_number",
            "missing_order_amount",
            "missing_currency",
        }
    ]
    if base_blocking_reasons:
        raise EmailDraftBusinessError("Email draft requires core claim data", base_blocking_reasons)


def ensure_order_has_evidence(order: ClaimOrder) -> None:
    if not order.evidence_files:
        raise EmailDraftBusinessError("Proof reply draft requires at least one evidence file", ["missing_evidence"])


def build_subject(order: ClaimOrder, draft_type: str) -> str:
    return DRAFT_SUBJECTS[draft_type].format(uber_order_number=display_order_number(order))


def build_template_context(order: ClaimOrder) -> dict[str, Any]:
    restaurant = order.restaurant
    return {
        "uber_order_number": display_order_number(order),
        "order_identity_phrase": build_order_identity_phrase(order),
        "restaurant_name": restaurant.name,
        "customer_name_line": optional_line("Client", order.customer_name),
        "order_date_line": optional_line("Date de commande", format_display_date(order.order_date)),
        "order_amount": format_amount(order.order_amount),
        "currency": order.currency,
        "accepted_line": optional_bool_line("Commande acceptee par le restaurant", order.accepted_by_restaurant),
        "prepared_line": optional_bool_line("Commande preparee avant annulation", order.prepared_before_cancellation),
        "loss_type_line": optional_line("Type de perte", order.loss_type),
        "evidence_list": format_evidence_list(order),
        "signature": format_restaurant_signature(restaurant),
    }


def build_order_identity_phrase(order: ClaimOrder) -> str:
    phrase = "la commande Uber Eats"
    if order.customer_name:
        phrase += f" de {order.customer_name}"
    phrase += f", numero de commande {display_order_number(order)}"
    order_date = format_display_date(order.order_date)
    if order_date:
        phrase += f", du {order_date}"
    return phrase


def display_order_number(order: ClaimOrder) -> str:
    reference = str(order.internal_reference or "").strip()
    if reference and not is_uuid_like(reference) and not is_internal_technical_reference(reference):
        return reference
    return order.uber_order_number


def is_internal_technical_reference(value: str | None) -> bool:
    cleaned = str(value or "").strip().upper()
    return cleaned.startswith(("CUST-REFUND-", "REFUND-", "AUTO-", "CLAIM-"))


def is_uuid_like(value: str | None) -> bool:
    return bool(
        value
        and re.fullmatch(
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
            value.strip(),
            flags=re.IGNORECASE,
        )
    )


def format_display_date(value: object | None) -> str:
    if value is None or value == "":
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)


def optional_line(label: str, value: object | None) -> str:
    if value is None or value == "":
        return ""
    return f"{label} : {value}\n"


def optional_bool_line(label: str, value: bool | None) -> str:
    if value is None:
        return ""
    return f"{label} : {'oui' if value else 'non'}\n"


def format_amount(amount: object) -> str:
    return f"{amount:.2f}"


def format_evidence_list(order: ClaimOrder) -> str:
    if not order.evidence_files:
        return "- Aucune piece jointe pour le moment"
    return "\n".join(
        f"- {evidence.original_filename}"
        for evidence in sorted(order.evidence_files, key=lambda item: item.id)
    )


def format_restaurant_signature(restaurant: Any) -> str:
    lines = [restaurant.name or restaurant.sender_email]
    if getattr(restaurant, "address", None):
        lines.append(restaurant.address)
    if getattr(restaurant, "phone_number", None):
        lines.append(restaurant.phone_number)
    if getattr(restaurant, "sender_email", None):
        lines.append(restaurant.sender_email)
    return "\n".join(line for line in lines if line)


def render_template(draft_type: str, context: dict[str, Any]) -> str:
    template_path = TEMPLATE_DIR / f"{draft_type}.txt"
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)
