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


DETERMINISTIC_AUTO_ATTACH_THRESHOLD = Decimal("0.94")


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

        existing_candidates = {
            (candidate.candidate_type, candidate.candidate_id): candidate
            for candidate in db.scalars(
                select(EvidenceMatchCandidate).where(EvidenceMatchCandidate.imported_file_id == imported_file.id)
            ).all()
        }
        candidates: list[EvidenceMatchCandidate] = []
        for (candidate_type, candidate_id), (reason, restaurant_id, score) in unique.items():
            candidate = existing_candidates.get((candidate_type, candidate_id))
            if candidate is None:
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
            elif candidate.status not in {"accepted", "auto_attached"}:
                candidate.analysis_result_id = analysis.id
                candidate.restaurant_id = restaurant_id or None
                candidate.match_reason = reason
                candidate.match_score = max(candidate.match_score, score)
            candidates.append(candidate)
        db.flush()
        maybe_auto_attach(db, current_user, imported_file, candidates, analysis)
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
        if analysis.detected_display_id:
            rows = db.scalars(
                select(ClaimOrder).where(ClaimOrder.uber_order_number == analysis.detected_display_id)
            ).all()
            for order in rows:
                candidates.append(("claim_order", order.id, order.restaurant_id, "display_id_match", Decimal("0.92")))
        if imported_file.batch.restaurant_id is not None and analysis.detected_order_amount is not None:
            rows = db.scalars(
                select(ClaimOrder).where(
                    ClaimOrder.restaurant_id == imported_file.batch.restaurant_id,
                    ClaimOrder.order_amount == analysis.detected_order_amount,
                )
            ).all()
            for order in rows:
                candidates.append(("claim_order", order.id, order.restaurant_id, "restaurant_date_amount_match", Decimal("0.65")))
        candidates.extend(self.customer_identity_order_candidates(db, imported_file, analysis))
        return candidates

    def customer_identity_order_candidates(
        self,
        db: Session,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
    ) -> list[tuple[str, int, int, str, Decimal]]:
        customer_name = detected_customer_name(analysis)
        if not customer_name:
            return []
        statement = select(ClaimOrder).where(ClaimOrder.customer_name == customer_name)
        restaurant_id = imported_file.batch.restaurant_id or restaurant_id_for_detected_name(db, analysis.detected_restaurant_name)
        if restaurant_id is not None:
            statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
        if analysis.detected_order_date is not None:
            statement = statement.where(ClaimOrder.order_date == analysis.detected_order_date)
        if analysis.detected_order_amount is not None:
            statement = statement.where(ClaimOrder.order_amount == analysis.detected_order_amount)
        rows = db.scalars(statement.order_by(ClaimOrder.id.desc()).limit(20)).all()
        if len(rows) != 1:
            return []
        score = Decimal("0.90")
        if analysis.detected_order_amount is not None and analysis.detected_order_date is not None:
            score = Decimal("0.93")
        return [("claim_order", rows[0].id, rows[0].restaurant_id, "amount_date_restaurant_match", score)]

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
        restaurant_id = imported_file.batch.restaurant_id or restaurant_id_for_detected_name(db, analysis.detected_restaurant_name)
        if restaurant_id is not None:
            statement = statement.where(EvidenceRequestTask.restaurant_id == restaurant_id)
        rows = db.scalars(statement).all()
        candidates = []
        for task in rows:
            score = Decimal("0.70")
            if analysis.detected_uber_order_number and task.order.uber_order_number == analysis.detected_uber_order_number:
                score = Decimal("0.98")
            elif analysis.detected_display_id and task.order.uber_order_number == analysis.detected_display_id:
                score = Decimal("0.96")
            elif task_matches_customer_identity(task, analysis):
                score = Decimal("0.94")
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
        restaurant_id = imported_file.batch.restaurant_id or restaurant_id_for_detected_name(db, analysis.detected_restaurant_name)
        if restaurant_id is not None:
            statement = statement.where(UberCustomerRefundDispute.restaurant_id == restaurant_id)
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
        restaurant_id = imported_file.batch.restaurant_id or restaurant_id_for_detected_name(db, analysis.detected_restaurant_name)
        if restaurant_id is not None:
            statement = statement.where(UberReconciliationResult.restaurant_id == restaurant_id)
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
    analysis: EvidenceAnalysisResult,
) -> None:
    detected_evidence_type = analysis.detected_evidence_type
    if detected_evidence_type == "unknown":
        return
    settings = get_settings()
    configured_threshold = Decimal(str(settings.ai_evidence_high_confidence_threshold))
    threshold = min(configured_threshold, DETERMINISTIC_AUTO_ATTACH_THRESHOLD)
    strong = [
        candidate
        for candidate in candidates
        if candidate.candidate_type == "evidence_task" and candidate.match_score >= threshold
    ]
    if len(strong) != 1:
        for candidate in candidates:
            if candidate.match_score >= threshold:
                candidate.status = "manual_review"
        return
    if not candidate_is_unambiguous(candidates, strong[0]):
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
        decision_reason="deterministic_auto_attach_exact_evidence_task",
    )
    strong[0].status = "auto_attached"


def candidate_is_unambiguous(candidates: list[EvidenceMatchCandidate], selected: EvidenceMatchCandidate) -> bool:
    competing_strong = [
        candidate
        for candidate in candidates
        if candidate.id != selected.id and candidate.match_score >= selected.match_score - Decimal("0.02")
    ]
    return not competing_strong


def detected_customer_name(analysis: EvidenceAnalysisResult) -> str | None:
    raw = analysis.raw_result_json or {}
    value = raw.get("customer_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def restaurant_id_for_detected_name(db: Session, restaurant_name: str | None) -> int | None:
    if not restaurant_name:
        return None
    from app.models import Restaurant

    restaurant = db.scalar(select(Restaurant).where(Restaurant.name == restaurant_name))
    return restaurant.id if restaurant else None


def task_matches_customer_identity(task: EvidenceRequestTask, analysis: EvidenceAnalysisResult) -> bool:
    customer_name = detected_customer_name(analysis)
    if not customer_name or not task.order or task.order.customer_name != customer_name:
        return False
    checks = []
    if analysis.detected_order_amount is not None:
        checks.append(task.order.order_amount == analysis.detected_order_amount)
    if analysis.detected_order_date is not None:
        checks.append(task.order.order_date == analysis.detected_order_date)
    return bool(checks) and all(checks)
