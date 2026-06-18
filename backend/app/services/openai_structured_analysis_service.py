from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import get_settings

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class AIProofExtraction:
    detected_evidence_type: str | None
    case_type: str | None
    restaurant_name: str | None
    customer_name: str | None
    order_number: str | None
    display_id: str | None
    order_date: date | None
    order_amount: Decimal | None
    currency: str | None
    confidence: Decimal
    missing_fields: list[str]
    notes: str


@dataclass(frozen=True)
class AIGmailClassification:
    review_type: str
    confidence: Decimal
    reason: str
    detected_amount: Decimal | None
    evidence_requested: bool | None
    notes: str


class OpenAIStructuredAnalysisService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def proof_enabled(self) -> bool:
        return bool(self.settings.ai_proof_identity_enabled and self.settings.openai_api_key)

    def gmail_enabled(self) -> bool:
        return bool(self.settings.ai_gmail_analysis_enabled and self.settings.openai_api_key)

    def analyze_proof(
        self,
        *,
        extracted_text: str,
        filename: str,
        restaurant_names: list[str],
        mime_type: str | None = None,
        image_bytes: bytes | None = None,
    ) -> AIProofExtraction | None:
        if not self.proof_enabled():
            return None
        schema = proof_schema()
        prompt = (
            "Tu analyses une preuve terrain TENNET pour Uber Eats. "
            "La preuve principale est une photo/PDF d'un ticket de caisse agrafe sur la commande. "
            "Extrais uniquement les informations visibles dans le texte ou l'image fournie. "
            "N'invente jamais un client, un montant, une date, un restaurant ou un numero de commande. "
            "Si un champ est absent ou illisible, retourne null et ajoute le champ dans missing_fields. "
            "Restaurants connus: "
            f"{', '.join(restaurant_names) or 'aucun'}.\n"
            f"Nom fichier: {filename}\n"
            f"Texte OCR/local:\n{extracted_text[:12000]}"
        )
        result = self._request_json(
            model=self.settings.openai_evidence_model or "gpt-4o-mini",
            schema_name="tennet_proof_extraction",
            schema=schema,
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
        )
        if not result:
            return None
        return AIProofExtraction(
            detected_evidence_type=string_or_none(result.get("detected_evidence_type")),
            case_type=string_or_none(result.get("case_type")),
            restaurant_name=string_or_none(result.get("restaurant_name")),
            customer_name=string_or_none(result.get("customer_name")),
            order_number=string_or_none(result.get("order_number")),
            display_id=string_or_none(result.get("display_id")),
            order_date=parse_date(result.get("order_date")),
            order_amount=parse_decimal(result.get("order_amount")),
            currency=(string_or_none(result.get("currency")) or "EUR")[:3].upper(),
            confidence=parse_decimal(result.get("confidence")) or Decimal("0"),
            missing_fields=[str(item) for item in result.get("missing_fields", []) if str(item).strip()],
            notes=(string_or_none(result.get("notes")) or "")[:1000],
        )

    def analyze_gmail_message(
        self,
        *,
        subject: str | None,
        snippet: str | None,
        body_text: str | None,
        labels: list[str],
        order_context: dict[str, Any] | None = None,
    ) -> AIGmailClassification | None:
        if not self.gmail_enabled():
            return None
        schema = gmail_schema()
        context = order_context or {}
        prompt = (
            "Tu analyses une reponse email Uber Eats pour TENNET. "
            "Objectif: classer la reponse sans inventer de paiement ni de refus. "
            "Si Gmail contient STARRED, cela signifie que l'utilisateur marque le mail comme refus urgent a relancer, "
            "sauf si le message contient clairement un paiement positif. "
            "Ne declare payment_confirmed que si un montant explicite est visible. "
            "Si le message contient des signaux positifs et negatifs contradictoires, retourne manual_review.\n"
            f"Contexte dossier: {json.dumps(context, ensure_ascii=True, default=str)}\n"
            f"Labels Gmail: {labels}\n"
            f"Sujet: {subject or ''}\n"
            f"Extrait: {snippet or ''}\n"
            f"Corps:\n{(body_text or '')[:12000]}"
        )
        result = self._request_json(
            model=self.settings.openai_gmail_model or self.settings.openai_evidence_model or "gpt-4o-mini",
            schema_name="tennet_gmail_response_classification",
            schema=schema,
            prompt=prompt,
        )
        if not result:
            return None
        return AIGmailClassification(
            review_type=string_or_none(result.get("review_type")) or "manual_review",
            confidence=parse_decimal(result.get("confidence")) or Decimal("0"),
            reason=(string_or_none(result.get("reason")) or "ai_no_reason")[:100],
            detected_amount=parse_decimal(result.get("detected_amount")),
            evidence_requested=bool(result.get("evidence_requested")) if result.get("evidence_requested") is not None else None,
            notes=(string_or_none(result.get("notes")) or "")[:1200],
        )

    def analyze_order_identity_text(
        self,
        *,
        text: str,
        restaurant_names: list[str],
        order_context: dict[str, Any] | None = None,
    ) -> AIProofExtraction | None:
        if not (self.gmail_enabled() or self.proof_enabled()):
            return None
        schema = proof_schema()
        context = order_context or {}
        prompt = (
            "Tu aides TENNET a reparer l'identite d'un dossier Uber Eats avant relance Gmail. "
            "Le texte peut contenir des emails envoyes par le restaurant, des reponses Uber, des extraits de ticket "
            "ou des notes historiques. Extrais uniquement les informations explicitement presentes: nom client, "
            "numero de commande, date de commande, restaurant et montant. "
            "N'invente jamais une donnee absente. Si une information est incertaine ou absente, retourne null et "
            "ajoute le champ dans missing_fields. "
            "Si un numero court visible comme F93BA ou BAEF7 existe, mets-le dans display_id. "
            "Restaurants connus: "
            f"{', '.join(restaurant_names) or 'aucun'}.\n"
            f"Contexte dossier: {json.dumps(context, ensure_ascii=True, default=str)}\n"
            f"Texte Gmail / historique / preuve:\n{text[:12000]}"
        )
        result = self._request_json(
            model=self.settings.openai_gmail_model or self.settings.openai_evidence_model or "gpt-4o-mini",
            schema_name="tennet_order_identity_extraction",
            schema=schema,
            prompt=prompt,
        )
        if not result:
            return None
        return AIProofExtraction(
            detected_evidence_type=string_or_none(result.get("detected_evidence_type")),
            case_type=string_or_none(result.get("case_type")),
            restaurant_name=string_or_none(result.get("restaurant_name")),
            customer_name=string_or_none(result.get("customer_name")),
            order_number=string_or_none(result.get("order_number")),
            display_id=string_or_none(result.get("display_id")),
            order_date=parse_date(result.get("order_date")),
            order_amount=parse_decimal(result.get("order_amount")),
            currency=(string_or_none(result.get("currency")) or "EUR")[:3].upper(),
            confidence=parse_decimal(result.get("confidence")) or Decimal("0"),
            missing_fields=[str(item) for item in result.get("missing_fields", []) if str(item).strip()],
            notes=(string_or_none(result.get("notes")) or "")[:1000],
        )

    def _request_json(
        self,
        *,
        model: str,
        schema_name: str,
        schema: dict[str, Any],
        prompt: str,
        image_bytes: bytes | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        credential = self.settings.openai_api_key
        if not credential:
            return None
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        if image_bytes and mime_type and mime_type.startswith("image/") and len(image_bytes) <= MAX_IMAGE_BYTES:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}"})
        payload = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        try:
            with httpx.Client(timeout=self.settings.openai_request_timeout_seconds) as client:
                response = client.post(
                    OPENAI_RESPONSES_URL,
                    headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json"},
                    json=payload,
                )
            response.raise_for_status()
            return parse_response_json(response.json())
        except Exception:
            return None


def parse_response_json(response: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[str] = []
    if isinstance(response.get("output_text"), str):
        candidates.append(response["output_text"])
    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict):
                text = content.get("text") or content.get("output_text")
                if isinstance(text, str):
                    candidates.append(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def proof_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "detected_evidence_type": nullable_string,
            "case_type": {"type": ["string", "null"], "enum": ["refund", "cancellation", "unknown", None]},
            "restaurant_name": nullable_string,
            "customer_name": nullable_string,
            "order_number": nullable_string,
            "display_id": nullable_string,
            "order_date": nullable_string,
            "order_amount": nullable_string,
            "currency": nullable_string,
            "confidence": {"type": "number"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
        },
        "required": [
            "detected_evidence_type",
            "case_type",
            "restaurant_name",
            "customer_name",
            "order_number",
            "display_id",
            "order_date",
            "order_amount",
            "currency",
            "confidence",
            "missing_fields",
            "notes",
        ],
    }


def gmail_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "review_type": {
                "type": "string",
                "enum": [
                    "accepted",
                    "payment_to_verify",
                    "payment_confirmed",
                    "refused",
                    "evidence_requested",
                    "information_requested",
                    "followup_needed",
                    "manual_review",
                ],
            },
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "detected_amount": nullable_string,
            "evidence_requested": {"type": ["boolean", "null"]},
            "notes": {"type": "string"},
        },
        "required": ["review_type", "confidence", "reason", "detected_amount", "evidence_requested", "notes"],
    }


def string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(" ", "")
    for token in ("EUR", "eur", "\u20ac"):
        text = text.replace(token, "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return abs(Decimal(text)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_date(value: object) -> date | None:
    text = string_or_none(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
