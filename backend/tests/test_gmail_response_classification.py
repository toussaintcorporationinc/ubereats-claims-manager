from app.models import InboundEmailMessage
from app.services.gmail_response_intelligence_service import GmailResponseIntelligenceService, detect_amount
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


def test_uber_next_cycle_payment_addition_is_payment_to_verify() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-next-cycle-addition",
        provider_thread_id="thread-next-cycle-addition",
        subject="Contestation d'annulation de commande",
        body_text=(
            "Cette commande ne vous a pas ete reglee, mais compte tenu de la situation, "
            "je vais proceder a l'ajout du paiement pour cette commande, afin que vous "
            "soyez paye lors de votre prochain cycle de paiement."
        ),
        provider_labels_json=["STARRED"],
    )

    classification = GmailResponseIntelligenceService().classify_message(message)
    fast_review_type, fast_reason, _confidence = classify_unlinked_watched_message(message)

    assert classification.review_type == "payment_to_verify"
    assert classification.reason == "payment_to_verify_keywords"
    assert fast_review_type == "payment_confirmed"
    assert fast_reason == "fast_unlinked_payment_positive"


def test_uber_already_reimbursed_message_is_payment_to_verify() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-already-reimbursed",
        provider_thread_id="thread-already-reimbursed",
        subject="Contestation de remboursement de commande",
        body_text="Apres verification, il semble que vous ayez deja ete rembourse pour cette commande.",
    )

    classification = GmailResponseIntelligenceService().classify_message(message)

    assert classification.review_type == "payment_to_verify"
    assert classification.reason == "payment_confirmed_without_amount"


def test_full_order_payment_retained_is_payment_to_verify() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-full-payment-retained",
        provider_thread_id="thread-full-payment-retained",
        subject="Contestation de remboursement de commande",
        body_text=(
            "Apres verification, il n'y a pas eu d'ajustement. "
            "Le remboursement client n'a engendre aucun frais pour vous. "
            "Vous avez donc percu l'integralite du paiement de la commande."
        ),
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


def test_french_sent_support_status_is_followup_needed() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-envoye",
        provider_thread_id="thread-envoye",
        subject="Restaurant Support Help Center ENVOYE",
        body_text="Votre demande a bien ete envoyee a l'assistance.",
    )

    classification = GmailResponseIntelligenceService().classify_message(message)
    fast_review_type, fast_reason, _confidence = classify_unlinked_watched_message(message)

    assert classification.review_type == "followup_needed"
    assert classification.reason == "waiting_or_under_review_keywords"
    assert fast_review_type == "followup_needed"
    assert fast_reason == "fast_unlinked_followup_needed"


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


def test_adjusted_payment_is_confirmed_and_amount_is_rounded() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="msg-adjusted-payment",
        provider_thread_id="thread-adjusted-payment",
        subject="Contestation d'annulation de commande",
        body_text=(
            "Apres examen, le client a annule la commande apres l'avoir acceptee. "
            "Nous avons ajuste votre paiement de 37,383 EUR. "
            "Ce montant sera visible sur votre prochain releve de paiement."
        ),
        provider_labels_json=["STARRED"],
    )

    classification = GmailResponseIntelligenceService().classify_message(message)
    fast_review_type, fast_reason, _confidence = classify_unlinked_watched_message(message)

    assert classification.review_type == "payment_confirmed"
    assert classification.reason == "payment_confirmed_with_amount"
    assert str(classification.detected_amount) == "37.38"
    assert fast_review_type == "payment_confirmed"
    assert fast_reason == "fast_unlinked_payment_positive"


def test_three_decimal_payment_amount_does_not_match_only_the_trailing_digits() -> None:
    assert str(detect_amount("Nous avons ajuste votre paiement de 25.483 EUR.")) == "25.48"
