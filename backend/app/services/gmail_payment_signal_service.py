from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
import unicodedata

from app.models import InboundEmailMessage

EXPLICIT_PAYMENT_PROMISE_MARKERS = (
    "paiement accorde",
    "paiement a ete accorde",
    "remboursement accorde",
    "remboursement a ete accorde",
    "nous allons vous rembourser",
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
    "nous avons procede au paiement",
    "a ete credite",
    "payment approved",
    "refund approved",
    "we have credited",
    "we will credit",
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
    "accepte",
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
    "accepted",
    "issued",
    "processed",
    "paid out",
    "credited",
)
PAYMENT_REJECTION_MARKERS = (
    "refus",
    "refuse",
    "pas de remboursement",
    "aucun remboursement",
    "ne pouvons pas rembourser",
    "ne sera pas rembourse",
    "non eligible",
    "denied",
    "declined",
    "no refund",
    "cannot refund",
)
PAYMENT_AMOUNT_PATTERN = re.compile(
    r"(?<![\w])(?:€\s*\d+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?\s*(?:€|eur|euros?))(?![\w])",
    re.I,
)
PAYMENT_SIGNAL_TEXT_LIMIT = 12000
IGNORED_HTML_TAGS = {"head", "script", "style", "svg", "title"}


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
    return " ".join(without_accents.replace("\xa0", " ").split())


def current_response_text(message: InboundEmailMessage) -> str:
    text = "\n".join(
        visible_email_text(part)
        for part in (message.subject or "", message.snippet or "", message.body_text or "")
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


def text_has_explicit_payment_confirmation(text: str) -> bool:
    normalized = normalize_payment_signal_text(text)
    positive_positions = [
        normalized.find(marker)
        for marker in EXPLICIT_PAYMENT_PROMISE_MARKERS
        if marker in normalized
    ]
    has_amount = PAYMENT_AMOUNT_PATTERN.search(text) is not None
    if (
        has_amount
        and any(marker in normalized for marker in PAYMENT_CONTEXT_MARKERS)
        and any(marker in normalized for marker in PAYMENT_APPROVAL_MARKERS)
    ):
        positive_positions.extend(
            normalized.find(marker)
            for marker in PAYMENT_APPROVAL_MARKERS
            if marker in normalized
        )
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
