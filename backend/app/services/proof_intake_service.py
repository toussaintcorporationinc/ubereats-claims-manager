from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import can_access_restaurant, ensure_can_access_restaurant, get_accessible_restaurant_ids
from app.models import (
    ClaimOrder,
    EvidenceAnalysisResult,
    EvidenceFile,
    EvidenceImportBatch,
    EvidenceImportedFile,
    Restaurant,
    SmartImportPreviewBatch,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReconciliationResult,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.claim_validation_service import validate_claim_order
from app.services.customer_refund_detection_service import CLASSIFICATION_RULES, contains_any, normalize_text
from app.services.customer_refund_dispute_service import ensure_evidence_requirements
from app.services.customer_refund_evidence_policy_service import evidence_policy_for_dispute
from app.services.evidence_ai_analysis_service import has_attached_decision, latest_analysis_result
from app.services.evidence_bulk_review_service import attach_imported_file
from app.services.order_identity_resolution_service import (
    candidate_numbers_from_payload,
    clean_candidates,
    find_import_row_identity,
    identity_from_analysis,
)
from app.services.uber_reporting_import_service import resolve_mapping_by_store_name, resolve_restaurant_by_store_name


@dataclass
class ProofIntakeResult:
    processed_count: int = 0
    created_count: int = 0
    attached_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = field(default_factory=list)
    created_order_ids: list[int] = field(default_factory=list)
    created_dispute_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ProofIdentity:
    restaurant_id: int | None
    order_number: str | None
    customer_name: str | None
    order_amount: Decimal | None
    currency: str
    order_date: object | None
    evidence_type: str
    text: str
    case_type: str | None


class ProofIntakeService:
    def process(
        self,
        db: Session,
        current_user: User,
        *,
        trigger: str,
        restaurant_id: int | None,
        smart_import_batch_id: int | None,
        limit: int = 500,
    ) -> ProofIntakeResult:
        result = ProofIntakeResult()
        for imported_file in self.iter_files(db, current_user, restaurant_id, smart_import_batch_id, limit):
            result.processed_count += 1
            if has_attached_decision(imported_file):
                result.skipped_count += 1
                continue
            analysis = latest_analysis_result(imported_file)
            if analysis is None:
                result.skipped_count += 1
                result.warnings.append(f"file {imported_file.id}: analysis_pending")
                continue

            identity = self.build_identity(db, imported_file, analysis, trigger)
            missing = self.missing_fields(identity)
            if missing:
                result.skipped_count += 1
                result.warnings.append(f"file {imported_file.id}: missing_{'_'.join(missing)}")
                continue
            if identity.restaurant_id is None or identity.order_number is None or identity.order_amount is None:
                result.skipped_count += 1
                continue
            if not can_access_restaurant(db, current_user, identity.restaurant_id):
                result.skipped_count += 1
                result.warnings.append(f"file {imported_file.id}: restaurant_access_denied")
                continue

            case_type = identity.case_type
            if case_type is None:
                result.skipped_count += 1
                result.warnings.append(f"file {imported_file.id}: case_type_unclear")
                continue

            if self.is_duplicate_evidence_for_order(db, imported_file, identity.restaurant_id, identity.order_number):
                self.mark_duplicate_imported_file(db, current_user, imported_file, identity)
                result.skipped_count += 1
                continue

            try:
                if case_type == "refund":
                    created, attached, order_id, dispute_id = self.process_refund_proof(db, current_user, imported_file, identity)
                    result.created_count += 1 if created else 0
                    result.attached_count += 1 if attached else 0
                    if created:
                        result.created_order_ids.append(order_id)
                    if dispute_id is not None:
                        result.created_dispute_ids.append(dispute_id)
                elif case_type == "cancellation":
                    created, attached, order_id = self.process_cancellation_proof(db, current_user, imported_file, identity)
                    result.created_count += 1 if created else 0
                    result.attached_count += 1 if attached else 0
                    if created:
                        result.created_order_ids.append(order_id)
                else:
                    result.skipped_count += 1
                    result.warnings.append(f"file {imported_file.id}: unsupported_case_type")
            except HTTPException as exc:
                result.skipped_count += 1
                result.warnings.append(f"file {imported_file.id}: {exc.detail}")

        add_audit_log(
            db,
            entity_type="proof_intake",
            entity_id=current_user.id,
            action="proof_intake.processed",
            user_id=current_user.id,
            new_value={
                "trigger": trigger,
                "restaurant_id": restaurant_id,
                "smart_import_batch_id": smart_import_batch_id,
                "processed_count": result.processed_count,
                "created_count": result.created_count,
                "attached_count": result.attached_count,
                "skipped_count": result.skipped_count,
                "warnings": result.warnings[:50],
            },
        )
        return result

    def iter_files(
        self,
        db: Session,
        current_user: User,
        restaurant_id: int | None,
        smart_import_batch_id: int | None,
        limit: int,
    ) -> list[EvidenceImportedFile]:
        statement = (
            select(EvidenceImportedFile)
            .join(EvidenceImportBatch, EvidenceImportedFile.batch_id == EvidenceImportBatch.id)
            .options(
                selectinload(EvidenceImportedFile.batch).selectinload(EvidenceImportBatch.restaurant),
                selectinload(EvidenceImportedFile.analysis_results),
                selectinload(EvidenceImportedFile.attachment_decisions),
            )
            .where(EvidenceImportedFile.status == "analyzed")
            .order_by(EvidenceImportedFile.id.desc())
            .limit(limit)
        )
        evidence_batch_ids = self.evidence_batch_ids_for_preview(db, current_user, smart_import_batch_id)
        if evidence_batch_ids is not None:
            if not evidence_batch_ids:
                return []
            statement = statement.where(EvidenceImportedFile.batch_id.in_(evidence_batch_ids))
        if restaurant_id is not None:
            statement = statement.where(
                (EvidenceImportBatch.restaurant_id == restaurant_id) | (EvidenceImportBatch.restaurant_id.is_(None))
            )
        accessible_ids = get_accessible_restaurant_ids(db, current_user)
        if accessible_ids is not None:
            if not accessible_ids:
                return []
            statement = statement.where(
                (EvidenceImportBatch.restaurant_id.is_(None)) | (EvidenceImportBatch.restaurant_id.in_(accessible_ids))
            )
        return list(db.scalars(statement).unique().all())

    def evidence_batch_ids_for_preview(
        self,
        db: Session,
        current_user: User,
        smart_import_batch_id: int | None,
    ) -> list[int] | None:
        if smart_import_batch_id is None:
            return None
        batch = db.get(SmartImportPreviewBatch, smart_import_batch_id)
        if batch is None:
            return []
        if batch.uploaded_by_user_id != current_user.id and current_user.role != "owner":
            return []
        return sorted(
            {
                file.destination_id
                for file in batch.files
                if file.destination_type == "evidence_import_batch" and file.destination_id is not None
            }
        )

    def build_identity(
        self,
        db: Session,
        imported_file: EvidenceImportedFile,
        analysis: EvidenceAnalysisResult,
        trigger: str,
    ) -> ProofIdentity:
        raw = analysis.raw_result_json or {}
        text = " ".join(
            str(value)
            for value in (
                imported_file.original_filename,
                imported_file.batch.restaurant.name if imported_file.batch.restaurant else "",
                analysis.extracted_text or "",
            )
            if value
        )
        analysis_identity = identity_from_analysis(analysis)
        candidate_numbers = clean_candidates(
            value
            for value in {
                analysis.detected_uber_order_number,
                analysis.detected_display_id,
                analysis_identity.order_number,
                analysis_identity.display_id,
                *candidate_numbers_from_payload(raw),
                *candidate_numbers_from_payload(text),
            }
            if likely_order_candidate(value)
        )
        order_number = first_order_number(candidate_numbers, analysis.detected_uber_order_number or analysis.detected_display_id)
        order_context = self.resolve_order_context(db, order_number) if order_number else {}
        restaurant_id = (
            imported_file.batch.restaurant_id
            or self.resolve_restaurant_id(db, analysis.detected_restaurant_name, text)
            or order_context.get("restaurant_id")
        )
        if restaurant_id is not None and candidate_numbers:
            row_identity = find_import_row_identity(db, int(restaurant_id), candidate_numbers)
            if row_identity is not None:
                order_context = {
                    **order_context,
                    "customer_name": order_context.get("customer_name") or row_identity.customer_name,
                    "order_amount": order_context.get("order_amount") or row_identity.order_amount,
                    "currency": order_context.get("currency") or row_identity.currency,
                    "order_date": order_context.get("order_date") or row_identity.order_date,
                }
                order_number = order_number or row_identity.best_order_label
        customer_name = (str(raw.get("customer_name")).strip() if raw.get("customer_name") else None) or order_context.get(
            "customer_name"
        )
        evidence_type = analysis.detected_evidence_type if analysis.detected_evidence_type != "unknown" else "receipt"
        case_type = self.case_type_for_trigger(trigger, text, evidence_type)
        return ProofIdentity(
            restaurant_id=restaurant_id,
            order_number=order_number,
            customer_name=customer_name,
            order_amount=analysis.detected_order_amount or order_context.get("order_amount"),
            currency=analysis.detected_currency or order_context.get("currency") or "EUR",
            order_date=analysis.detected_order_date or order_context.get("order_date"),
            evidence_type=evidence_type,
            text=text,
            case_type=case_type,
        )

    def resolve_order_context(self, db: Session, order_number: str) -> dict[str, object]:
        contexts: list[dict[str, object]] = []

        order = db.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == order_number).order_by(ClaimOrder.id.desc()))
        if order is not None:
            contexts.append(
                {
                    "restaurant_id": order.restaurant_id,
                    "customer_name": order.customer_name,
                    "order_amount": order.order_amount,
                    "currency": order.currency,
                    "order_date": order.order_date,
                }
            )

        snapshot = db.scalar(
            select(UberOrderSnapshot)
            .where((UberOrderSnapshot.uber_order_id == order_number) | (UberOrderSnapshot.display_id == order_number))
            .order_by(UberOrderSnapshot.id.desc())
        )
        if snapshot is not None:
            contexts.append(
                {
                    "restaurant_id": snapshot.restaurant_id,
                    "customer_name": snapshot.customer_name,
                    "order_amount": snapshot.order_total_amount,
                    "currency": snapshot.currency,
                    "order_date": snapshot.placed_at.date() if snapshot.placed_at else None,
                }
            )

        dispute = db.scalar(
            select(UberCustomerRefundDispute)
            .where(
                (UberCustomerRefundDispute.uber_order_id == order_number)
                | (UberCustomerRefundDispute.display_id == order_number)
            )
            .order_by(UberCustomerRefundDispute.id.desc())
        )
        if dispute is not None:
            contexts.append(
                {
                    "restaurant_id": dispute.restaurant_id,
                    "customer_name": None,
                    "order_amount": dispute.order_amount or dispute.customer_refund_amount,
                    "currency": dispute.currency,
                    "order_date": dispute.order_date,
                }
            )

        reconciliation_result = db.scalar(
            select(UberReconciliationResult)
            .where(
                (UberReconciliationResult.uber_order_id == order_number)
                | (UberReconciliationResult.display_id == order_number)
            )
            .order_by(UberReconciliationResult.id.desc())
        )
        if reconciliation_result is not None:
            contexts.append(
                {
                    "restaurant_id": reconciliation_result.restaurant_id,
                    "customer_name": None,
                    "order_amount": reconciliation_result.order_amount or reconciliation_result.missing_amount,
                    "currency": reconciliation_result.currency,
                    "order_date": None,
                }
            )

        transaction = db.scalar(
            select(UberFinancialTransaction)
            .where(UberFinancialTransaction.uber_order_id == order_number)
            .order_by(UberFinancialTransaction.id.desc())
        )
        if transaction is not None:
            contexts.append(
                {
                    "restaurant_id": transaction.restaurant_id,
                    "customer_name": self.first_text_value(
                        transaction.raw_payload_json,
                        ("customer_name", "client", "eater_name", "nom_client"),
                    ),
                    "order_amount": abs(transaction.amount),
                    "currency": transaction.currency,
                    "order_date": transaction.transaction_date,
                }
            )

        restaurant_ids = {context.get("restaurant_id") for context in contexts if context.get("restaurant_id") is not None}
        if len(restaurant_ids) != 1:
            return {}

        merged: dict[str, object] = {"restaurant_id": restaurant_ids.pop()}
        for key in ("customer_name", "order_amount", "currency", "order_date"):
            for context in contexts:
                value = context.get(key)
                if value:
                    merged[key] = value
                    break
        return merged

    def first_text_value(self, payload: object, keys: tuple[str, ...]) -> str | None:
        if not isinstance(payload, dict):
            return None
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def resolve_restaurant_id(self, db: Session, detected_restaurant_name: str | None, text: str) -> int | None:
        candidates = [detected_restaurant_name]
        for restaurant in db.scalars(select(Restaurant).where(Restaurant.active.is_(True)).order_by(Restaurant.id)).all():
            if restaurant.name and restaurant.name.lower() in text.lower():
                candidates.append(restaurant.name)
        for value in candidates:
            if not value:
                continue
            mapping = resolve_mapping_by_store_name(db, value)
            if mapping is not None:
                return mapping.restaurant_id
            restaurant = resolve_restaurant_by_store_name(db, value)
            if restaurant is not None:
                return restaurant.id
        return None

    def case_type_for_trigger(self, trigger: str, text: str, evidence_type: str) -> str | None:
        if trigger == "refunds":
            return "refund"
        if trigger == "cancellations":
            return "cancellation"
        normalized = normalize_text(text)
        if any(marker in normalized for marker in ("annulation", "annule", "cancel", "cancelled", "canceled")):
            return "cancellation"
        if any(
            marker in normalized
            for marker in (
                "remboursement",
                "refund",
                "deduction",
                "non recu",
                "article manquant",
                "missing item",
                "order accuracy",
                "inaccurate",
            )
        ):
            return "refund"
        if evidence_type == "cancellation_proof":
            return "cancellation"
        return None

    def missing_fields(self, identity: ProofIdentity) -> list[str]:
        missing: list[str] = []
        if identity.restaurant_id is None:
            missing.append("restaurant")
        if not identity.order_number:
            missing.append("numero_commande")
        if identity.order_amount is None:
            missing.append("montant")
        return missing

    def process_refund_proof(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        identity: ProofIdentity,
    ) -> tuple[bool, bool, int, int | None]:
        assert identity.restaurant_id is not None
        assert identity.order_number is not None
        assert identity.order_amount is not None
        ensure_can_access_restaurant(db, current_user, identity.restaurant_id)

        dispute_type, reason = self.classify_refund_text(identity.text)
        dispute = self.find_or_create_refund_dispute(db, current_user, identity, dispute_type, reason)
        order, created = self.find_or_create_claim_order(db, current_user, identity, "customer_refund_dispute", dispute.id)
        dispute.claim_order_id = order.id
        if identity.customer_name and not order.customer_name:
            order.customer_name = identity.customer_name
        if identity.order_date and not order.order_date:
            order.order_date = identity.order_date
        evidence_file = self.attach_unified_proof(db, current_user, imported_file, order, identity.evidence_type)
        attached = evidence_file is not None
        if evidence_file is not None:
            self.complete_refund_requirements_with_unified_proof(db, dispute, evidence_file)
        validate_claim_order(db, order.id, user_id=current_user.id)
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=order.id,
            action="proof_intake.refund_case_ready",
            user_id=current_user.id,
            new_value={"dispute_id": dispute.id, "imported_file_id": imported_file.id, "created": created},
        )
        return created, attached, order.id, dispute.id

    def process_cancellation_proof(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        identity: ProofIdentity,
    ) -> tuple[bool, bool, int]:
        assert identity.restaurant_id is not None
        assert identity.order_number is not None
        assert identity.order_amount is not None
        ensure_can_access_restaurant(db, current_user, identity.restaurant_id)
        order, created = self.find_or_create_claim_order(db, current_user, identity, "cancellation_not_compensated", None)
        evidence_type = "cancellation_proof" if identity.evidence_type == "unknown" else identity.evidence_type
        evidence_file = self.attach_unified_proof(db, current_user, imported_file, order, evidence_type)
        validate_claim_order(db, order.id, user_id=current_user.id)
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=order.id,
            action="proof_intake.cancellation_case_ready",
            user_id=current_user.id,
            new_value={"imported_file_id": imported_file.id, "created": created},
        )
        return created, evidence_file is not None, order.id

    def classify_refund_text(self, text: str) -> tuple[str, str]:
        normalized = normalize_text(text)
        for dispute_type, reason, needles in CLASSIFICATION_RULES:
            if contains_any(normalized, needles):
                return dispute_type, reason
        return "customer_refund", "refund_without_sufficient_proof"

    def find_or_create_refund_dispute(
        self,
        db: Session,
        current_user: User,
        identity: ProofIdentity,
        dispute_type: str,
        reason: str,
    ) -> UberCustomerRefundDispute:
        dispute = db.scalar(
            select(UberCustomerRefundDispute).where(
                UberCustomerRefundDispute.restaurant_id == identity.restaurant_id,
                (UberCustomerRefundDispute.uber_order_id == identity.order_number)
                | (UberCustomerRefundDispute.display_id == identity.order_number),
            )
        )
        if dispute is not None:
            return dispute
        dispute = UberCustomerRefundDispute(
            restaurant_id=identity.restaurant_id,
            uber_order_id=identity.order_number,
            display_id=identity.order_number,
            dispute_type=dispute_type,
            reason=reason,
            status="needs_evidence",
            customer_refund_amount=identity.order_amount,
            order_amount=identity.order_amount,
            currency=identity.currency,
            order_date=identity.order_date,
            evidence_required=True,
            evidence_status="missing",
            raw_payload_json={
                "source": "proof_intake",
                "customer_name": identity.customer_name,
                "extracted_text_sample": identity.text[:1000],
            },
            created_by_user_id=current_user.id,
            notes=(
                "Cree depuis preuve unique lisible. "
                "Le montant extrait de la preuve est utilise comme montant reclamable initial."
            ),
        )
        db.add(dispute)
        db.flush()
        add_audit_log(
            db,
            entity_type="uber_customer_refund_dispute",
            entity_id=dispute.id,
            action="proof_intake.customer_refund_dispute_created",
            user_id=current_user.id,
            new_value={
                "order_number": identity.order_number,
                "amount": str(identity.order_amount),
                "dispute_type": dispute.dispute_type,
            },
        )
        return dispute

    def find_or_create_claim_order(
        self,
        db: Session,
        current_user: User,
        identity: ProofIdentity,
        loss_type: str,
        dispute_id: int | None,
    ) -> tuple[ClaimOrder, bool]:
        order = db.scalar(
            select(ClaimOrder).where(
                ClaimOrder.restaurant_id == identity.restaurant_id,
                ClaimOrder.uber_order_number == identity.order_number,
            )
        )
        if order is not None:
            return order, False
        order = ClaimOrder(
            restaurant_id=identity.restaurant_id,
            internal_reference=f"PROOF-{identity.order_number}",
            uber_order_number=identity.order_number,
            customer_name=identity.customer_name,
            order_date=identity.order_date,
            order_amount=identity.order_amount,
            currency=identity.currency,
            loss_type=loss_type,
            status="missing_evidence",
            notes=self.order_note(identity, loss_type, dispute_id),
        )
        db.add(order)
        db.flush()
        add_audit_log(
            db,
            entity_type="claim_order",
            entity_id=order.id,
            action="proof_intake.claim_order_created",
            user_id=current_user.id,
            new_value={
                "restaurant_id": identity.restaurant_id,
                "uber_order_number": identity.order_number,
                "loss_type": loss_type,
                "amount": str(identity.order_amount),
            },
        )
        return order, True

    def attach_unified_proof(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        order: ClaimOrder,
        evidence_type: str,
    ) -> EvidenceFile | None:
        normalized_evidence_type = evidence_type if evidence_type != "unknown" else "receipt"
        if normalized_evidence_type != "receipt":
            normalized_evidence_type = "receipt" if self.looks_like_single_order_proof(imported_file) else normalized_evidence_type
        result = attach_imported_file(
            db,
            current_user,
            imported_file,
            candidate_type="claim_order",
            candidate_id=order.id,
            evidence_type=normalized_evidence_type,
            decision_reason="proof_intake_unified_order_proof",
        )
        return result.evidence_file

    def complete_refund_requirements_with_unified_proof(
        self,
        db: Session,
        dispute: UberCustomerRefundDispute,
        evidence_file: EvidenceFile,
    ) -> None:
        policy = evidence_policy_for_dispute(dispute.dispute_type)
        requirements = ensure_evidence_requirements(db, dispute, policy.required)
        for requirement in requirements:
            requirement.status = "uploaded"
            requirement.evidence_file_id = evidence_file.id
        dispute.evidence_status = "complete"
        if dispute.status in {"detected", "needs_evidence", "manual_review"}:
            dispute.status = "evidence_ready"
        add_audit_log(
            db,
            entity_type="uber_customer_refund_dispute",
            entity_id=dispute.id,
            action="proof_intake.unified_proof_completed_requirements",
            user_id=evidence_file.uploaded_by_user_id,
            new_value={
                "evidence_file_id": evidence_file.id,
                "requirements": [requirement.required_evidence_type for requirement in requirements],
            },
        )

    def is_duplicate_evidence_for_order(
        self,
        db: Session,
        imported_file: EvidenceImportedFile,
        restaurant_id: int,
        order_number: str,
    ) -> bool:
        if not imported_file.checksum_sha256:
            return False
        return (
            db.scalar(
                select(EvidenceFile)
                .join(ClaimOrder, EvidenceFile.order_id == ClaimOrder.id)
                .where(
                    ClaimOrder.restaurant_id == restaurant_id,
                    ClaimOrder.uber_order_number == order_number,
                    EvidenceFile.checksum_sha256 == imported_file.checksum_sha256,
                    EvidenceFile.deleted_at.is_(None),
                )
                .limit(1)
            )
            is not None
        )

    def mark_duplicate_imported_file(
        self,
        db: Session,
        current_user: User,
        imported_file: EvidenceImportedFile,
        identity: ProofIdentity,
    ) -> None:
        imported_file.status = "ignored"
        imported_file.updated_at = utc_now()
        add_audit_log(
            db,
            entity_type="evidence_imported_file",
            entity_id=imported_file.id,
            action="proof_intake.duplicate_evidence_ignored",
            user_id=current_user.id,
            new_value={"restaurant_id": identity.restaurant_id, "order_number": identity.order_number},
        )

    def looks_like_single_order_proof(self, imported_file: EvidenceImportedFile) -> bool:
        analysis = latest_analysis_result(imported_file)
        raw = analysis.raw_result_json if analysis is not None else {}
        return bool(raw and raw.get("unified_order_proof"))

    def order_note(self, identity: ProofIdentity, loss_type: str, dispute_id: int | None) -> str:
        pieces = [
            "Cree automatiquement depuis preuve unique importee en masse.",
            f"Type: {loss_type}.",
            f"Commande: {identity.order_number}.",
            f"Montant extrait: {identity.order_amount} {identity.currency}.",
        ]
        if identity.customer_name:
            pieces.append(f"Client: {identity.customer_name}.")
        if identity.order_date:
            pieces.append(f"Date: {identity.order_date}.")
        if dispute_id is not None:
            pieces.append(f"Dispute remboursement liee: {dispute_id}.")
        return " ".join(pieces)


def first_order_number(candidates: set[str], preferred: str | None) -> str | None:
    if preferred and likely_order_candidate(preferred):
        return preferred.strip()
    if not candidates:
        return None
    return sorted(candidates, key=lambda value: (len(value), value), reverse=True)[0]


def likely_order_candidate(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if len(text) < 4 or len(text) > 64:
        return False
    normalized = "".join(char for char in text.upper() if char.isalnum())
    if len(normalized) < 4:
        return False
    blocked = {
        "CLIENT",
        "COMMANDE",
        "CUSTOMER",
        "DATE",
        "ORDER",
        "RESTAURANT",
        "TICKET",
        "TOTAL",
    }
    if normalized in blocked:
        return False
    return any(char.isdigit() for char in normalized)
