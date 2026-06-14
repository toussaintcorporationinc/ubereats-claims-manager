from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Restaurant,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReportingImportBatch,
    UberReportingImportRow,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.uber_reporting_import_service import (
    create_or_update_snapshot,
    create_transaction_if_missing,
    normalize_keys,
    normalize_report_row,
    parse_date,
    refresh_batch_counts,
    row_dedupe_key,
)


REPAIR_LIMIT_DEFAULT = 1000
REPAIR_LIMIT_MAX = 10000
REPAIR_MIN_CONFIDENCE = Decimal("0.85")
REPAIRABLE_SOURCE_STATUSES = {"invalid", "skipped", "duplicate", "warning", "valid"}


@dataclass(slots=True)
class HistoricalImportRepairCandidate:
    row_id: int
    batch_id: int
    row_number: int
    original_filename: str
    report_type: str
    old_status: str
    old_errors: list[str]
    old_warnings: list[str]
    row_kind: str | None
    uber_store_id: str | None
    uber_store_name: str | None
    uber_order_id: str | None
    display_id: str | None
    target_restaurant_id: int | None
    target_restaurant_name: str | None
    reason: str
    confidence: Decimal
    status: str = "eligible"
    blockers: list[str] = field(default_factory=list)
    created_snapshot_id: int | None = None
    created_transaction_id: int | None = None
    created_new_record: bool = False
    normalized_data: dict[str, Any] | None = None
    new_errors: list[str] = field(default_factory=list)
    new_warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"uber_reporting_import_row:{self.row_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "row_id": self.row_id,
            "batch_id": self.batch_id,
            "row_number": self.row_number,
            "original_filename": self.original_filename,
            "report_type": self.report_type,
            "old_status": self.old_status,
            "old_errors": self.old_errors,
            "old_warnings": self.old_warnings,
            "new_errors": self.new_errors,
            "new_warnings": self.new_warnings,
            "row_kind": self.row_kind,
            "uber_store_id": self.uber_store_id,
            "uber_store_name": self.uber_store_name,
            "uber_order_id": self.uber_order_id,
            "display_id": self.display_id,
            "target_restaurant_id": self.target_restaurant_id,
            "target_restaurant_name": self.target_restaurant_name,
            "reason": self.reason,
            "confidence": self.confidence,
            "status": self.status,
            "blockers": self.blockers,
            "created_snapshot_id": self.created_snapshot_id,
            "created_transaction_id": self.created_transaction_id,
            "created_new_record": self.created_new_record,
        }


class HistoricalUberReportingRepairService:
    def preview(
        self,
        db: Session,
        current_user: User,
        *,
        batch_id: int | None = None,
        restaurant_id: int | None = None,
        include_duplicates: bool = True,
        min_confidence: Decimal = REPAIR_MIN_CONFIDENCE,
        limit: int = REPAIR_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        candidates, scanned = self.scan_candidates(
            db,
            current_user,
            batch_id=batch_id,
            restaurant_id=restaurant_id,
            include_duplicates=include_duplicates,
            min_confidence=min_confidence,
            limit=limit,
        )
        return self.build_response(candidates, scanned, applied=False, current_user=current_user)

    def apply(
        self,
        db: Session,
        current_user: User,
        *,
        batch_id: int | None = None,
        restaurant_id: int | None = None,
        include_duplicates: bool = True,
        min_confidence: Decimal = REPAIR_MIN_CONFIDENCE,
        limit: int = REPAIR_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        candidates, scanned = self.scan_candidates(
            db,
            current_user,
            batch_id=batch_id,
            restaurant_id=restaurant_id,
            include_duplicates=include_duplicates,
            min_confidence=min_confidence,
            limit=limit,
        )
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        touched_batches: set[int] = set()
        for candidate in candidates:
            if candidate.blockers:
                candidate.status = "blocked"
                skipped.append(candidate.to_dict())
                continue
            row = db.get(UberReportingImportRow, candidate.row_id)
            if row is None or row.created_snapshot_id or row.created_transaction_id:
                candidate.status = "skipped"
                candidate.blockers.append("row_already_processed")
                skipped.append(candidate.to_dict())
                continue
            try:
                self.apply_candidate(db, current_user, row, candidate)
                touched_batches.add(row.batch_id)
                applied.append(candidate.to_dict())
            except Exception as exc:
                candidate.status = "failed"
                candidate.blockers.append(str(exc))
                row.status = "skipped"
                row.errors = [*candidate.new_errors, str(exc)]
                skipped.append(candidate.to_dict())

        for touched_batch_id in touched_batches:
            batch = db.get(UberReportingImportBatch, touched_batch_id)
            if batch is None:
                continue
            refresh_batch_counts(db, batch)
            batch.created_snapshots_count = self.count_created_snapshots(db, batch.id)
            batch.created_transactions_count = self.count_created_transactions(db, batch.id)
            if batch.status in {"parsed", "failed", "cancelled"}:
                batch.status = "partially_imported"
            if batch.confirmed_at is None:
                batch.confirmed_at = utc_now()

        add_audit_log(
            db,
            entity_type="historical_uber_reporting_import_repair",
            entity_id=current_user.id,
            action="historical_uber_reporting_import_repair.apply",
            user_id=current_user.id,
            new_value={
                "batch_id": batch_id,
                "restaurant_id": restaurant_id,
                "scanned_count": scanned,
                "applied_count": len(applied),
                "skipped_count": len(skipped),
                "min_confidence": str(min_confidence),
            },
        )
        db.commit()
        return self.build_response(
            candidates,
            scanned,
            applied=True,
            current_user=current_user,
            repaired=applied,
            skipped=skipped,
        )

    def scan_candidates(
        self,
        db: Session,
        current_user: User,
        *,
        batch_id: int | None,
        restaurant_id: int | None,
        include_duplicates: bool,
        min_confidence: Decimal,
        limit: int,
    ) -> tuple[list[HistoricalImportRepairCandidate], int]:
        bounded_limit = min(max(limit, 1), REPAIR_LIMIT_MAX)
        statement = (
            select(UberReportingImportRow, UberReportingImportBatch)
            .join(UberReportingImportBatch, UberReportingImportRow.batch_id == UberReportingImportBatch.id)
            .where(UberReportingImportRow.created_snapshot_id.is_(None))
            .where(UberReportingImportRow.created_transaction_id.is_(None))
            .where(UberReportingImportRow.status.in_(sorted(REPAIRABLE_SOURCE_STATUSES)))
            .order_by(UberReportingImportRow.id)
        )
        if batch_id is not None:
            statement = statement.where(UberReportingImportRow.batch_id == batch_id)
        if not include_duplicates:
            statement = statement.where(UberReportingImportRow.status != "duplicate")

        candidates: list[HistoricalImportRepairCandidate] = []
        scanned = 0
        for row, batch in db.execute(statement).all():
            scanned += 1
            candidate = self.build_candidate(db, current_user, row, batch, restaurant_id, min_confidence)
            if candidate is not None:
                candidates.append(candidate)
            if len(candidates) >= bounded_limit:
                break
        return candidates, scanned

    def build_candidate(
        self,
        db: Session,
        current_user: User,
        row: UberReportingImportRow,
        batch: UberReportingImportBatch,
        restaurant_id_filter: int | None,
        min_confidence: Decimal,
    ) -> HistoricalImportRepairCandidate | None:
        raw_data = normalize_keys(row.raw_data or {})
        normalized_data, errors, warnings = normalize_report_row(db, current_user, raw_data, batch.report_type)
        target_restaurant_id = normalized_data.get("restaurant_id")
        target_restaurant_name = self.restaurant_name(db, target_restaurant_id)
        reason, confidence = self.resolve_reason_and_confidence(normalized_data, warnings)
        candidate = HistoricalImportRepairCandidate(
            row_id=row.id,
            batch_id=batch.id,
            row_number=row.row_number,
            original_filename=batch.original_filename,
            report_type=batch.report_type,
            old_status=row.status,
            old_errors=list(row.errors or []),
            old_warnings=list(row.warnings or []),
            new_errors=errors,
            new_warnings=warnings,
            row_kind=normalized_data.get("row_kind"),
            uber_store_id=clean_text(normalized_data.get("uber_store_id")),
            uber_store_name=clean_text(normalized_data.get("uber_store_name")),
            uber_order_id=clean_text(normalized_data.get("uber_order_id")),
            display_id=clean_text(normalized_data.get("display_id")),
            target_restaurant_id=target_restaurant_id if isinstance(target_restaurant_id, int) else None,
            target_restaurant_name=target_restaurant_name,
            reason=reason,
            confidence=confidence,
            normalized_data=normalized_data,
        )
        self.attach_blockers(db, row, candidate, errors, restaurant_id_filter, min_confidence)
        if not self.is_candidate_relevant(row, candidate):
            return None
        return candidate

    def attach_blockers(
        self,
        db: Session,
        row: UberReportingImportRow,
        candidate: HistoricalImportRepairCandidate,
        errors: list[str],
        restaurant_id_filter: int | None,
        min_confidence: Decimal,
    ) -> None:
        if row.created_snapshot_id or row.created_transaction_id:
            candidate.blockers.append("row_already_processed")
        if errors:
            candidate.blockers.extend(errors)
        if candidate.row_kind not in {"order", "transaction"}:
            candidate.blockers.append("unsupported_row_kind")
        if candidate.target_restaurant_id is None:
            candidate.blockers.append("missing_target_restaurant")
        if restaurant_id_filter is not None and candidate.target_restaurant_id != restaurant_id_filter:
            candidate.blockers.append("target_restaurant_filter_mismatch")
        if candidate.confidence < min_confidence:
            candidate.blockers.append("confidence_below_threshold")
        if not candidate.uber_order_id:
            candidate.blockers.append("missing_uber_order_id")
        if candidate.row_kind == "order" and self.snapshot_exists(db, candidate):
            candidate.status = "existing"
            candidate.blockers.append("snapshot_already_exists")
        if candidate.row_kind == "transaction" and self.transaction_exists(db, candidate):
            candidate.status = "existing"
            candidate.blockers.append("transaction_already_exists")
        dedupe_key = row_dedupe_key(candidate.normalized_data or {}, candidate.report_type)
        if dedupe_key is None:
            candidate.blockers.append("missing_dedupe_key")

    def is_candidate_relevant(self, row: UberReportingImportRow, candidate: HistoricalImportRepairCandidate) -> bool:
        already_exists_blockers = {"snapshot_already_exists", "transaction_already_exists"}
        if candidate.blockers and set(candidate.blockers).issubset(already_exists_blockers):
            return False
        if not candidate.blockers:
            return True
        old_blockers = set(row.errors or []) | set(row.warnings or [])
        repair_signals = {
            "missing_uber_store_id",
            "unmapped_store",
            "unmapped_store_name",
            "restaurant_access_denied",
            "duplicate_in_file",
        }
        if old_blockers & repair_signals:
            return True
        if candidate.target_restaurant_id is not None and candidate.uber_order_id and not (set(candidate.blockers) & already_exists_blockers):
            return True
        return False

    def apply_candidate(
        self,
        db: Session,
        current_user: User,
        row: UberReportingImportRow,
        candidate: HistoricalImportRepairCandidate,
    ) -> None:
        if candidate.normalized_data is None:
            raise ValueError("missing_normalized_data")
        row.normalized_data = candidate.normalized_data
        row.errors = []
        row.warnings = [*candidate.new_warnings, "historical_import_repair"]
        if candidate.row_kind == "order":
            snapshot, created = create_or_update_snapshot(db, candidate.normalized_data)
            row.created_snapshot_id = snapshot.id
            candidate.created_snapshot_id = snapshot.id
            candidate.created_new_record = created
        elif candidate.row_kind == "transaction":
            transaction, created = create_transaction_if_missing(db, candidate.normalized_data)
            row.created_transaction_id = transaction.id if transaction else None
            candidate.created_transaction_id = transaction.id if transaction else None
            candidate.created_new_record = created
        else:
            raise ValueError("unsupported_row_kind")
        row.status = "created"
        candidate.status = "applied"
        add_audit_log(
            db,
            entity_type="uber_reporting_import_row",
            entity_id=row.id,
            action="historical_uber_reporting_import_repair.row_applied",
            user_id=current_user.id,
            old_value={
                "status": candidate.old_status,
                "errors": candidate.old_errors,
                "warnings": candidate.old_warnings,
            },
            new_value={
                "status": row.status,
                "restaurant_id": candidate.target_restaurant_id,
                "row_kind": candidate.row_kind,
                "created_snapshot_id": candidate.created_snapshot_id,
                "created_transaction_id": candidate.created_transaction_id,
                "created_new_record": candidate.created_new_record,
                "reason": candidate.reason,
                "confidence": str(candidate.confidence),
            },
        )

    def resolve_reason_and_confidence(self, data: dict[str, Any], warnings: list[str]) -> tuple[str, Decimal]:
        store_id = clean_text(data.get("uber_store_id"))
        if store_id and not store_id.startswith("restaurant-name:") and "restaurant_matched_by_store_name" not in warnings:
            return "store_id_mapping", Decimal("1.00")
        if "missing_store_id_resolved_by_store_name" in warnings:
            return "store_name_mapping", Decimal("0.95")
        if "restaurant_matched_by_store_name" in warnings or "missing_store_id_resolved_by_restaurant_name" in warnings:
            return "restaurant_name_exact_match", Decimal("0.90")
        return "re_normalized", Decimal("0.85")

    def snapshot_exists(self, db: Session, candidate: HistoricalImportRepairCandidate) -> bool:
        if candidate.target_restaurant_id is None or not candidate.uber_order_id:
            return False
        return (
            db.scalar(
                select(UberOrderSnapshot.id).where(
                    UberOrderSnapshot.restaurant_id == candidate.target_restaurant_id,
                    UberOrderSnapshot.uber_order_id == candidate.uber_order_id,
                )
            )
            is not None
        )

    def transaction_exists(self, db: Session, candidate: HistoricalImportRepairCandidate) -> bool:
        data = candidate.normalized_data or {}
        if candidate.target_restaurant_id is None or not candidate.uber_order_id:
            return False
        try:
            amount = Decimal(str(data["amount"]))
        except Exception:
            return False
        return (
            db.scalar(
                select(UberFinancialTransaction.id).where(
                    UberFinancialTransaction.restaurant_id == candidate.target_restaurant_id,
                    UberFinancialTransaction.uber_order_id == candidate.uber_order_id,
                    UberFinancialTransaction.transaction_type == data.get("transaction_type"),
                    UberFinancialTransaction.transaction_date == parse_date(data.get("transaction_date")),
                    UberFinancialTransaction.amount == amount,
                    UberFinancialTransaction.payout_reference == data.get("payout_reference"),
                )
            )
            is not None
        )

    def restaurant_name(self, db: Session, restaurant_id: object) -> str | None:
        if not isinstance(restaurant_id, int):
            return None
        restaurant = db.get(Restaurant, restaurant_id)
        return restaurant.name if restaurant else None

    def count_created_snapshots(self, db: Session, batch_id: int) -> int:
        return sum(
            1
            for value in db.scalars(
                select(UberReportingImportRow.created_snapshot_id).where(
                    UberReportingImportRow.batch_id == batch_id,
                    UberReportingImportRow.created_snapshot_id.is_not(None),
                )
            ).all()
            if value is not None
        )

    def count_created_transactions(self, db: Session, batch_id: int) -> int:
        return sum(
            1
            for value in db.scalars(
                select(UberReportingImportRow.created_transaction_id).where(
                    UberReportingImportRow.batch_id == batch_id,
                    UberReportingImportRow.created_transaction_id.is_not(None),
                )
            ).all()
            if value is not None
        )

    def build_response(
        self,
        candidates: list[HistoricalImportRepairCandidate],
        scanned: int,
        *,
        applied: bool,
        current_user: User,
        repaired: list[dict[str, Any]] | None = None,
        skipped: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        eligible = [candidate for candidate in candidates if not candidate.blockers]
        blocked = [candidate for candidate in candidates if candidate.blockers]
        created_snapshots = sum(1 for candidate in candidates if candidate.created_snapshot_id)
        created_transactions = sum(1 for candidate in candidates if candidate.created_transaction_id)
        return {
            "status": "applied" if applied else "preview",
            "scanned_count": scanned,
            "total_candidates": len(candidates),
            "eligible_count": len(eligible),
            "blocked_count": len(blocked),
            "repaired_count": len(repaired or []),
            "skipped_count": len(skipped or []),
            "created_snapshots_count": created_snapshots,
            "created_transactions_count": created_transactions,
            "candidates": [candidate.to_dict() for candidate in candidates],
            "repaired": repaired or [],
            "skipped": skipped or [],
            "run_by_user_id": current_user.id,
        }

def clean_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
