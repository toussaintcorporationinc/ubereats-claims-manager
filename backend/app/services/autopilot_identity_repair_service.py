from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppealWorkflow, ClaimOrder, EmailThread, InboundEmailMessage, Restaurant, User
from app.models.domain import utc_now
from app.services.appeal_workflow_service import latest_analysis
from app.services.audit import add_audit_log
from app.services.openai_structured_analysis_service import AIProofExtraction, OpenAIStructuredAnalysisService
from app.services.order_identity_resolution_service import (
    ResolvedOrderIdentity,
    clean_customer_name,
    hydrate_order_identity_from_sources,
    identity_score,
    is_uuid_like,
    merge_identity,
)

MAX_IDENTITY_TEXT_CHARS = 18000
IDENTITY_MESSAGE_LIMIT = 35
MIN_AI_IDENTITY_CONFIDENCE = Decimal("0.65")


def repair_order_identity_for_autopilot(db: Session, user: User, order: ClaimOrder) -> bool:
    """Fill missing order identity from trusted local data, Gmail thread text, then AI if available."""
    before = snapshot_order_identity(order)
    changed = hydrate_order_identity_from_sources(db, order)

    identity = extract_identity_from_linked_text(db, order)
    if identity_score(identity) < 4:
        ai_identity = analyze_identity_with_ai(db, order)
        if ai_identity is not None:
            merge_identity(identity, ai_identity, prefer_display=True)

    if apply_identity_to_order(order, identity):
        changed = True

    if changed:
        db.flush()
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=order.id,
            action="autopilot.identity_repaired",
            user_id=user.id,
            old_value=before,
            new_value=snapshot_order_identity(order) | {"source": identity.source},
        )
    return changed


def repair_appeal_workflow_for_autopilot(db: Session, user: User, workflow: AppealWorkflow) -> bool:
    changed = False
    order = workflow.claim_order
    if order is not None:
        changed = repair_order_identity_for_autopilot(db, user, order) or changed

    if workflow.next_action_type != "manual_review" or order is None:
        return changed
    if not has_starred_linked_gmail_thread(db, order.id):
        return changed
    if not order_identity_is_complete(order):
        return changed

    analysis = latest_analysis(db, workflow)
    if analysis is not None and analysis.recommended_next_action == "provide_missing_evidence":
        return changed

    previous = {"status": workflow.status, "next_action_type": workflow.next_action_type}
    workflow.next_action_type = "review_refusal"
    if workflow.status == "paused":
        workflow.status = "appeal_needed"
    workflow.next_action_at = utc_now()
    workflow.updated_at = utc_now()
    db.flush()
    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=workflow.id,
        action="autopilot.manual_review_reopened_from_starred_gmail",
        user_id=user.id,
        old_value=previous,
        new_value={"status": workflow.status, "next_action_type": workflow.next_action_type},
    )
    return True


def extract_identity_from_linked_text(db: Session, order: ClaimOrder) -> ResolvedOrderIdentity:
    text = collect_linked_identity_text(db, order)
    identity = ResolvedOrderIdentity(source="linked_gmail_thread")
    if not text:
        return identity

    identity.customer_name = extract_customer_name(text)
    order_number = extract_order_number(text)
    if order_number:
        if is_uuid_like(order.uber_order_number):
            identity.display_id = order_number
        else:
            identity.order_number = order_number
            identity.display_id = order_number
    identity.order_date = extract_order_date(text)
    identity.order_amount = extract_amount(text)
    identity.currency = "EUR" if identity.order_amount is not None else None

    restaurant = extract_restaurant_name(text, known_restaurant_names(db, order))
    if restaurant:
        identity.source = f"{identity.source}:restaurant:{restaurant}"
    return identity


def analyze_identity_with_ai(db: Session, order: ClaimOrder) -> ResolvedOrderIdentity | None:
    text = collect_linked_identity_text(db, order)
    if not text:
        return None
    result = OpenAIStructuredAnalysisService().analyze_order_identity_text(
        text=text,
        restaurant_names=known_restaurant_names(db, order),
        order_context={
            "order_id": order.id,
            "restaurant": order.restaurant.name if order.restaurant else None,
            "uber_order_number": order.uber_order_number,
            "internal_reference": order.internal_reference,
            "customer_name": order.customer_name,
            "order_date": order.order_date,
            "order_amount": order.order_amount,
        },
    )
    if result is None or result.confidence < MIN_AI_IDENTITY_CONFIDENCE:
        return None
    identity = identity_from_ai_result(result)
    identity.source = "openai_gmail_identity"
    return identity


def identity_from_ai_result(result: AIProofExtraction) -> ResolvedOrderIdentity:
    return ResolvedOrderIdentity(
        order_number=result.order_number,
        display_id=result.display_id,
        customer_name=clean_customer_name(result.customer_name),
        order_date=result.order_date,
        order_amount=result.order_amount,
        currency=result.currency,
        source="openai_gmail_identity",
    )


def apply_identity_to_order(order: ClaimOrder, identity: ResolvedOrderIdentity) -> bool:
    changed = False
    customer_name = clean_customer_name(identity.customer_name)
    if customer_name and not order.customer_name:
        order.customer_name = customer_name
        changed = True
    if identity.order_date and order.order_date is None:
        order.order_date = identity.order_date
        changed = True
    if identity.order_amount is not None and order.order_amount is None:
        order.order_amount = identity.order_amount
        changed = True
    if identity.currency and not order.currency:
        order.currency = identity.currency[:3].upper()
        changed = True

    display_id = clean_order_identifier(identity.display_id or identity.order_number)
    if display_id and not is_uuid_like(display_id) and not order.internal_reference:
        order.internal_reference = display_id
        changed = True
    if identity.order_number and not is_uuid_like(identity.order_number) and is_uuid_like(order.uber_order_number):
        if not order.internal_reference:
            order.internal_reference = identity.order_number
            changed = True
    return changed


def collect_linked_identity_text(db: Session, order: ClaimOrder) -> str:
    chunks: list[str] = []
    if order.notes:
        chunks.append(f"ORDER NOTES:\n{order.notes}")

    messages = db.scalars(
        select(InboundEmailMessage)
        .where(InboundEmailMessage.order_id == order.id)
        .order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
        .limit(IDENTITY_MESSAGE_LIMIT)
    ).all()
    for message in messages:
        chunks.append(
            "\n".join(
                part
                for part in (
                    f"FROM: {message.from_email or ''}",
                    f"TO: {message.to_email or ''}",
                    f"SUBJECT: {message.subject or ''}",
                    f"SNIPPET: {message.snippet or ''}",
                    f"BODY:\n{message.body_text or ''}",
                )
                if part.strip()
            )
        )

    threads = db.scalars(
        select(EmailThread)
        .where(EmailThread.order_id == order.id)
        .order_by(EmailThread.created_at.desc(), EmailThread.id.desc())
        .limit(IDENTITY_MESSAGE_LIMIT)
    ).all()
    for thread in threads:
        chunks.append(f"THREAD SUBJECT: {thread.subject or ''}\nTHREAD BODY:\n{thread.body or ''}")

    return "\n\n---\n\n".join(chunks)[:MAX_IDENTITY_TEXT_CHARS]


def has_starred_linked_gmail_thread(db: Session, order_id: int) -> bool:
    messages = db.scalars(
        select(InboundEmailMessage)
        .where(
            InboundEmailMessage.order_id == order_id,
            InboundEmailMessage.provider == "gmail",
            InboundEmailMessage.provider_thread_id.is_not(None),
        )
        .order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
        .limit(IDENTITY_MESSAGE_LIMIT)
    ).all()
    for message in messages:
        labels = {str(label).strip().casefold() for label in (message.provider_labels_json or [])}
        if "starred" in labels:
            return True
    return False


def order_identity_is_complete(order: ClaimOrder) -> bool:
    return bool(
        str(order.uber_order_number or "").strip()
        and str(order.customer_name or "").strip()
        and order.order_date is not None
        and order.restaurant is not None
        and str(order.restaurant.name or "").strip()
    )


def extract_customer_name(text: str) -> str | None:
    normalized = compact_text(text)
    patterns = [
        r"(?:demande\s+de\s+remboursement|contestation\s+de\s+remboursement)\s+de\s+(.{2,80}?)(?:\s*,?\s*(?:num[eé]ro|numero|n[°o])\s+de\s+commande|\s+car\b|\s+pour\b)",
        r"(?:demande\s+de\s+remboursement\s+de\s+commande|contestation\s+de\s+remboursement\s+de\s+commande)\s+de\s+(.{2,80}?)(?:\s*,?\s*(?:num[eé]ro|numero|n[°o])\s+de\s+commande|\s+car\b|\s+pour\b)",
        r"(?:annulation\s+de\s+commande|contestation\s+d[' ]annulation\s+de\s+commande)\s+de\s+(.{2,80}?)(?:\s*,?\s*(?:num[eé]ro|numero|n[°o])\s+de\s+commande|\s+car\b|\s+pour\b)",
        r"commande\s+uber\s+eats\s+de\s+(.{2,80}?)(?:\s*,?\s*(?:num[eé]ro|numero|n[°o])\s+de\s+commande|\s+du\b|\s+car\b)",
        r"(?:client|nom\s+client|customer)\s*[:\-]\s*(.{2,80}?)(?:\n|,|;|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        name = cleanup_name_candidate(match.group(1))
        if name:
            return name
    return None


def extract_order_number(text: str) -> str | None:
    normalized = compact_text(text)
    patterns = [
        r"(?:num[eé]ro|numero|n[°o])\s+(?:de\s+)?commande\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{3,40})",
        r"(?:commande|order)\s*(?:id|number|no|#)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{3,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return clean_order_identifier(match.group(1))
    return None


def extract_order_date(text: str) -> date | None:
    normalized = compact_text(text)
    for pattern in (r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"):
        match = re.search(pattern, normalized)
        if not match:
            continue
        try:
            if len(match.group(1)) == 4:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            year = int(match.group(3))
            if year < 100:
                year += 2000
            return date(year, int(match.group(2)), int(match.group(1)))
        except ValueError:
            continue
    return None


def extract_amount(text: str) -> Decimal | None:
    normalized = compact_text(text)
    patterns = [
        r"(?:montant\s+(?:concerne|concern[eé]|de\s+la\s+commande|commande)|montant\s+paye|total)\s*[:\-]?\s*(\d{1,5}(?:[,.]\d{1,2})?)\s*(?:eur|euro|euros|€)",
        r"\b(\d{1,5}(?:[,.]\d{1,2})?)\s*(?:eur|€)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return abs(Decimal(match.group(1).replace(",", "."))).quantize(Decimal("0.01"))
        except InvalidOperation:
            continue
    return None


def extract_restaurant_name(text: str, restaurant_names: list[str]) -> str | None:
    folded = text.casefold()
    for name in restaurant_names:
        if name and name.casefold() in folded:
            return name
    return None


def known_restaurant_names(db: Session, order: ClaimOrder) -> list[str]:
    names: list[str] = []
    if order.restaurant is not None and order.restaurant.name:
        names.append(order.restaurant.name)
    for name in db.scalars(select(Restaurant.name).where(Restaurant.active.is_(True))).all():
        if name and name not in names:
            names.append(name)
    return names


def compact_text(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text.replace("\xa0", " ")).strip()


def cleanup_name_candidate(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,:;-")
    cleaned = re.sub(r"\b(num[eé]ro|numero|commande|order|uber|eats)\b.*$", "", cleaned, flags=re.IGNORECASE).strip(" .,:;-")
    if len(cleaned) > 80:
        cleaned = cleaned[:80]
    return clean_customer_name(cleaned)


def clean_order_identifier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Z0-9\-]", "", value.upper()).strip("-")
    if len(cleaned) < 4 or len(cleaned) > 40:
        return None
    return cleaned


def snapshot_order_identity(order: ClaimOrder) -> dict[str, object | None]:
    return {
        "customer_name": order.customer_name,
        "uber_order_number": order.uber_order_number,
        "internal_reference": order.internal_reference,
        "order_date": order.order_date.isoformat() if isinstance(order.order_date, date) else None,
        "order_amount": str(order.order_amount) if order.order_amount is not None else None,
        "currency": order.currency,
    }
