from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import get_accessible_restaurant_ids
from app.models import (
    EvidenceAnalysisResult,
    EvidenceAttachmentDecision,
    EvidenceImportedFile,
    EvidenceImportBatch,
    User,
)
from app.schemas.domain import WorkspaceUnclassifiedItem, WorkspaceUnclassifiedResponse

HIGH_CONFIDENCE_MATCH = Decimal("0.94")


class WorkspaceUnclassifiedService:
    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user

    def list_items(self, *, limit: int = 50) -> WorkspaceUnclassifiedResponse:
        statement = (
            select(EvidenceImportedFile)
            .join(EvidenceImportBatch, EvidenceImportedFile.batch_id == EvidenceImportBatch.id)
            .options(
                selectinload(EvidenceImportedFile.batch).selectinload(EvidenceImportBatch.restaurant),
                selectinload(EvidenceImportedFile.analysis_results),
                selectinload(EvidenceImportedFile.match_candidates),
                selectinload(EvidenceImportedFile.attachment_decisions),
            )
            .where(EvidenceImportedFile.status.notin_(["ignored"]))
            .order_by(EvidenceImportedFile.id.desc())
            .limit(max(limit * 4, limit))
        )
        accessible_ids = get_accessible_restaurant_ids(self.db, self.current_user)
        if accessible_ids is not None:
            if not accessible_ids:
                return WorkspaceUnclassifiedResponse(items=[], total_count=0)
            statement = statement.where(
                (EvidenceImportBatch.restaurant_id.is_(None)) | (EvidenceImportBatch.restaurant_id.in_(accessible_ids))
            )

        items: list[WorkspaceUnclassifiedItem] = []
        for imported_file in self.db.scalars(statement).unique().all():
            item = build_unclassified_item(imported_file)
            if item is not None:
                items.append(item)
            if len(items) >= limit:
                break
        return WorkspaceUnclassifiedResponse(items=items, total_count=len(items))


def build_unclassified_item(imported_file: EvidenceImportedFile) -> WorkspaceUnclassifiedItem | None:
    if has_attached_decision(imported_file):
        return None

    analysis = latest_analysis(imported_file)
    missing_fields: list[str] = []
    reason = "classification_incomplete"
    title = "Source non classee"
    description_parts = []

    if imported_file.status == "failed":
        reason = "analysis_failed"
        missing_fields.append("lecture fichier")
        description_parts.append("TENNET n'a pas pu lire ce fichier. Reimporte une version lisible ou une photo plus nette.")
    elif analysis is None:
        reason = "analysis_pending"
        missing_fields.append("analyse TENNET")
        description_parts.append("TENNET doit encore analyser ce fichier au prochain passage de la machine.")
    else:
        if analysis.detected_evidence_type == "unknown":
            missing_fields.append("type de preuve")
        if not (analysis.detected_uber_order_number or analysis.detected_display_id):
            missing_fields.append("numero de commande")
        if not analysis.detected_restaurant_name and imported_file.batch.restaurant is None:
            missing_fields.append("restaurant")
        if analysis.detected_order_amount is None:
            missing_fields.append("montant")

        if missing_fields:
            reason = "missing_identity"
            description_parts.append("Il manque: " + ", ".join(missing_fields) + ".")

        strong_candidates = [
            candidate
            for candidate in imported_file.match_candidates
            if candidate.status in {"proposed", "manual_review"} and candidate.match_score >= HIGH_CONFIDENCE_MATCH
        ]
        if len(strong_candidates) > 1:
            reason = "ambiguous_matches"
            missing_fields.append("choix entre plusieurs dossiers")
            description_parts.append("Plusieurs dossiers ressemblent a ce fichier. Choisis le bon rattachement.")
        elif not strong_candidates and not missing_fields:
            reason = "no_reliable_match"
            missing_fields.append("lien commande/preuve")
            description_parts.append("Le fichier est lisible, mais aucun dossier fiable ne correspond encore.")

    if not missing_fields and reason == "classification_incomplete":
        return None

    restaurant_name = imported_file.batch.restaurant.name if imported_file.batch.restaurant else None
    if analysis and analysis.detected_restaurant_name:
        restaurant_name = analysis.detected_restaurant_name
    if analysis and (analysis.detected_uber_order_number or analysis.detected_display_id):
        title = f"Commande {analysis.detected_uber_order_number or analysis.detected_display_id} a classer"
    elif restaurant_name:
        title = f"{restaurant_name} - source a classer"

    if not description_parts:
        description_parts.append("TENNET garde ce fichier en attente d'une information fiable.")
    description_parts.append("Ajoute une preuve avec restaurant, client, numero de commande ou montant visible, puis TENNET reprendra automatiquement.")

    return WorkspaceUnclassifiedItem(
        source_type="evidence_file",
        source_id=imported_file.id,
        original_filename=imported_file.original_filename,
        title=title,
        description=" ".join(description_parts),
        restaurant=restaurant_name,
        reason=reason,
        missing_fields=dedupe(missing_fields),
        action_url=f"/evidence-imports/files/{imported_file.id}",
        created_at=imported_file.created_at,
    )


def latest_analysis(imported_file: EvidenceImportedFile) -> EvidenceAnalysisResult | None:
    if not imported_file.analysis_results:
        return None
    return sorted(imported_file.analysis_results, key=lambda item: item.id)[-1]


def has_attached_decision(imported_file: EvidenceImportedFile) -> bool:
    return any(
        isinstance(decision, EvidenceAttachmentDecision) and decision.decision == "attached"
        for decision in imported_file.attachment_decisions
    )


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
