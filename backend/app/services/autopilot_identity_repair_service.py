from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant
from app.models import AppealWorkflow, ClaimOrder, EmailThread, EvidenceFile, InboundEmailMessage, Restaurant, User
from app.models.domain import utc_now
from app.services.appeal_workflow_service import ensure_workflow_for_claim_order, latest_analysis
from app.services.audit import add_audit_log
from app.services.email_provider import InboundEmailAttachment
from app.services.file_storage_service import FileStorageError, resolve_evidence_path
from app.services.openai_structured_analysis_service import AIProofExtraction, OpenAIStructuredAnalysisService
from app.services.order_identity_resolution_service import (
    ResolvedOrderIdentity,
    clean_customer_name,
    hydrate_order_identity_from_sources,
    identity_score,
    is_uuid_like,
    merge_identity,
)
from app.services.restaurant_identity_service import (
    canonical_restaurant_display_name,
    canonical_restaurant_lookup_key,
    canonicalize_restaurant_names_in_text,
)

MAX_IDENTITY_TEXT_CHARS = 18000
IDENTITY_MESSAGE_LIMIT = 35
MIN_AI_IDENTITY_CONFIDENCE = Decimal("0.65")
MAX_PROOF_IMAGE_BYTES = 8 * 1024 * 1024
MAX_INBOUND_ATTACHMENT_AI_ANALYSES = 2
REQUIRED_ATTACHMENT_IDENTITY_FIELDS = ("restaurant", "customer_name", "order_number", "order_date", "order_amount")
INVALID_ORDER_IDENTIFIERS = {
    "BODY",
    "CORPS",
    "EXTRAIT",
    "FROM",
    "MESSAGE",
    "SNIPPET",
    "SUBJECT",
    "SUJET",
    "THREAD",
}
IDENTITY_REPAIR_PROTECTED_STATUSES = {
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "closed",
}


def repair_order_identity_for_autopilot(db: Session, user: User, order: ClaimOrder) -> bool:
    """Fill missing order identity from trusted local data, Gmail thread text, then AI if available."""
    before = snapshot_order_identity(order)
    changed = hydrate_order_identity_from_sources(db, order)

    identity = extract_identity_from_linked_text(db, order)
    if identity_score(identity) < 4:
        ai_identity = analyze_identity_with_ai(db, order)
        if ai_identity is not None:
            merge_identity(identity, ai_identity, prefer_display=True)
    if identity_score(identity) < 4:
        proof_identity = analyze_attached_evidence_with_ai(db, order)
        if proof_identity is not None:
            merge_identity(identity, proof_identity, prefer_display=True)

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


def repair_order_identity_from_inbound_attachments(
    db: Session,
    user: User,
    order: ClaimOrder,
    attachments: list[InboundEmailAttachment],
) -> bool:
    """Repair identity while a Gmail sync still has access to inbound image attachments."""
    if not attachments:
        return False
    before = snapshot_order_identity(order)
    identity = analyze_inbound_attachments_with_ai(db, order, attachments)
    if identity is None:
        return False
    if not apply_identity_to_order(order, identity):
        return False

    db.flush()
    add_audit_log(
        db,
        entity_type="claim_order",
        entity_id=order.id,
        action="autopilot.identity_repaired_from_gmail_attachment",
        user_id=user.id,
        old_value=before,
        new_value=snapshot_order_identity(order) | {"source": identity.source},
    )
    return True


def find_or_create_order_from_inbound_attachments(
    db: Session,
    user: User,
    attachments: list[InboundEmailAttachment],
    *,
    context_text: str = "",
) -> ClaimOrder | None:
    """Create or link a claim order from a starred Gmail proof image when no thread link exists yet."""
    if not attachments:
        return None
    result = analyze_best_inbound_attachment(db, attachments, context_text=context_text)
    if result is None or not ai_result_has_required_identity(result):
        return None
    restaurant = resolve_restaurant_from_ai_result(db, result)
    if restaurant is None or not can_access_restaurant(db, user, restaurant.id):
        return None

    identity = identity_from_ai_result(result)
    order = find_existing_order_for_identity(db, restaurant.id, identity)
    created = False
    if order is None:
        order_number = clean_order_identifier(identity.order_number or identity.display_id)
        if order_number is None:
            return None
        order = ClaimOrder(
            restaurant_id=restaurant.id,
            uber_order_number=order_number,
            internal_reference=clean_order_identifier(identity.display_id),
            customer_name=clean_customer_name(identity.customer_name),
            order_date=identity.order_date,
            order_amount=identity.order_amount,
            currency=(identity.currency or "EUR")[:3].upper(),
            accepted_by_restaurant=True,
            prepared_before_cancellation=True,
            loss_type=loss_type_from_ai_case_type(result.case_type),
            status="refused",
            notes="Dossier cree depuis un fil Gmail etoile et une preuve image lisible. Aucune donnee inventee.",
        )
        db.add(order)
        db.flush()
        created = True
    else:
        apply_identity_to_order(order, identity)
        mark_existing_order_refused_for_appeal(order)
        db.flush()

    ensure_workflow_for_claim_order(db, order, user)
    add_audit_log(
        db,
        entity_type="claim_order",
        entity_id=order.id,
        action="autopilot.order_created_from_starred_gmail_attachment" if created else "autopilot.order_linked_from_starred_gmail_attachment",
        user_id=user.id,
        new_value=snapshot_order_identity(order)
        | {
            "restaurant_id": restaurant.id,
            "source": "openai_starred_gmail_attachment",
            "case_type": result.case_type,
        },
    )
    return order


def find_or_create_order_from_starred_text(db: Session, user: User, text: str) -> ClaimOrder | None:
    """Create or link a claim order from a starred Gmail thread when the original proof was already sent."""
    if not text.strip():
        return None
    restaurant_names = known_active_restaurant_names(db)
    restaurant_name = extract_restaurant_name(text, restaurant_names)
    local_order_number = extract_order_number_deep(text)
    local_amount = extract_amount_deep(text)
    identity = ResolvedOrderIdentity(
        order_number=local_order_number,
        display_id=local_order_number,
        customer_name=extract_customer_name_deep(text),
        order_date=extract_order_date_deep(text),
        order_amount=local_amount,
        currency="EUR" if local_amount is not None else None,
        source="starred_gmail_thread_text",
    )

    restaurant = resolve_restaurant_from_name(db, restaurant_name)
    local_identity_ready = (
        restaurant is not None
        and can_access_restaurant(db, user, restaurant.id)
        and text_identity_has_required_fields(identity)
    )
    ai_result = None
    if not local_identity_ready:
        ai_result = OpenAIStructuredAnalysisService().analyze_order_identity_text(
            text=text,
            restaurant_names=restaurant_names,
            order_context={"source": "starred_gmail_unlinked_thread"},
        )
    if ai_result is not None and ai_result.confidence >= MIN_AI_IDENTITY_CONFIDENCE:
        ai_identity = identity_from_ai_result(ai_result)
        merge_identity_without_overriding_local_facts(identity, ai_identity)
        if ai_result.restaurant_name and not restaurant_name:
            restaurant_name = ai_result.restaurant_name
        identity.source = "openai_starred_gmail_thread_text"

    restaurant = resolve_restaurant_from_name(db, restaurant_name)
    if restaurant is None or not can_access_restaurant(db, user, restaurant.id):
        return None
    if not identity.order_number and identity.display_id:
        identity.order_number = identity.display_id
    if not identity.display_id and identity.order_number and not is_uuid_like(identity.order_number):
        identity.display_id = identity.order_number
    if not text_identity_has_required_fields(identity):
        return None

    order = create_or_update_order_from_identity(
        db,
        user,
        restaurant,
        identity,
        source="openai_starred_gmail_thread_text" if identity.source == "openai_starred_gmail_thread_text" else "starred_gmail_thread_text",
        case_type=case_type_from_text(text, ai_result.case_type if ai_result else None),
    )
    return order


def merge_identity_without_overriding_local_facts(
    target: ResolvedOrderIdentity,
    source: ResolvedOrderIdentity | None,
) -> None:
    """Let AI fill blanks, but never replace facts already read from Gmail text."""
    if source is None:
        return
    if not target.customer_name and source.customer_name:
        target.customer_name = source.customer_name
    if not target.order_number and source.order_number:
        target.order_number = source.order_number
    if not target.display_id and source.display_id:
        target.display_id = source.display_id
    if not target.order_date and source.order_date:
        target.order_date = source.order_date
    if target.order_amount is None and source.order_amount is not None:
        target.order_amount = source.order_amount
    if not target.currency and source.currency:
        target.currency = source.currency


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

    identity.customer_name = extract_customer_name_deep(text)
    order_number = extract_order_number_deep(text)
    if order_number:
        if is_uuid_like(order.uber_order_number):
            identity.display_id = order_number
        else:
            identity.order_number = order_number
            identity.display_id = order_number
    identity.order_date = extract_order_date_deep(text)
    identity.order_amount = extract_amount_deep(text)
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


def analyze_attached_evidence_with_ai(db: Session, order: ClaimOrder) -> ResolvedOrderIdentity | None:
    service = OpenAIStructuredAnalysisService()
    if not service.proof_enabled():
        return None
    evidence_files = db.scalars(
        select(EvidenceFile)
        .where(
            EvidenceFile.order_id == order.id,
            EvidenceFile.deleted_at.is_(None),
        )
        .order_by(EvidenceFile.id.desc())
        .limit(5)
    ).all()
    best: ResolvedOrderIdentity | None = None
    best_score = -1
    for evidence in evidence_files:
        mime_type = evidence.mime_type or ""
        if not mime_type.startswith("image/"):
            continue
        if evidence.file_size and evidence.file_size > MAX_PROOF_IMAGE_BYTES:
            continue
        try:
            path = resolve_evidence_path(evidence)
            image_bytes = path.read_bytes()
        except (OSError, FileStorageError):
            continue
        result = service.analyze_proof(
            extracted_text="",
            filename=evidence.original_filename,
            restaurant_names=known_restaurant_names(db, order),
            mime_type=mime_type,
            image_bytes=image_bytes,
        )
        if result is None or result.confidence < MIN_AI_IDENTITY_CONFIDENCE:
            continue
        identity = identity_from_ai_result(result)
        identity.source = f"openai_evidence_file:{evidence.id}"
        score = identity_score(identity)
        if score > best_score:
            best = identity
            best_score = score
        if score >= 4:
            return best
    return best


def analyze_inbound_attachments_with_ai(
    db: Session,
    order: ClaimOrder,
    attachments: list[InboundEmailAttachment],
) -> ResolvedOrderIdentity | None:
    service = OpenAIStructuredAnalysisService()
    if not service.proof_enabled():
        return None
    best: ResolvedOrderIdentity | None = None
    best_score = -1
    for index, attachment in enumerate(attachments[:5], start=1):
        mime_type = attachment.mime_type or ""
        if not mime_type.startswith("image/"):
            continue
        if len(attachment.content) > MAX_PROOF_IMAGE_BYTES:
            continue
        result = service.analyze_proof(
            extracted_text="",
            filename=attachment.filename,
            restaurant_names=known_restaurant_names(db, order),
            mime_type=mime_type,
            image_bytes=attachment.content,
        )
        if result is None or result.confidence < MIN_AI_IDENTITY_CONFIDENCE:
            continue
        identity = identity_from_ai_result(result)
        identity.source = f"openai_gmail_attachment:{index}:{attachment.filename}"
        score = identity_score(identity)
        if score > best_score:
            best = identity
            best_score = score
        if score >= 4:
            return best
    return best


def analyze_best_inbound_attachment(
    db: Session,
    attachments: list[InboundEmailAttachment],
    *,
    context_text: str = "",
) -> AIProofExtraction | None:
    service = OpenAIStructuredAnalysisService()
    if not service.proof_enabled():
        return None
    restaurant_names = list(db.scalars(select(Restaurant.name).where(Restaurant.active.is_(True)).order_by(Restaurant.name)).all())
    best: AIProofExtraction | None = None
    best_score = -1
    for attachment in attachments[:MAX_INBOUND_ATTACHMENT_AI_ANALYSES]:
        mime_type = attachment.mime_type or ""
        if not mime_type.startswith("image/"):
            continue
        if len(attachment.content) > MAX_PROOF_IMAGE_BYTES:
            continue
        result = service.analyze_proof(
            extracted_text=context_text[:12000],
            filename=attachment.filename,
            restaurant_names=restaurant_names,
            mime_type=mime_type,
            image_bytes=attachment.content,
        )
        if result is None or result.confidence < MIN_AI_IDENTITY_CONFIDENCE:
            continue
        score = ai_result_identity_score(result)
        if score > best_score:
            best = result
            best_score = score
        if score >= len(REQUIRED_ATTACHMENT_IDENTITY_FIELDS):
            return best
    return best


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


def ai_result_has_required_identity(result: AIProofExtraction) -> bool:
    return all(
        (
            resolve_truthy(result.restaurant_name),
            resolve_truthy(result.customer_name),
            resolve_truthy(result.order_number or result.display_id),
            result.order_date is not None,
            result.order_amount is not None,
        )
    )


def ai_result_identity_score(result: AIProofExtraction) -> int:
    return sum(
        1
        for value in (
            result.restaurant_name,
            result.customer_name,
            result.order_number or result.display_id,
            result.order_date,
            result.order_amount,
        )
        if resolve_truthy(value)
    )


def resolve_truthy(value: object) -> bool:
    return bool(str(value or "").strip())


def resolve_restaurant_from_ai_result(db: Session, result: AIProofExtraction) -> Restaurant | None:
    if not result.restaurant_name:
        return None
    return resolve_restaurant_from_name(db, result.restaurant_name)


def resolve_restaurant_from_name(db: Session, restaurant_name: str | None) -> Restaurant | None:
    if not restaurant_name:
        return None
    from app.services.evidence_ai_analysis_service import resolve_restaurant_display_name

    canonical_name = canonical_restaurant_display_name(restaurant_name)
    resolved_name = resolve_restaurant_display_name(db, canonical_name) or canonical_name
    lookup_key = canonical_restaurant_lookup_key(resolved_name)
    for restaurant in db.scalars(select(Restaurant).where(Restaurant.active.is_(True))).all():
        if restaurant.name and canonical_restaurant_lookup_key(restaurant.name) == lookup_key:
            return restaurant
    return None


def find_existing_order_for_identity(db: Session, restaurant_id: int, identity: ResolvedOrderIdentity) -> ClaimOrder | None:
    identifiers = [
        candidate
        for candidate in {
            clean_order_identifier(identity.order_number),
            clean_order_identifier(identity.display_id),
        }
        if candidate
    ]
    if not identifiers:
        return None
    return db.scalar(
        select(ClaimOrder)
        .where(
            ClaimOrder.restaurant_id == restaurant_id,
            (ClaimOrder.uber_order_number.in_(identifiers)) | (ClaimOrder.internal_reference.in_(identifiers)),
        )
        .order_by(ClaimOrder.id.desc())
    )


def loss_type_from_ai_case_type(case_type: str | None) -> str:
    if case_type == "cancellation":
        return "cancellation"
    if case_type == "refund":
        return "customer_refund"
    return "gmail_starred_proof"


def case_type_from_text(text: str, ai_case_type: str | None = None) -> str | None:
    if ai_case_type in {"cancellation", "refund"}:
        return ai_case_type
    normalized = text.casefold()
    if "annulation" in normalized or "cancel" in normalized:
        return "cancellation"
    if "remboursement" in normalized or "refund" in normalized:
        return "refund"
    return None


def text_identity_has_required_fields(identity: ResolvedOrderIdentity) -> bool:
    return bool(
        clean_order_identifier(identity.order_number or identity.display_id)
        and clean_customer_name(identity.customer_name)
    )


def create_or_update_order_from_identity(
    db: Session,
    user: User,
    restaurant: Restaurant,
    identity: ResolvedOrderIdentity,
    *,
    source: str,
    case_type: str | None,
) -> ClaimOrder | None:
    order = find_existing_order_for_identity(db, restaurant.id, identity)
    created = False
    if order is None:
        order_number = clean_order_identifier(identity.order_number or identity.display_id)
        if order_number is None:
            return None
        try:
            with db.begin_nested():
                order = ClaimOrder(
                    restaurant_id=restaurant.id,
                    uber_order_number=order_number,
                    internal_reference=clean_order_identifier(identity.display_id),
                    customer_name=clean_customer_name(identity.customer_name),
                    order_date=identity.order_date,
                    order_amount=identity.order_amount,
                    currency=(identity.currency or "EUR")[:3].upper(),
                    accepted_by_restaurant=True,
                    prepared_before_cancellation=True,
                    loss_type=loss_type_from_ai_case_type(case_type),
                    status="refused",
                    notes="Dossier cree depuis un fil Gmail etoile deja envoye. Relance autorisee dans le meme fil, sans inventer de preuve.",
                )
                db.add(order)
                db.flush()
            created = True
        except IntegrityError:
            # Gmail workers can discover the same thread/order through several
            # paths. A duplicate must attach to the existing dossier, never stop
            # the whole Gmail backlog.
            order = find_existing_order_for_identity(db, restaurant.id, identity)
            if order is None:
                raise
            apply_identity_to_order(order, identity)
            mark_existing_order_refused_for_appeal(order)
            db.flush()
    else:
        apply_identity_to_order(order, identity)
        mark_existing_order_refused_for_appeal(order)
        db.flush()

    ensure_workflow_for_claim_order(db, order, user)
    add_audit_log(
        db,
        entity_type="claim_order",
        entity_id=order.id,
        action="autopilot.order_created_from_starred_gmail_text" if created else "autopilot.order_linked_from_starred_gmail_text",
        user_id=user.id,
        new_value=snapshot_order_identity(order)
        | {
            "restaurant_id": restaurant.id,
            "source": source,
            "case_type": case_type,
        },
    )
    return order


def mark_existing_order_refused_for_appeal(order: ClaimOrder) -> None:
    if order.status in IDENTITY_REPAIR_PROTECTED_STATUSES:
        return
    order.status = "refused"
    order.updated_at = utc_now()


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
    folded = canonicalize_restaurant_names_in_text(text).casefold()
    for name in restaurant_names:
        canonical_name = canonical_restaurant_display_name(name)
        if canonical_name and canonical_name.casefold() in folded:
            return canonical_name
    return None


def known_restaurant_names(db: Session, order: ClaimOrder) -> list[str]:
    names: list[str] = []
    if order.restaurant is not None and order.restaurant.name:
        names.append(order.restaurant.name)
    for name in db.scalars(select(Restaurant.name).where(Restaurant.active.is_(True))).all():
        if name and name not in names:
            names.append(name)
    return names


def known_active_restaurant_names(db: Session) -> list[str]:
    return [
        name
        for name in db.scalars(select(Restaurant.name).where(Restaurant.active.is_(True)).order_by(Restaurant.name)).all()
        if name
    ]


def compact_text(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text.replace("\xa0", " ")).strip()


def normalize_search_text(text: str) -> str:
    compacted = compact_text(text)
    normalized = unicodedata.normalize("NFKD", compacted)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.replace("’", "'").replace("`", "'")


ORDER_NUMBER_LABEL_RE = r"(?:num\S{0,4}ro|numero|n\s*[°o])"
ORDER_NUMBER_DELIMITER_RE = rf"(?:{ORDER_NUMBER_LABEL_RE}\s+(?:de\s+)?commande|\border\s*(?:id|number|no|#)|\bcommande\s*(?:id|number|no|#))"


def extract_customer_name_deep(text: str) -> str | None:
    normalized = normalize_search_text(text)
    patterns = [
        rf"(?:je\s+(?:veux\s+)?contest(?:e|er)\s+)?l[' ]annulation\s+de\s+(?:la\s+)?commande\s+(?:de\s+|d[' ])(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        rf"(?:je\s+veux\s+)?contester\s+la\s+demande\s+de\s+remboursement\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        rf"(?:demande|contestation)\s+de\s+remboursement\s+de\s+commande\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        rf"(?:demande|contestation)\s+de\s+remboursement\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        rf"(?:je\s+veux\s+)?contester\s+l[' ]annulation\s+de\s+commande\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        rf"(?:annulation\s+de\s+commande|contestation\s+d[' ]annulation\s+de\s+commande)\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        rf"commande\s+uber\s+eats\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+du\b|\s+car\b)",
        rf"commande\s+de\s+(.{{2,80}}?)(?:\s*,?\s*{ORDER_NUMBER_DELIMITER_RE}|\s+car\b|\s+pour\b)",
        r"(?:client|nom\s+client|customer)\s*[:\-]\s*(.{2,80}?)(?:\n|,|;|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        name = cleanup_name_candidate(match.group(1))
        if name:
            return name
    return extract_customer_name(text)


def extract_order_number_deep(text: str) -> str | None:
    normalized = normalize_search_text(text)
    patterns = [
        rf"{ORDER_NUMBER_DELIMITER_RE}\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{{3,40}})",
        r"\b[A-Z][A-Za-z]{1,30}\s+[A-Z]\.?\s+([A-Z0-9]{4,12})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            identifier = clean_order_identifier(match.group(1))
            if identifier:
                return identifier
    return extract_order_number(text)


def extract_order_date_deep(text: str) -> date | None:
    normalized = normalize_search_text(text)
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
    return extract_order_date(text)


def extract_amount_deep(text: str) -> Decimal | None:
    normalized = normalize_search_text(text)
    patterns = [
        r"(?:montant\s+(?:concerne|de\s+la\s+commande|commande)|montant\s+paye|total)\s*[:\-]?\s*(\d{1,5}(?:[,.]\d{1,2})?)\s*(?:eur|euro|euros|\u20ac)",
        r"\b(\d{1,5}(?:[,.]\d{1,2})?)\s*(?:eur|\u20ac)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return abs(Decimal(match.group(1).replace(",", "."))).quantize(Decimal("0.01"))
        except InvalidOperation:
            continue
    return extract_amount(text)


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
    if cleaned in INVALID_ORDER_IDENTIFIERS:
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
