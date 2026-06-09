from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings


@dataclass(frozen=True)
class RefusalPolicyResult:
    recommended_next_action: str
    required_evidence_types: list[str]
    confidence: Decimal
    reason: str


def analyze_refusal_text(
    refusal_reason: str | None,
    notes: str | None = None,
    *,
    refusal_count: int = 1,
) -> RefusalPolicyResult:
    settings = get_settings()
    text = normalize_text(f"{refusal_reason or ''} {notes or ''}")

    if refusal_count >= settings.appeal_max_attempts_before_manual_review:
        return RefusalPolicyResult(
            recommended_next_action="manual_review",
            required_evidence_types=[],
            confidence=Decimal("0.90"),
            reason="manual_review_threshold_reached",
        )
    if refusal_count >= settings.appeal_max_attempts_before_escalation:
        return RefusalPolicyResult(
            recommended_next_action="request_escalation",
            required_evidence_types=[],
            confidence=Decimal("0.85"),
            reason="refusal_threshold_reached",
        )

    if has_any(text, ("preuve", "evidence", "document", "ticket", "receipt", "justificatif")):
        evidence_types = ["receipt"]
        if has_any(text, ("livraison", "delivery", "non recue", "non recu", "not received", "delivered")):
            evidence_types.append("delivery_proof")
        if has_any(text, ("prepar", "prepare", "prepared", "article", "missing item", "element manquant")):
            evidence_types.append("preparation_proof")
        return RefusalPolicyResult(
            recommended_next_action="provide_missing_evidence",
            required_evidence_types=dedupe(evidence_types),
            confidence=Decimal("0.80"),
            reason="missing_evidence_refusal",
        )
    if has_any(text, ("livraison", "delivery", "non recue", "non recu", "not received", "commande non recue")):
        return RefusalPolicyResult(
            recommended_next_action="clarify_delivery_proof",
            required_evidence_types=["delivery_proof"],
            confidence=Decimal("0.75"),
            reason="delivery_proof_needed",
        )
    if has_any(text, ("prepar", "prepare", "prepared", "annulation", "cancel")):
        return RefusalPolicyResult(
            recommended_next_action="clarify_order_prepared",
            required_evidence_types=["preparation_proof"],
            confidence=Decimal("0.75"),
            reason="preparation_clarification_needed",
        )
    if has_any(text, ("paiement", "payment", "versement", "payout", "reglement")):
        return RefusalPolicyResult(
            recommended_next_action="payment_verification",
            required_evidence_types=["uber_screenshot"],
            confidence=Decimal("0.70"),
            reason="payment_verification_needed",
        )
    if has_any(text, ("escal", "supervisor", "responsable", "manager")):
        return RefusalPolicyResult(
            recommended_next_action="request_escalation",
            required_evidence_types=[],
            confidence=Decimal("0.70"),
            reason="escalation_requested",
        )
    return RefusalPolicyResult(
        recommended_next_action="challenge_generic_refusal",
        required_evidence_types=[],
        confidence=Decimal("0.65"),
        reason="generic_refusal",
    )


def next_action_type_for_policy(action: str) -> str:
    return {
        "provide_missing_evidence": "request_more_evidence",
        "clarify_order_prepared": "create_appeal_draft",
        "clarify_delivery_proof": "create_appeal_draft",
        "challenge_generic_refusal": "create_appeal_draft",
        "request_escalation": "escalation",
        "payment_verification": "payment_verification",
        "manual_review": "manual_review",
    }.get(action, "manual_review")


def appeal_type_for_policy(action: str) -> str:
    return {
        "provide_missing_evidence": "evidence_reply",
        "clarify_order_prepared": "first_appeal",
        "clarify_delivery_proof": "first_appeal",
        "challenge_generic_refusal": "first_appeal",
        "request_escalation": "escalation",
        "payment_verification": "payment_verification",
        "manual_review": "manager_review",
    }.get(action, "first_appeal")


def template_type_for_policy(action: str, appeal_type: str) -> str:
    if appeal_type == "escalation" or action == "request_escalation":
        return "appeal_escalation"
    if appeal_type == "payment_verification" or action == "payment_verification":
        return "appeal_payment_verification"
    if appeal_type == "evidence_reply" or action == "provide_missing_evidence":
        return "appeal_missing_evidence_reply"
    if action == "clarify_delivery_proof":
        return "appeal_order_not_received_delivery_proof"
    if action == "clarify_order_prepared":
        return "appeal_order_prepared_before_cancellation"
    return "appeal_generic_refusal"


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return ascii_text.lower()


def has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
