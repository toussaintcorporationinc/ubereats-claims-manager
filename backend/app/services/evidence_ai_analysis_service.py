from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EvidenceAnalysisResult, EvidenceImportBatch, EvidenceImportedFile, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.bulk_evidence_import_service import BulkEvidenceImportError, resolve_imported_file_path

ORDER_PATTERN = re.compile(r"\b(UBER(?:[-_\s]?[A-Z0-9]+){1,5})\b", re.IGNORECASE)
DISPLAY_PATTERN = re.compile(r"\b([A-Z0-9]{4,8})\b")
AMOUNT_PATTERN = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)")
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4})\b")


@dataclass(frozen=True)
class EvidenceAnalysisPayload:
    detected_evidence_type: str
    restaurant_name: str | None
    uber_order_number: str | None
    display_id: str | None
    order_date: date | None
    order_amount: Decimal | None
    currency: str | None
    keywords: list[str]
    classification_confidence: Decimal
    extraction_confidence: Decimal
    needs_manual_review: bool
    notes: str
    extracted_text: str


class EvidenceAIAnalysisService:
    def analyze_batch(
        self,
        db: Session,
        current_user: User,
        batch: EvidenceImportBatch,
        *,
        provider: str,
        limit: int,
    ) -> dict[str, object]:
        if provider == "openai_vision" and not get_settings().ai_evidence_analysis_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenAI evidence analysis is disabled")
        if provider == "local_ocr" and not get_settings().ocr_local_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local OCR is disabled")

        batch.status = "analyzing"
        errors: list[str] = []
        files = db.scalars(
            select(EvidenceImportedFile)
            .where(
                EvidenceImportedFile.batch_id == batch.id,
                EvidenceImportedFile.status.in_(("analysis_pending", "stored", "failed")),
            )
            .order_by(EvidenceImportedFile.id)
            .limit(limit)
        ).all()

        from app.services.evidence_matching_service import EvidenceMatchingService

        matching_service = EvidenceMatchingService()
        for imported_file in files:
            try:
                payload = self.analyze_file(imported_file, provider)
                result = EvidenceAnalysisResult(
                    imported_file_id=imported_file.id,
                    provider=provider,
                    model_name=get_settings().openai_evidence_model if provider == "openai_vision" else None,
                    status="manual_review" if payload.needs_manual_review else "success",
                    extracted_text=payload.extracted_text,
                    detected_evidence_type=payload.detected_evidence_type,
                    detected_restaurant_name=payload.restaurant_name,
                    detected_uber_order_number=payload.uber_order_number,
                    detected_display_id=payload.display_id,
                    detected_order_date=payload.order_date,
                    detected_order_amount=payload.order_amount,
                    detected_currency=payload.currency,
                    detected_keywords_json=payload.keywords,
                    classification_confidence=payload.classification_confidence,
                    extraction_confidence=payload.extraction_confidence,
                    matching_confidence=Decimal("0"),
                    raw_result_json={
                        "detected_evidence_type": payload.detected_evidence_type,
                        "restaurant_name": payload.restaurant_name,
                        "uber_order_number": payload.uber_order_number,
                        "display_id": payload.display_id,
                        "order_date": payload.order_date.isoformat() if payload.order_date else None,
                        "order_amount": str(payload.order_amount) if payload.order_amount is not None else None,
                        "currency": payload.currency,
                        "keywords": payload.keywords,
                        "classification_confidence": str(payload.classification_confidence),
                        "extraction_confidence": str(payload.extraction_confidence),
                        "needs_manual_review": payload.needs_manual_review,
                        "notes": payload.notes,
                    },
                )
                db.add(result)
                db.flush()
                candidates = matching_service.create_candidates(db, current_user, imported_file, result)
                result.matching_confidence = max((candidate.match_score for candidate in candidates), default=Decimal("0"))
                imported_file.status = "analyzed"
                imported_file.updated_at = utc_now()
            except Exception as exc:
                imported_file.status = "failed"
                imported_file.updated_at = utc_now()
                errors.append(f"file {imported_file.id}: {exc}")

        refresh_batch_analysis_counts(batch)
        add_audit_log(
            db,
            entity_type="evidence_import_batch",
            entity_id=batch.id,
            action="evidence_import_batch.analyzed",
            user_id=current_user.id,
            new_value={
                "provider": provider,
                "analyzed_files_count": batch.analyzed_files_count,
                "auto_matched_count": batch.auto_matched_count,
                "needs_review_count": batch.needs_review_count,
                "failed_files_count": batch.failed_files_count,
                "errors": errors,
            },
        )
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "analyzed_files_count": batch.analyzed_files_count,
            "auto_matched_count": batch.auto_matched_count,
            "needs_review_count": batch.needs_review_count,
            "failed_files_count": batch.failed_files_count,
            "errors": errors,
        }

    def analyze_file(self, imported_file: EvidenceImportedFile, provider: str) -> EvidenceAnalysisPayload:
        if provider == "openai_vision":
            settings = get_settings()
            if not settings.ai_evidence_analysis_enabled or not settings.openai_api_key:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenAI evidence analysis is disabled")
        text = build_local_text(imported_file)
        evidence_type, keywords, classification_confidence = classify_evidence_type(text, imported_file.original_filename)
        order_number = extract_order_number(text)
        amount = extract_amount(text)
        detected_date = extract_date(text)
        extraction_confidence = Decimal("0.80") if order_number else Decimal("0.45")
        needs_manual_review = evidence_type == "unknown" or not order_number
        return EvidenceAnalysisPayload(
            detected_evidence_type=evidence_type,
            restaurant_name=None,
            uber_order_number=order_number,
            display_id=extract_display_id(text, order_number),
            order_date=detected_date,
            order_amount=amount,
            currency="EUR" if amount is not None else None,
            keywords=keywords,
            classification_confidence=classification_confidence,
            extraction_confidence=extraction_confidence,
            needs_manual_review=needs_manual_review,
            notes="Analyse deterministe V1.1, sans appel OpenAI reel.",
            extracted_text=text,
        )


def build_local_text(imported_file: EvidenceImportedFile) -> str:
    filename_text = imported_file.original_filename.replace("_", " ").replace("-", " ")
    try:
        path = resolve_imported_file_path(imported_file)
        content = path.read_bytes()[:8192]
        decoded = content.decode("utf-8", errors="ignore")
    except (BulkEvidenceImportError, UnicodeDecodeError):
        decoded = ""
    return f"{filename_text}\n{decoded}".strip()


def classify_evidence_type(text: str, filename: str) -> tuple[str, list[str], Decimal]:
    lower = f"{filename} {text}".lower()
    rules = [
        ("cancellation_proof", ("annulation", "cancel", "canceled", "cancelled")),
        ("preparation_proof", ("preparation", "preparee", "préparée", "prepared", "ready")),
        ("waste_photo", ("waste", "gaspillage", "jetee", "jetée")),
        ("receipt", ("receipt", "ticket", "caisse", "recu", "reçu")),
        ("uber_screenshot", ("uber", "manager", "capture", "screenshot")),
        ("delivery_proof", ("delivery", "livraison", "delivered")),
        ("packaging_photo", ("packaging", "emballage", "pack")),
        ("sealed_bag_photo", ("sealed", "scelle", "scellé", "bag", "sac")),
        ("order_details_screenshot", ("order details", "details commande", "détails commande")),
        ("courier_statement", ("courier", "livreur", "coursier")),
        ("gps_or_route_proof", ("gps", "route", "trajet")),
        ("customer_contact_proof", ("customer contact", "client message", "whatsapp")),
    ]
    for evidence_type, keywords in rules:
        matched = [keyword for keyword in keywords if keyword in lower]
        if matched:
            return evidence_type, matched, Decimal("0.85")
    return "unknown", [], Decimal("0.25")


def extract_order_number(text: str) -> str | None:
    match = ORDER_PATTERN.search(text)
    if not match:
        return None
    return re.sub(r"[-_\s]+", "-", match.group(1)).strip("-").upper()


def extract_display_id(text: str, order_number: str | None) -> str | None:
    if order_number:
        return None
    match = DISPLAY_PATTERN.search(text)
    return match.group(1).upper() if match else None


def extract_amount(text: str) -> Decimal | None:
    match = AMOUNT_PATTERN.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None


def extract_date(text: str) -> date | None:
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1)
    try:
        if "-" in raw and raw[4] == "-":
            return date.fromisoformat(raw)
        day, month, year = re.split(r"[/-]", raw)
        return date(int(year), int(month), int(day))
    except (ValueError, IndexError):
        return None


def refresh_batch_analysis_counts(batch: EvidenceImportBatch) -> None:
    files = list(batch.files)
    analyzed = [item for item in files if item.status == "analyzed"]
    failed = [item for item in files if item.status == "failed"]
    batch.analyzed_files_count = len(analyzed)
    batch.failed_files_count = len(failed)
    batch.auto_matched_count = len(
        [
            candidate
            for imported_file in files
            for candidate in imported_file.match_candidates
            if candidate.status == "auto_attached"
        ]
    )
    batch.needs_review_count = len(
        [
            imported_file
            for imported_file in files
            if imported_file.status == "analyzed"
            and not any(candidate.status in {"accepted", "auto_attached"} for candidate in imported_file.match_candidates)
        ]
    )
    if failed and analyzed:
        batch.status = "partially_analyzed"
    elif failed and not analyzed:
        batch.status = "failed"
    elif analyzed:
        batch.status = "analyzed"
        batch.completed_at = utc_now()
    batch.updated_at = utc_now()
