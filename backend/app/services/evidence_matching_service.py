from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant
from app.core.config import get_settings
from app.models import (
    ClaimOrder,
    EvidenceAnalysisResult,
    EvidenceImportedFile,
    EvidenceMatchCandidate,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    UberReconciliationResult,
    User,
)


class EvidenceMatchingService:
    def create_candidates(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
    ) -> list[EvidenceMatchCandidate]:
        specs = [
            *self.claim_order_candidates(db, current_user, imported_file, analysis),
            *self.evidence_task_candidates(db, current_user, imported_file, analysis),
            *self.customer_refund_candidates(db, current_user, imported_file, analysis),
            *self.reconciliation_candidates(db, current_user, imported_file, analysis),
        ]
        unique: dict[tuple[str, int], tuple[str, int, Decimal]] = {}
        for candidate_type, candidate_id, restaurant_id, reason, score in specs:
            key = (candidate_type, candidate_id)
            if restaurant_id is not None and not can_access_restaurant(db, current_user, restaurant_id):
                continue
            existing = unique.get(key)
            if existing is None or score > existing[2]:
                unique[key] = (reason, restaurant_id or 0, score)

        candidates: list[EvidenceMatchCandidate] = []
        for (candidate_type, candidate_id), (reason, restaurant_id, score) in unique.items():
            candidate = EvidenceMatchCandidate(
                imported_file_id=imported_file.id,
                analysis_result_id=analysis.id,
                candidate_type=candidate_type,
                candidate_id=candidate_id,
                restaurant_id=restaurant_id or None,
                match_reason=reason,
                match_score=score,
                status="proposed",
            )
            db.add(candidate)
            candidates.append(candidate)
        db.flush()
        maybe_auto_attach(db, current_user, imported_file, candidates, analysis.detected_evidence_type)
        return candidates

    def claim_order_candidates(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
    ) -> list[tuple[str, int, int, str, Decimal]]:
        candidates: list[tuple[str, int, int, str, Decimal]] = []
        if analysis.detected_uber_order_number:
            rows = db.scalars(
                select(ClaimOrder).where(ClaimOrder.uber_order_number == analysis.detected_uber_order_number)
            ).all()
            for order in rows:
                candidates.append(("claim_order", order.id, order.restaurant_id, "exact_order_number", Decimal("0.95")))
        if imported_file.batch.restaurant_id is not None and analysis.detected_order_amount is not None:
            rows = db.scalars(
                select(ClaimOrder).where(
                    ClaimOrder.restaurant_id == imported_file.batch.restaurant_id,
                    ClaimOrder.order_amount == analysis.detected_order_amount,
                )
            ).all()
            for order in rows:
                candidates.append(("claim_order", order.id, order.restaurant_id, "restaurant_date_amount_match", Decimal("0.65")))
        return candidates

    def evidence_task_candidates(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
    ) -> list[tuple[str, int, int, str, Decimal]]:
        if analysis.detected_evidence_type == "unknown":
            return []
        statement = select(EvidenceRequestTask).where(
            EvidenceRequestTask.required_evidence_type == analysis.detected_evidence_type,
            EvidenceRequestTask.status.in_(("pending", "uploaded")),
        )
        if imported_file.batch.restaurant_id is not None:
            statement = statement.where(EvidenceRequestTask.restaurant_id == imported_file.batch.restaurant_id)
        rows = db.scalars(statement).all()
        candidates = []
        for task in rows:
            score = Decimal("0.70")
            if analysis.detected_uber_order_number and task.order.uber_order_number == analysis.detected_uber_order_number:
                score = Decimal("0.98")
            candidates.append(("evidence_task", task.id, task.restaurant_id, "evidence_task_type_match", score))
        return candidates

    def customer_refund_candidates(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
    ) -> list[tuple[str, int, int, str, Decimal]]:
        conditions = []
        if analysis.detected_uber_order_number:
            conditions.append(UberCustomerRefundDispute.uber_order_id == analysis.detected_uber_order_number)
        if analysis.detected_display_id:
            conditions.append(UberCustomerRefundDispute.display_id == analysis.detected_display_id)
        if not conditions:
            return []
        statement = select(UberCustomerRefundDispute).where(or_(*conditions))
        if imported_file.batch.restaurant_id is not None:
            statement = statement.where(UberCustomerRefundDispute.restaurant_id == imported_file.batch.restaurant_id)
        return [
            (
                "customer_refund_dispute",
                dispute.id,
                dispute.restaurant_id,
                "exact_order_number" if analysis.detected_uber_order_number else "display_id_match",
                Decimal("0.90"),
            )
            for dispute in db.scalars(statement).all()
        ]

    def reconciliation_candidates(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
    ) -> list[tuple[str, int, int, str, Decimal]]:
        conditions = []
        if analysis.detected_uber_order_number:
            conditions.append(UberReconciliationResult.uber_order_id == analysis.detected_uber_order_number)
        if analysis.detected_display_id:
            conditions.append(UberReconciliationResult.display_id == analysis.detected_display_id)
        if not conditions:
            return []
        statement = select(UberReconciliationResult).where(or_(*conditions))
        if imported_file.batch.restaurant_id is not None:
            statement = statement.where(UberReconciliationResult.restaurant_id == imported_file.batch.restaurant_id)
        return [
            (
                "reconciliation_result",
                result.id,
                result.restaurant_id,
                "exact_order_number" if analysis.detected_uber_order_number else "display_id_match",
                Decimal("0.88"),
            )
            for result in db.scalars(statement).all()
        ]


def maybe_auto_attach(
    db: Session,
    current_user: User,
    imported_file: EvidenceImportedFile,
    candidates: list[EvidenceMatchCandidate],
    detected_evidence_type: str,
) -> None:
    settings = get_settings()
    if not settings.ai_evidence_auto_attach_enabled or detected_evidence_type == "unknown":
        return
    threshold = Decimal(str(settings.ai_evidence_high_confidence_threshold))
    strong = [candidate for candidate in candidates if candidate.match_score >= threshold]
    if len(strong) != 1:
        for candidate in candidates:
            if candidate.match_score >= threshold:
                candidate.status = "manual_review"
        return
    from app.services.evidence_bulk_review_service import attach_imported_file

    attach_imported_file(
        db,
        current_user,
        imported_file,
        candidate_type=strong[0].candidate_type,
        candidate_id=strong[0].candidate_id,
        evidence_type=detected_evidence_type,
        decision_reason="auto_attach_high_confidence",
    )
    strong[0].status = "auto_attached"
