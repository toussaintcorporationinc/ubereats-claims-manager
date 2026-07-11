from app.models import InboundEmailMessage
from app.services.gmail_response_intelligence_service import GmailResponseIntelligenceService
from app.services.gmail_watched_thread_monitor_service import classify_unlinked_watched_message


def test_waiting_for_reply_is_evidence_requested() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-waiting",
        provider_thread_id="thread-waiting",
        subject="Contestation d'annulation de commande",
        body_text="Support WAITING FOR YOUR REPLY. Merci de nous transmettre une photo du ticket.",
    )

    classification = GmailResponseIntelligenceService().classify_message(message)

    assert classification.review_type == "evidence_requested"
    assert classification.reason == "evidence_requested_keywords"


def test_next_payout_adjustment_is_payment_to_verify() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-payout",
        provider_thread_id="thread-payout",
        subject="Contestation d'annulation de commande",
        body_text="Bonjour, un ajustement sera ajoute a votre prochain versement.",
        provider_labels_json=["STARRED"],
    )

    classification = GmailResponseIntelligenceService().classify_message(message)

    assert classification.review_type == "payment_to_verify"
    assert classification.reason == "payment_confirmed_without_amount"


def test_submitted_status_is_followup_needed_not_payment() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-submitted",
        provider_thread_id="thread-submitted",
        subject="Contestation d'annulation de commande",
        body_text="Support SUBMITTED. Nous vous confirmons avoir recu votre demande.",
    )

    classification = GmailResponseIntelligenceService().classify_message(message)

    assert classification.review_type == "followup_needed"
    assert classification.reason == "waiting_or_under_review_keywords"


def test_maintained_decision_is_refused() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-refused",
        provider_thread_id="thread-refused",
        subject="Contestation d'annulation de commande",
        body_text="Nous maintenons notre decision. Aucun remboursement ne sera accorde.",
    )

    classification = GmailResponseIntelligenceService().classify_message(message)

    assert classification.review_type == "refused"
    assert classification.reason == "refused_keywords"


def test_fast_watched_classifier_detects_next_payout_positive() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-fast-payout",
        provider_thread_id="thread-fast-payout",
        body_text="Bonjour, la regularisation sera ajoutee a votre prochain versement.",
    )

    review_type, reason, confidence = classify_unlinked_watched_message(message)

    assert review_type == "payment_confirmed"
    assert reason == "fast_unlinked_payment_positive"
    assert confidence >= 0
