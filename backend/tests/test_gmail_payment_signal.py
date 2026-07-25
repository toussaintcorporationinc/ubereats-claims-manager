from app.models import InboundEmailMessage
from app.services.gmail_payment_signal_service import (
    current_response_order_number,
    message_has_explicit_payment_confirmation,
    text_has_explicit_payment_confirmation,
)


def test_uber_survey_html_tracking_token_is_not_a_payment_confirmation() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="survey-message",
        from_email="support@uber.com",
        subject="Contestation remboursement de commande",
        snippet="Partagez votre experience avec le service d'assistance Uber.",
        body_text="""
            <!doctype html>
            <html>
              <head><meta charset="utf-8"><style>.remboursement { width: 1px; }</style></head>
              <body>
                <p>Nous accordons beaucoup d'importance a votre avis.</p>
                <img src="https://tracking.example/O6eurexpxU5p6bOoiw" width="1" height="1">
              </body>
            </html>
        """,
    )

    assert message_has_explicit_payment_confirmation(message) is False


def test_amount_like_fragment_inside_identifier_is_not_a_payment_amount() -> None:
    assert text_has_explicit_payment_confirmation("Remboursement O6eurexpxU5p6bOoiw") is False


def test_visible_html_payment_approval_with_amount_is_confirmed() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="payment-message",
        from_email="support@uber.com",
        subject="Mise a jour de votre contestation",
        body_text="<p>Un remboursement de <strong>24,90 EUR</strong> a ete accorde.</p>",
    )

    assert message_has_explicit_payment_confirmation(message) is True


def test_explicit_payment_promise_without_amount_is_confirmed() -> None:
    assert text_has_explicit_payment_confirmation("Nous allons vous rembourser.") is True


def test_uber_decided_to_refund_with_next_payment_amount_is_confirmed() -> None:
    text = (
        "Nous avons decide de vous rembourser. "
        "Un montant de 59.96 EUR sera visible sur votre prochain paiement hebdomadaire."
    )

    assert text_has_explicit_payment_confirmation(text) is True


def test_uber_full_payment_retained_is_confirmed() -> None:
    text = (
        "Apr\u00e8s v\u00e9rification de la commande \ufeff62A5B, il n\u2019y a pas eu d\u2019ajustement. "
        "Le remboursement client n\u2019a engendr\u00e9 aucun frais pour vous. "
        "Vous avez donc per\u00e7u l\u2019int\u00e9gralit\u00e9 du paiement de la commande."
    )

    assert text_has_explicit_payment_confirmation(text) is True


def test_rejection_with_amount_is_not_confirmed() -> None:
    assert text_has_explicit_payment_confirmation("Aucun remboursement de 24,90 EUR ne sera accorde.") is False


def test_adjusted_payment_with_amount_is_confirmed() -> None:
    text = (
        "Apres examen, le client a annule la commande apres l'avoir acceptee. "
        "Nous avons ajuste votre paiement de 37,383 EUR. "
        "Ce montant sera visible sur votre prochain releve de paiement."
    )

    assert text_has_explicit_payment_confirmation(text) is True


def test_client_acceptance_near_payment_under_review_is_not_confirmed() -> None:
    text = "Le client a accepte la commande. Le paiement de 24,90 EUR reste en cours d'examen."

    assert text_has_explicit_payment_confirmation(text) is False


def test_current_response_order_number_handles_uber_punctuation() -> None:
    message = InboundEmailMessage(
        email_account_id=1,
        provider_message_id="payment-order-number",
        body_text="Nous avons ajuste le paiement de la commande N° . 0A04C.",
    )

    assert current_response_order_number(message) == "0A04C"
