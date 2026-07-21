from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import ClaimOrder, GmailResponseAnalysis, InboundEmailMessage, User
from app.models.domain import utc_now
from app.schemas.domain import ClaimResponseReviewCreate
from app.services.audit import add_audit_log
from app.services.gmail_payment_signal_service import (
    current_response_text,
    message_has_explicit_payment_confirmation,
    normalize_payment_signal_text,
)
from app.services.openai_structured_analysis_service import AIGmailClassification, OpenAIStructuredAnalysisService
from app.services.response_review_service import (
    PROTECTED_ORDER_STATUSES,
    ResponseReviewError,
    create_response_review,
)

AUTO_APPLY_REVIEW_TYPES = {
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
    "evidence_requested",
    "information_requested",
}
MIN_AUTO_APPLY_CONFIDENCE = Decimal("0.70")
MAX_NOTES_LENGTH = 1200
MAX_REASON_LENGTH = 100


@dataclass(frozen=True)
class GmailResponseClassification:
    review_type: str
    confidence_score: Decimal
    reason: str
    detected_amount: Decimal | None = None
    evidence_requested: bool | None = None
    matched_keywords: dict[str, list[str]] | None = None
    notes: str | None = None


@dataclass(frozen=True)
class GmailResponseAnalyzeSummary:
    analyzed_messages: int = 0
    applied_reviews: int = 0
    manual_review_messages: int = 0
    ignored_messages: int = 0
    failed_messages: int = 0
    errors: tuple[str, ...] = ()


class GmailResponseIntelligenceService:
    def analyze_inbox(
        self,
        db: Session,
        user: User,
        *,
        apply_reviews: bool,
        limit: int = 100,
        only_unreviewed: bool = True,
    ) -> tuple[GmailResponseAnalyzeSummary, list[GmailResponseAnalysis]]:
        query = self.visible_messages_query(db, user).where(InboundEmailMessage.match_status.in_(["linked", "unlinked"]))
        if only_unreviewed:
            query = query.where(InboundEmailMessage.review_status == "unreviewed")
        messages = db.scalars(
            query.order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc()).limit(limit)
        ).all()

        analyses: list[GmailResponseAnalysis] = []
        analyzed = applied = manual = ignored = failed = 0
        errors: list[str] = []
        for message in messages:
            try:
                analysis = self.analyze_message(db, user, message, apply_review=apply_reviews)
                analyses.append(analysis)
                if analysis.status == "applied":
                    applied += 1
                elif analysis.status == "manual_review":
                    manual += 1
                elif analysis.status == "ignored":
                    ignored += 1
                elif analysis.status == "failed":
                    failed += 1
                else:
                    analyzed += 1
            except ResponseReviewError as exc:
                failed += 1
                errors.append(exc.message)
            except ValueError as exc:
                failed += 1
                errors.append(str(exc))

        return (
            GmailResponseAnalyzeSummary(
                analyzed_messages=analyzed,
                applied_reviews=applied,
                manual_review_messages=manual,
                ignored_messages=ignored,
                failed_messages=failed,
                errors=tuple(errors),
            ),
            analyses,
        )

    def analyze_message(
        self,
        db: Session,
        user: User,
        message: InboundEmailMessage,
        *,
        apply_review: bool,
    ) -> GmailResponseAnalysis:
        self.ensure_message_access(db, user, message)
        order = message.order if message.order_id else None
        classification = self.guard_positive_payment_classification(message, self.classify_message(message))
        analysis = self.upsert_analysis(db, user, message, order, classification)

        if message.match_status != "linked" or order is None:
            analysis.status = "manual_review"
            analysis.reason = limit_reason(f"message_not_linked_to_order:{classification.reason}")
            analysis.error_message = None
            db.flush()
            return analysis

        if message.review_status != "unreviewed":
            analysis.status = "ignored"
            analysis.reason = "already_reviewed"
            analysis.error_message = None
            db.flush()
            return analysis

        if order.status in PROTECTED_ORDER_STATUSES:
            analysis.status = "ignored"
            analysis.reason = f"order_already_final:{order.status}"
            analysis.error_message = None
            message.review_status = "ignored"
            message.reviewed_at = utc_now()
            message.reviewed_by_user_id = user.id
            message.updated_at = utc_now()
            db.flush()
            return analysis

        if not apply_review or not self.should_apply(analysis):
            analysis.status = "manual_review" if analysis.recommended_review_type == "manual_review" else "analyzed"
            db.flush()
            return analysis

        payload = ClaimResponseReviewCreate(
            inbound_message_id=message.id,
            review_type=analysis.recommended_review_type,  # type: ignore[arg-type]
            recovered_amount=analysis.detected_amount if analysis.recommended_review_type == "payment_confirmed" else None,
            expected_payment_date=analysis.expected_payment_date,
            refusal_reason=analysis.notes if analysis.recommended_review_type == "refused" else None,
            evidence_requested=True if analysis.recommended_review_type == "evidence_requested" else None,
            notes=analysis.notes,
        )
        try:
            review = create_response_review(db, order=order, user=user, payload=payload)
        except ResponseReviewError as exc:
            analysis.status = "failed"
            analysis.error_message = exc.message
            db.flush()
            raise

        analysis.status = "applied"
        analysis.response_review_id = review.id
        analysis.applied_by_user_id = user.id
        analysis.applied_at = utc_now()
        analysis.error_message = None
        db.flush()
        add_audit_log(
            db,
            entity_type="gmail_response_analysis",
            entity_id=analysis.id,
            action="gmail_response_analysis.applied",
            user_id=user.id,
            new_value={
                "inbound_message_id": message.id,
                "order_id": order.id,
                "review_type": analysis.recommended_review_type,
                "response_review_id": review.id,
            },
        )
        return analysis

    @staticmethod
    def guard_positive_payment_classification(
        message: InboundEmailMessage,
        classification: GmailResponseClassification,
    ) -> GmailResponseClassification:
        if classification.review_type not in {"accepted", "payment_to_verify", "payment_confirmed"}:
            return classification
        if message_has_explicit_payment_confirmation(message):
            return classification
        return GmailResponseClassification(
            review_type="manual_review",
            confidence_score=min(classification.confidence_score, Decimal("0.50")),
            reason="positive_without_explicit_payment_confirmation",
            detected_amount=classification.detected_amount,
            evidence_requested=classification.evidence_requested,
            matched_keywords=classification.matched_keywords,
            notes=limited_note(
                "Signal positif ambigu: aucun montant approuve ni promesse explicite de paiement.",
                classification.notes,
            ),
        )

    def classify_message(self, message: InboundEmailMessage) -> GmailResponseClassification:
        text = normalize_text(current_response_text(message))
        is_starred = message_has_provider_label(message, "STARRED")
        amount = detect_amount(text)
        matches = {key: matching_keywords(text, keywords) for key, keywords in KEYWORDS.items()}
        pattern_positive_matches = positive_payment_pattern_matches(text)
        if pattern_positive_matches:
            matches["payment_confirmed"] = [*matches["payment_confirmed"], *pattern_positive_matches]
        if is_starred:
            matches["gmail_labels"] = ["STARRED"]
        strong_groups = {key for key, values in matches.items() if values}

        if not text.strip() and not is_starred:
            return GmailResponseClassification(
                review_type="manual_review",
                confidence_score=Decimal("0.20"),
                reason="empty_message",
                matched_keywords=matches,
                notes="Email vide ou non lisible. Revue humaine requise.",
            )

        if "payment_confirmed" in strong_groups:
            if amount is not None:
                return GmailResponseClassification(
                    review_type="payment_confirmed",
                    confidence_score=Decimal("0.92"),
                    reason="payment_confirmed_with_amount",
                    detected_amount=amount,
                    matched_keywords=matches,
                    notes=build_notes("Paiement confirme avec montant detecte.", message, matches),
                )
            return GmailResponseClassification(
                review_type="payment_to_verify",
                confidence_score=Decimal("0.78"),
                reason="payment_confirmed_without_amount",
                matched_keywords=matches,
                notes=build_notes("Paiement annonce sans montant exploitable.", message, matches),
            )

        positive_groups = strong_groups.intersection({"payment_confirmed", "payment_to_verify", "accepted"})
        negative_groups = strong_groups.intersection({"refused"})
        if positive_groups and negative_groups:
            return GmailResponseClassification(
                review_type="manual_review",
                confidence_score=Decimal("0.45"),
                reason="conflicting_positive_negative_keywords",
                detected_amount=amount,
                matched_keywords=matches,
                notes=build_notes("Signaux positifs et negatifs detectes dans le meme email.", message, matches),
            )

        if "payment_to_verify" in strong_groups:
            return GmailResponseClassification(
                review_type="payment_to_verify",
                confidence_score=Decimal("0.82"),
                reason="payment_to_verify_keywords",
                detected_amount=amount,
                matched_keywords=matches,
                notes=build_notes("Uber annonce une regularisation ou un paiement a verifier.", message, matches),
            )

        if "accepted" in strong_groups:
            return GmailResponseClassification(
                review_type="accepted",
                confidence_score=Decimal("0.80"),
                reason="accepted_keywords",
                detected_amount=amount,
                matched_keywords=matches,
                notes=build_notes("Uber semble accepter la demande.", message, matches),
            )

        if is_starred:
            return GmailResponseClassification(
                review_type="refused",
                confidence_score=Decimal("0.95"),
                reason="gmail_starred_urgent_followup",
                matched_keywords=matches,
                notes=build_notes("Email marque avec une etoile Gmail: refus Uber a relancer en urgence.", message, matches),
            )

        if "evidence_requested" in strong_groups:
            return GmailResponseClassification(
                review_type="evidence_requested",
                confidence_score=Decimal("0.86"),
                reason="evidence_requested_keywords",
                detected_amount=amount,
                evidence_requested=True,
                matched_keywords=matches,
                notes=build_notes("Uber demande des preuves ou informations justificatives.", message, matches),
            )

        if "refused" in strong_groups:
            return GmailResponseClassification(
                review_type="refused",
                confidence_score=Decimal("0.84"),
                reason="refused_keywords",
                matched_keywords=matches,
                notes=build_notes("Uber semble refuser la demande. Le dossier reste appelable.", message, matches),
            )

        if "information_requested" in strong_groups:
            return GmailResponseClassification(
                review_type="information_requested",
                confidence_score=Decimal("0.74"),
                reason="information_requested_keywords",
                matched_keywords=matches,
                notes=build_notes("Uber demande des informations complementaires.", message, matches),
            )

        if "followup_needed" in strong_groups:
            return GmailResponseClassification(
                review_type="followup_needed",
                confidence_score=Decimal("0.62"),
                reason="waiting_or_under_review_keywords",
                matched_keywords=matches,
                notes=build_notes("Uber indique que le dossier est en cours de traitement.", message, matches),
            )

        ai_classification = self.classify_message_with_ai(message, text, matches)
        if ai_classification is not None:
            return ai_classification

        return GmailResponseClassification(
            review_type="manual_review",
            confidence_score=Decimal("0.35"),
            reason="no_reliable_decision_detected",
            matched_keywords=matches,
            notes=build_notes("Aucune decision Uber fiable detectee.", message, matches),
        )

    def classify_message_with_ai(
        self,
        message: InboundEmailMessage,
        normalized_text: str,
        matches: dict[str, list[str]],
    ) -> GmailResponseClassification | None:
        order_context = None
        if message.order is not None:
            order_context = {
                "order_id": message.order.id,
                "restaurant_id": message.order.restaurant_id,
                "uber_order_number": message.order.uber_order_number,
                "customer_name": message.order.customer_name,
                "order_amount": str(message.order.order_amount) if message.order.order_amount is not None else None,
                "status": message.order.status,
            }
        ai = OpenAIStructuredAnalysisService().analyze_gmail_message(
            subject=message.subject,
            snippet=message.snippet,
            body_text=message.body_text,
            labels=message.provider_labels_json or [],
            order_context=order_context,
        )
        if ai is None:
            return None
        return self.guard_ai_classification(ai, normalized_text, matches, message)

    def guard_ai_classification(
        self,
        ai: AIGmailClassification,
        normalized_text: str,
        matches: dict[str, list[str]],
        message: InboundEmailMessage,
    ) -> GmailResponseClassification | None:
        settings = get_settings()
        min_confidence = Decimal(str(settings.ai_gmail_min_confidence))
        if ai.confidence < min_confidence:
            return None
        allowed = {
            "accepted",
            "payment_to_verify",
            "payment_confirmed",
            "refused",
            "evidence_requested",
            "information_requested",
            "followup_needed",
            "manual_review",
        }
        if ai.review_type not in allowed:
            return None
        positive_groups = {key for key in ("payment_confirmed", "payment_to_verify", "accepted") if matches.get(key)}
        negative_groups = {key for key in ("refused",) if matches.get(key)}
        if positive_groups and negative_groups:
            return GmailResponseClassification(
                review_type="manual_review",
                confidence_score=Decimal("0.45"),
                reason="ai_blocked_conflicting_positive_negative_keywords",
                detected_amount=ai.detected_amount,
                matched_keywords={**matches, "ai": [ai.reason]},
                notes=build_notes("IA bloquee: signaux positifs et negatifs contradictoires.", message, matches),
            )
        if ai.review_type == "payment_confirmed" and ai.detected_amount is None:
            return GmailResponseClassification(
                review_type="payment_to_verify",
                confidence_score=min(ai.confidence, Decimal("0.78")),
                reason="ai_payment_without_amount",
                matched_keywords={**matches, "ai": [ai.reason]},
                notes=limited_note("IA detecte un paiement mais aucun montant explicite exploitable.", ai.notes),
            )
        if ai.review_type == "refused" and any(token in normalized_text for token in ("payment has been issued", "paiement effectue", "montant verse")):
            return None
        if ai.review_type == "manual_review":
            return GmailResponseClassification(
                review_type="manual_review",
                confidence_score=ai.confidence,
                reason=f"ai:{ai.reason}"[:100],
                detected_amount=ai.detected_amount,
                evidence_requested=ai.evidence_requested,
                matched_keywords={**matches, "ai": [ai.reason]},
                notes=limited_note("IA demande revue humaine.", ai.notes),
            )
        return GmailResponseClassification(
            review_type=ai.review_type,
            confidence_score=min(ai.confidence, Decimal("0.95")),
            reason=f"ai:{ai.reason}"[:100],
            detected_amount=ai.detected_amount,
            evidence_requested=ai.evidence_requested,
            matched_keywords={**matches, "ai": [ai.reason]},
            notes=limited_note("IA Gmail appliquee avec garde-fous.", ai.notes),
        )

    def upsert_analysis(
        self,
        db: Session,
        user: User,
        message: InboundEmailMessage,
        order: ClaimOrder | None,
        classification: GmailResponseClassification,
    ) -> GmailResponseAnalysis:
        analysis = db.scalar(
            select(GmailResponseAnalysis).where(GmailResponseAnalysis.inbound_message_id == message.id)
        )
        if analysis is None:
            analysis = GmailResponseAnalysis(inbound_message_id=message.id)
            db.add(analysis)
        analysis.order_id = order.id if order else None
        analysis.analyzed_by_user_id = user.id
        analysis.recommended_review_type = classification.review_type
        analysis.status = "manual_review" if classification.review_type == "manual_review" else "analyzed"
        analysis.confidence_score = classification.confidence_score
        analysis.reason = limit_reason(classification.reason)
        analysis.detected_amount = classification.detected_amount
        analysis.expected_payment_date = None
        analysis.evidence_requested = classification.evidence_requested
        analysis.matched_keywords_json = classification.matched_keywords
        analysis.notes = classification.notes
        analysis.error_message = None
        analysis.updated_at = utc_now()
        db.flush()
        add_audit_log(
            db,
            entity_type="gmail_response_analysis",
            entity_id=analysis.id,
            action="gmail_response_analysis.analyzed",
            user_id=user.id,
            new_value={
                "inbound_message_id": message.id,
                "order_id": analysis.order_id,
                "recommended_review_type": analysis.recommended_review_type,
                "confidence_score": str(analysis.confidence_score),
                "reason": analysis.reason,
            },
        )
        return analysis

    def should_apply(self, analysis: GmailResponseAnalysis) -> bool:
        if analysis.recommended_review_type not in AUTO_APPLY_REVIEW_TYPES:
            return False
        if analysis.confidence_score is None or analysis.confidence_score < MIN_AUTO_APPLY_CONFIDENCE:
            return False
        if analysis.recommended_review_type == "payment_confirmed" and analysis.detected_amount is None:
            return False
        return True

    def ensure_message_access(self, db: Session, user: User, message: InboundEmailMessage) -> None:
        if user.role == "staff":
            raise ValueError("Staff cannot analyze Gmail responses")
        if message.order_id is not None:
            if not message.order or not can_access_restaurant(db, user, message.order.restaurant_id):
                raise ValueError("Inbound message access denied")
            return
        accessible_ids = get_accessible_restaurant_ids(db, user)
        if accessible_ids == []:
            raise ValueError("Inbound message access denied")

    def visible_messages_query(self, db: Session, user: User):
        query = select(InboundEmailMessage)
        accessible_ids = get_accessible_restaurant_ids(db, user)
        if accessible_ids is None:
            return query
        if not accessible_ids:
            return query.where(InboundEmailMessage.id == -1)
        return query.outerjoin(ClaimOrder, InboundEmailMessage.order_id == ClaimOrder.id).where(
            (InboundEmailMessage.order_id.is_(None)) | (ClaimOrder.restaurant_id.in_(accessible_ids))
        )


KEYWORDS: dict[str, tuple[str, ...]] = {
    "evidence_requested": (
        "waiting for your reply",
        "support waiting for your reply",
        "please provide proof",
        "please provide evidence",
        "send us proof",
        "send evidence",
        "additional evidence",
        "supporting evidence",
        "upload proof",
        "provide a photo",
        "provide photos",
        "receipt",
        "screenshot",
        "preuve",
        "preuves",
        "justificatif",
        "justificatifs",
        "capture",
        "photo",
        "ticket",
        "details de commande",
        "informations justificatives",
        "attendons votre reponse",
        "en attente de votre reponse",
        "merci de fournir",
        "merci de nous fournir",
        "merci de transmettre",
        "merci de nous transmettre",
        "veuillez fournir",
        "veuillez transmettre",
    ),
    "payment_confirmed": (
        "payment has been issued",
        "payment was processed",
        "payment processed",
        "we have paid",
        "we paid",
        "we have approved a payment",
        "payment approved",
        "refund approved",
        "reimbursement approved",
        "we have credited",
        "we will credit",
        "credited to your account",
        "amount has been added",
        "paid out",
        "payout completed",
        "paiement effectue",
        "paiement confirme",
        "paiement accorde",
        "paiement a ete accorde",
        "reglement effectue",
        "montant verse",
        "montant credite",
        "compensation versee",
        "compensation accordee",
        "remboursement effectue",
        "remboursement accorde",
        "remboursement a ete accorde",
        "regularisation effectuee",
        "regularisation accordee",
        "ajustement effectue",
        "ajustement accorde",
        "ajustement applique",
        "ajustement a ete applique",
        "nous avons applique un ajustement",
        "nous avons ajuste votre paiement",
        "votre paiement a ete ajuste",
        "nous avons procede au paiement",
        "nous avons procede a un paiement",
        "nous avons credite",
        "nous vous avons credite",
        "credite sur votre compte",
        "montant ajoute",
        "vous avez percu l'integralite du paiement",
        "vous avez donc percu l'integralite du paiement",
        "vous avez recu l'integralite du paiement",
        "you received the full payment",
        "you have received the full payment",
        "you were paid in full",
        "we adjusted your payment",
        "we have adjusted your payment",
    ),
    "payment_to_verify": (
        "will be paid",
        "will receive",
        "you will receive",
        "we will reimburse",
        "we will compensate",
        "approved a payment",
        "next payout",
        "sera verse",
        "vous recevrez",
        "prochain versement",
        "regularisation sera",
        "paiement a venir",
        "compensation a venir",
        "sera credite",
        "sera ajoute a votre prochain versement",
        "sera ajoutee a votre prochain versement",
        "apparaitra dans votre prochain versement",
        "apparaitra sur votre prochain versement",
        "ajoute a votre prochain versement",
        "ajoutee a votre prochain versement",
        "prochain paiement",
        "nous allons vous verser",
        "vous recevrez un paiement",
        "vous recevrez ce montant",
    ),
    "accepted": (
        "claim approved",
        "approved your claim",
        "we approved",
        "request approved",
        "accepted your request",
        "nous acceptons",
        "demande acceptee",
        "demande approuvee",
        "reclamation acceptee",
        "regularisation acceptee",
        "eligible au remboursement",
    ),
    "refused": (
        "unable to reimburse",
        "cannot reimburse",
        "can't reimburse",
        "not eligible",
        "denied",
        "rejected",
        "declined",
        "will not reimburse",
        "no reimbursement",
        "no compensation",
        "not able to compensate",
        "we are unable",
        "we cannot",
        "refuse",
        "refus",
        "refusee",
        "rejetee",
        "rejete",
        "pas eligible",
        "ne pouvons pas",
        "aucun remboursement",
        "pas de remboursement",
        "aucune compensation",
        "pas de compensation",
        "decision maintenue",
        "maintenons notre decision",
        "nous maintenons",
        "ne sommes pas en mesure",
        "nous ne pourrons pas",
        "pas possible de rembourser",
    ),
    "information_requested": (
        "need more information",
        "additional information",
        "more details",
        "clarification",
        "could you confirm",
        "informations complementaires",
        "plus d informations",
        "details supplementaires",
        "pouvez vous confirmer",
    ),
    "followup_needed": (
        "under review",
        "we are reviewing",
        "we are investigating",
        "we'll get back",
        "we will get back",
        "in progress",
        "en cours d examen",
        "en cours de traitement",
        "nous examinons",
        "nous reviendrons vers vous",
        "submitted",
        "support submitted",
        "case submitted",
        "demande soumise",
        "dossier soumis",
        "demande envoyee",
        "requete envoyee",
        "restaurant support help center envoye",
        "nous vous confirmons avoir recu",
        "nous vous confirmons avoir soumis",
    ),
}


def normalize_text(value: str) -> str:
    return normalize_payment_signal_text(value)


def matching_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if normalize_text(keyword) in text]


def positive_payment_pattern_matches(text: str) -> list[str]:
    patterns = {
        "payment_approved_pattern": r"\bpayment\b.{0,80}\b(?:approved|issued|processed|credited)\b",
        "refund_approved_pattern": r"\b(?:refund|reimbursement)\b.{0,80}\bapproved\b",
        "paiement_accorde_pattern": r"\bpaiement\b.{0,80}\b(?:accorde|effectue|confirme|credite|verse)\b",
        "remboursement_accorde_pattern": r"\bremboursement\b.{0,80}\b(?:accorde|effectue|confirme|credite|verse)\b",
        "regularisation_accordee_pattern": r"\bregularisation\b.{0,80}\b(?:accordee|effectuee|confirmee|creditee|versee)\b",
        "ajustement_accorde_pattern": r"\bajustement\b.{0,80}\b(?:accorde|effectue|confirme|credite|verse)\b",
        "paiement_ajuste_pattern": r"\b(?:avons\s+ajuste\s+votre\s+paiement|votre\s+paiement\s+a\s+ete\s+ajuste)\b",
        "payment_adjusted_pattern": r"\b(?:we\s+(?:have\s+)?adjusted\s+your\s+payment|your\s+payment\s+was\s+adjusted)\b",
        "prochain_versement_pattern": r"\b(?:sera|a ete)?\s*(?:ajoutee?|creditee?)\b.{0,80}\bprochain versement\b",
        "paiement_prochain_versement_pattern": r"\b(?:paiement|montant|regularisation|compensation)\b.{0,100}\bprochain versement\b",
    }
    matches: list[str] = []
    for name, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            if not positive_payment_match_is_negated(text, match.start(), match.end()):
                matches.append(name)
                break
    return matches


def positive_payment_match_is_negated(text: str, start: int, end: int) -> bool:
    context = text[max(0, start - 40) : min(len(text), end + 20)]
    negated_phrases = (
        "aucun remboursement",
        "aucune compensation",
        "pas de remboursement",
        "pas de compensation",
        "no refund",
        "no reimbursement",
        "no compensation",
        "not eligible",
        "will not reimburse",
    )
    if any(phrase in context for phrase in negated_phrases):
        return True
    return bool(re.search(r"\bne\b.{0,40}\b(?:pas|aucun|aucune)\b", context))


def message_has_provider_label(message: InboundEmailMessage, label: str) -> bool:
    wanted = label.strip().casefold()
    return any(str(value).strip().casefold() == wanted for value in (message.provider_labels_json or []))


def detect_amount(text: str) -> Decimal | None:
    number = r"-?(?:\d{1,3}(?:[ .]\d{3})+(?:[,.]\d{1,3})?|\d+(?:[,.]\d{1,3})?)"
    decimal_number = r"-?(?:\d{1,3}(?:[ .]\d{3})*[,.]\d{1,3}|\d+[,.]\d{1,3})"
    amount_patterns = [
        rf"(?<![\w.,])(?:€\s*)?({number})\s*(?:€|eur|euros?)(?![\w.,])",
        rf"(?:amount|montant|payment|paiement|compensation|reimbursement|remboursement)\D{{0,20}}"
        rf"(?<![\w.,])({decimal_number})(?![\w.,])",
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return parse_decimal_amount(match.group(1))
        except InvalidOperation:
            continue
    return None


def parse_decimal_amount(value: str) -> Decimal:
    cleaned = value.strip().replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    return abs(Decimal(cleaned)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_notes(prefix: str, message: InboundEmailMessage, matches: dict[str, list[str]]) -> str:
    snippet = clean_human_snippet(message.snippet or message.subject or message.body_text or "")
    if snippet:
        return f"{prefix} Resume du mail Uber: {snippet}"[:MAX_NOTES_LENGTH]
    return prefix[:MAX_NOTES_LENGTH]


def limited_note(prefix: str, note: str | None) -> str:
    return f"{prefix} {note or ''}".strip()[:MAX_NOTES_LENGTH]


def limit_reason(reason: str | None) -> str:
    value = (reason or "unknown").strip() or "unknown"
    return value[:MAX_REASON_LENGTH]


def clean_human_snippet(value: str) -> str:
    cleaned = re.sub(r"(?is)please enter your reply above this line.*", "", value or "")
    cleaned = re.sub(r"(?is)replies below this line will not be received.*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:240]
