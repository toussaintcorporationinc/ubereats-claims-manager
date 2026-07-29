from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
import unicodedata

from app.models import InboundEmailMessage
from app.services.email_provider import InboundEmailPayload

EXPLICIT_PAYMENT_PROMISE_MARKERS = (
    "paiement accorde",
    "paiement a ete accorde",
    "remboursement accorde",
    "remboursement a ete accorde",
    "remboursement accepte",
    "remboursement approuve",
    "nous allons vous rembourser",
    "nous avons decide de vous rembourser",
    "vous serez rembourse",
    "sera verse",
    "sera credite",
    "sera ajoute a votre prochain versement",
    "sera ajoutee a votre prochain versement",
    "apparaitra dans votre prochain versement",
    "apparaitra sur votre prochain versement",
    "ajoute a votre prochain versement",
    "ajoutee a votre prochain versement",
    "nous avons applique un ajustement",
    "ajustement a ete applique",
    "nous avons ajuste votre paiement",
    "votre paiement a ete ajuste",
    "nous avons procede au paiement",
    "nous avons procede au remboursement",
    "je vais proceder a l'ajout du paiement",
    "nous allons proceder a l'ajout du paiement",
    "nous procederons a l'ajout du paiement",
    "afin que vous soyez paye lors de votre prochain cycle de paiement",
    "afin que vous soyez remunere lors de votre prochain cycle de paiement",
    "a ete credite",
    "vous avez deja ete rembourse",
    "il semble que vous ayez deja ete rembourse",
    "vous avez deja ete paye",
    "il semble que vous ayez deja ete paye",
    "payment approved",
    "refund approved",
    "refund accepted",
    "we have credited",
    "we will credit",
    "we adjusted your payment",
    "we have adjusted your payment",
    "payment has been issued",
    "payment was processed",
    "payment processed",
    "we have paid",
    "paid out",
    "payout completed",
    "will appear in your next payout",
    "you will receive this amount",
    "we will reimburse",
    "we will compensate",
    "vous recevrez ce montant",
    "vous recevrez un paiement",
    "nous allons vous verser",
    "vous avez percu l'integralite du paiement",
    "vous avez donc percu l'integralite du paiement",
    "vous avez recu l'integralite du paiement",
    "you received the full payment",
    "you have received the full payment",
    "you were paid in full",
)
PAYMENT_CONTEXT_MARKERS = (
    "paiement",
    "rembours",
    "versement",
    "credite",
    "crediter",
    "ajustement",
    "payment",
    "refund",
    "credited",
)
PAYMENT_APPROVAL_MARKERS = (
    "accorde",
    "approuve",
    "paiement accorde",
    "remboursement accorde",
    "remboursement accepte",
    "remboursement approuve",
    "sera rembourse",
    "a ete rembourse",
    "avons rembourse",
    "remboursement effectue",
    "remboursement traite",
    "sera verse",
    "a ete verse",
    "avons verse",
    "sera credite",
    "a ete credite",
    "avons credite",
    "ajustement applique",
    "approved",
    "issued",
    "paid out",
    "credited",
)
PAYMENT_REJECTION_MARKERS = (
    "refus",
    "refuse",
    "pas de remboursement",
    "aucun remboursement",
    "ne pouvons pas rembourser",
    "nous avons decide de ne pas rembourser",
    "ne sera pas rembourse",
    "n'avons pas procede au remboursement",
    "n'a pas procede au remboursement",
    "non eligible",
    "denied",
    "declined",
    "no refund",
    "cannot refund",
    "rembourser le montant de l'article signale",
    "rembourser le montant des articles signales",
    "rembourser le montant du plat signale",
    "rembourser le montant des plats signales",
)
PAYMENT_AMOUNT_PATTERN = re.compile(
    r"(?<![\w.,])(?:€\s*\d+(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?\s*(?:€|eur|euros?))(?![\w.,])",
    re.I,
)
PAYMENT_SIGNAL_TEXT_LIMIT = 12000
IGNORED_HTML_TAGS = {"head", "script", "style", "svg", "title"}
PAYMENT_TEXT_TRANSLATIONS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\u2032": "'",
        "\u200b": " ",
        "\u200c": " ",
        "\u200d": " ",
        "\u2060": " ",
        "\ufeff": " ",
    }
)


class VisibleEmailTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.ignored_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if self.ignored_tag is None and normalized_tag in IGNORED_HTML_TAGS:
            self.ignored_tag = normalized_tag

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag == self.ignored_tag:
            self.ignored_tag = None

    def handle_data(self, data: str) -> None:
        if self.ignored_tag is None and data.strip():
            self.chunks.append(data)


def visible_email_text(text: str) -> str:
    if "<" not in text or ">" not in text:
        return unescape(text)
    parser = VisibleEmailTextParser()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError):
        return unescape(text)
    return unescape(" ".join(parser.chunks))


def normalize_payment_signal_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized_punctuation = without_accents.translate(PAYMENT_TEXT_TRANSLATIONS)
    return " ".join(normalized_punctuation.replace("\xa0", " ").split())


def current_response_text_parts(
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
) -> str:
    text = "\n".join(
        visible_email_text(part)
        for part in (subject or "", snippet or "", body_text or "")
        if part
    )
    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    for marker in (
        "Continue this conversation by replying to this email.",
        "Poursuivez la conversation en répondant à cet e-mail.",
        "Poursuivez la conversation en repondant a cet e-mail.",
        "-----Original Message-----",
        "-----Message d'origine-----",
    ):
        marker_index = normalized_newlines.casefold().find(marker.casefold())
        if marker_index >= 0:
            normalized_newlines = normalized_newlines[:marker_index]
    return normalized_newlines[:PAYMENT_SIGNAL_TEXT_LIMIT]


def current_response_text(message: InboundEmailMessage) -> str:
    return current_response_text_parts(message.subject, message.snippet, message.body_text)


def current_payload_response_text(payload: InboundEmailPayload) -> str:
    return current_response_text_parts(payload.subject, payload.snippet, payload.body_text)


def text_has_explicit_payment_confirmation(text: str) -> bool:
    normalized = normalize_payment_signal_text(text)
    positive_positions = [
        normalized.find(marker)
        for marker in EXPLICIT_PAYMENT_PROMISE_MARKERS
        if marker in normalized
    ]
    for amount_match in PAYMENT_AMOUNT_PATTERN.finditer(text):
        context = normalize_payment_signal_text(
            text[max(0, amount_match.start() - 160) : min(len(text), amount_match.end() + 160)]
        )
        if any(marker in context for marker in PAYMENT_REJECTION_MARKERS):
            continue
        if any(marker in context for marker in PAYMENT_CONTEXT_MARKERS) and any(
            marker in context for marker in PAYMENT_APPROVAL_MARKERS
        ):
            positive_positions.append(amount_match.start())
    if not positive_positions:
        return False
    rejection_positions = [
        normalized.find(marker)
        for marker in PAYMENT_REJECTION_MARKERS
        if marker in normalized
    ]
    return not rejection_positions or min(positive_positions) < min(rejection_positions)


def message_has_explicit_payment_confirmation(message: InboundEmailMessage) -> bool:
    return text_has_explicit_payment_confirmation(current_response_text(message))


def payload_has_explicit_payment_confirmation(payload: InboundEmailPayload) -> bool:
    return text_has_explicit_payment_confirmation(current_payload_response_text(payload))


def response_text_order_number(text: str) -> str | None:
    normalized_text = normalize_payment_signal_text(text)
    patterns = (
        r"\bcommande\s+n(?:o|°|º)\s*[\s.:#-]*([a-z0-9][a-z0-9-]{3,11})\b",
        r"\bcommande\s+(?:numero|number|id)\s*[\s.:#-]*([a-z0-9][a-z0-9-]{3,11})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def current_response_order_number(message: InboundEmailMessage) -> str | None:
    return response_text_order_number(current_response_text(message))


def current_payload_response_order_number(payload: InboundEmailPayload) -> str | None:
    return response_text_order_number(current_payload_response_text(payload))
