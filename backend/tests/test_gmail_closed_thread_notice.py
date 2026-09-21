"""Regression coverage: Gmail SENT does not prove an Uber ticket received a reply."""

import pytest

from app.services.gmail_payment_signal_service import text_is_uber_closed_thread_notice


@pytest.mark.parametrize(
    "notice",
    [
        (
            "Nous ne pouvons pas répondre aux conversations qui ont été fermées. "
            "Veuillez noter que votre message n'a pas été reçu par notre équipe d'assistance."
        ),
        "Votre message n'a pas été reçu par notre équipe d'assistance.",
        "We cannot reply to conversations that have been closed.",
        "Your message was not received by our support team.",
    ],
)
def test_closed_uber_support_thread_is_not_actionable(notice: str) -> None:
    assert text_is_uber_closed_thread_notice(notice)


@pytest.mark.parametrize(
    "response",
    [
        "Nous avons décidé de vous rembourser. Le paiement sera ajouté au prochain versement.",
        "Votre demande a été refusée. Merci de transmettre une photo du ticket.",
        "Votre message a bien été reçu et votre dossier est en cours de traitement.",
    ],
)
def test_actionable_uber_response_is_not_a_closed_thread(response: str) -> None:
    assert not text_is_uber_closed_thread_notice(response)
