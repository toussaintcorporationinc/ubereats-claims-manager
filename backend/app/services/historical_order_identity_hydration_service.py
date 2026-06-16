from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import ClaimOrder, UberReconciliationResult, UberReportingImportRow, User
from app.services.audit import add_audit_log
from app.services.order_identity_resolution_service import (
    ResolvedOrderIdentity,
    clean_candidates,
    clean_customer_name,
    identity_from_import_row,
    identity_from_reconciliation_result,
    identity_score,
    is_uuid_like,
    merge_identity,
    normalize_identifier,
    normalize_payload_key,
    resolve_identity_for_order,
)

IMPORT_ROW_HYDRATION_SCAN_LIMIT = 50000
IMPORT_ROW_HYDRATION_STATUSES = ("created", "valid", "warning", "duplicate", "skipped", "invalid")
IMPORT_ROW_DIRECT_KEYS = (
    "uber_order_id",
    "display_id",
    "order_id",
    "order_number",
    "numero_commande",
    "id_de_la_commande",
)
IMPORT_ROW_RAW_IDENTIFIER_KEYS = {
    "id_de_la_commande",
    "id_du_flux",
    "uuid_du_processus",
    "uuid_de_la_commande",
    "numero_commande",
    "numero_de_commande",
    "order_uuid",
    "order_id",
    "order_number",
}


@dataclass(slots=True)
class IndexedImportRowIdentity:
    row_id: int
    restaurant_id: int | None
    identity: ResolvedOrderIdentity
    score: int


class HistoricalOrderIdentityHydrationService:
    """Backfill missing client/date labels from already imported Uber/proof sources."""

    def apply(
        self,
        db: Session,
        current_user: User,
        *,
        restaurant_id: int | None = None,
        limit: int = 10000,
        import_row_scan_limit: int = IMPORT_ROW_HYDRATION_SCAN_LIMIT,
    ) -> dict[str, object]:
        statement = select(ClaimOrder).where(
            or_(
                ClaimOrder.internal_reference.is_(None),
                ClaimOrder.internal_reference == "",
                ClaimOrder.customer_name.is_(None),
                ClaimOrder.customer_name == "",
                ClaimOrder.order_date.is_(None),
                ClaimOrder.order_time.is_(None),
                ClaimOrder.order_amount.is_(None),
            )
        )
        if restaurant_id is not None:
            statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
        statement = statement.options(selectinload(ClaimOrder.customer_refund_disputes))
        orders = list(db.scalars(statement.order_by(ClaimOrder.id.desc()).limit(limit)).all())
        order_ids = [order.id for order in orders]
        reconciliation_results_by_order = self.load_reconciliation_results(db, order_ids)
        order_candidates = {
            order.id: self.candidates_for_order(order, reconciliation_results_by_order.get(order.id, [])) for order in orders
        }
        import_index = self.build_import_row_identity_index(
            db,
            wanted_candidates=set().union(*order_candidates.values()) if order_candidates else set(),
            restaurant_id=restaurant_id,
            import_row_scan_limit=import_row_scan_limit,
        )

        updated_order_ids: list[int] = []
        updated_disputes_count = 0
        updated_reconciliation_results_count = 0
        skipped_count = 0
        bulk_import_matches_count = 0
        sources: set[str] = set()

        for order in orders:
            identity = resolve_identity_for_order(db, order, allow_import_fallback=False)
            reconciliation_results = reconciliation_results_by_order.get(order.id, [])
            for result in reconciliation_results:
                merge_identity(identity, identity_from_reconciliation_result(result), prefer_display=True)
            import_identity = self.identity_from_bulk_import_index(order, order_candidates.get(order.id, set()), import_index)
            if import_identity is not None:
                merge_identity(identity, import_identity, prefer_display=True)
                bulk_import_matches_count += 1
                if import_identity.source:
                    sources.add(import_identity.source.split(":", 1)[0])
            order_changed = self.apply_identity_to_order(order, identity)
            disputes_changed = self.apply_identity_to_disputes(order, identity)
            results_changed = self.apply_identity_to_reconciliation_results(reconciliation_results, identity)
            if order_changed or disputes_changed or results_changed:
                updated_order_ids.append(order.id)
                updated_disputes_count += disputes_changed
                updated_reconciliation_results_count += results_changed
                if identity.source:
                    sources.add(identity.source.split(":", 1)[0])
            else:
                skipped_count += 1

        if updated_order_ids:
            add_audit_log(
                db,
                entity_type="historical_order_identity",
                entity_id=current_user.id,
                action="historical_order_identity.hydrated",
                user_id=current_user.id,
                new_value={
                    "scanned_count": len(orders),
                    "updated_orders_count": len(updated_order_ids),
                    "updated_disputes_count": updated_disputes_count,
                    "updated_reconciliation_results_count": updated_reconciliation_results_count,
                    "indexed_import_rows_count": self.indexed_import_rows_count(import_index),
                    "bulk_import_matches_count": bulk_import_matches_count,
                    "sample_order_ids": updated_order_ids[:25],
                    "sources": sorted(sources),
                },
            )

        return {
            "scanned_count": len(orders),
            "updated_orders_count": len(updated_order_ids),
            "updated_disputes_count": updated_disputes_count,
            "updated_reconciliation_results_count": updated_reconciliation_results_count,
            "indexed_import_rows_count": self.indexed_import_rows_count(import_index),
            "bulk_import_matches_count": bulk_import_matches_count,
            "skipped_count": skipped_count,
            "sample_order_ids": updated_order_ids[:25],
            "sources": sorted(sources),
        }

    def load_reconciliation_results(
        self,
        db: Session,
        order_ids: list[int],
    ) -> dict[int, list[UberReconciliationResult]]:
        if not order_ids:
            return {}
        rows = db.scalars(
            select(UberReconciliationResult)
            .where(UberReconciliationResult.claim_order_id.in_(order_ids))
            .order_by(UberReconciliationResult.id.desc())
        ).all()
        results_by_order: dict[int, list[UberReconciliationResult]] = {}
        for result in rows:
            if result.claim_order_id is None:
                continue
            results_by_order.setdefault(result.claim_order_id, []).append(result)
        return results_by_order

    def candidates_for_order(
        self,
        order: ClaimOrder,
        reconciliation_results: list[UberReconciliationResult],
    ) -> set[str]:
        values = {order.uber_order_number, order.internal_reference}
        for dispute in order.customer_refund_disputes:
            values.update(
                {
                    dispute.uber_order_id,
                    dispute.display_id,
                    dispute.customer_refund_reference,
                    dispute.financial_transaction.uber_order_id if dispute.financial_transaction else None,
                }
            )
        for result in reconciliation_results:
            values.update({result.uber_order_id, result.display_id})
        return clean_candidates(values)

    def build_import_row_identity_index(
        self,
        db: Session,
        *,
        wanted_candidates: set[str],
        restaurant_id: int | None,
        import_row_scan_limit: int,
    ) -> dict[str, list[IndexedImportRowIdentity]]:
        normalized_wanted = {normalize_identifier(candidate) for candidate in wanted_candidates if candidate}
        if not normalized_wanted:
            return {}
        rows = self.load_candidate_import_rows(
            db,
            wanted_candidates=wanted_candidates,
            restaurant_id=restaurant_id,
            import_row_scan_limit=import_row_scan_limit,
        )
        index: dict[str, list[IndexedImportRowIdentity]] = {}
        for row in rows:
            row_restaurant_id = self.import_row_restaurant_id(row)
            if restaurant_id is not None and row_restaurant_id is not None and row_restaurant_id != restaurant_id:
                continue
            row_candidates = self.direct_candidates_for_import_row(row)
            matching_keys = {
                normalize_identifier(candidate)
                for candidate in row_candidates
                if candidate and normalize_identifier(candidate) in normalized_wanted
            }
            if not matching_keys:
                continue
            identity = identity_from_import_row(row)
            score = identity_score(identity)
            if score <= 0:
                continue
            indexed = IndexedImportRowIdentity(
                row_id=row.id,
                restaurant_id=row_restaurant_id,
                identity=identity,
                score=score,
            )
            for key in matching_keys:
                index.setdefault(key, []).append(indexed)
        return index

    def load_candidate_import_rows(
        self,
        db: Session,
        *,
        wanted_candidates: set[str],
        restaurant_id: int | None,
        import_row_scan_limit: int,
    ) -> list[UberReportingImportRow]:
        bind = db.get_bind()
        candidate_values = self.candidate_value_variants(wanted_candidates)
        if bind is not None and bind.dialect.name != "sqlite" and candidate_values:
            direct_conditions = [
                UberReportingImportRow.normalized_data[key].as_string().in_(candidate_values)
                for key in IMPORT_ROW_DIRECT_KEYS
            ]
            rows = list(
                db.scalars(
                    select(UberReportingImportRow)
                    .where(
                        UberReportingImportRow.status.in_(IMPORT_ROW_HYDRATION_STATUSES),
                        or_(*direct_conditions),
                    )
                    .order_by(UberReportingImportRow.id.desc())
                    .limit(import_row_scan_limit)
                ).all()
            )
            if rows:
                return rows
        statement = (
            select(UberReportingImportRow)
            .where(UberReportingImportRow.status.in_(IMPORT_ROW_HYDRATION_STATUSES))
            .order_by(UberReportingImportRow.id.desc())
            .limit(import_row_scan_limit)
        )
        return list(db.scalars(statement).all())

    def candidate_value_variants(self, candidates: set[str]) -> list[str]:
        values: set[str] = set()
        for candidate in candidates:
            cleaned = str(candidate or "").strip()
            if not cleaned:
                continue
            values.add(cleaned)
            values.add(cleaned.lstrip("#"))
            if not cleaned.startswith("#"):
                values.add(f"#{cleaned}")
        return list(values)

    def import_row_restaurant_id(self, row: UberReportingImportRow) -> int | None:
        value = (row.normalized_data or {}).get("restaurant_id")
        return int(value) if str(value or "").isdigit() else None

    def direct_candidates_for_import_row(self, row: UberReportingImportRow) -> set[str]:
        values: set[str] = set()
        normalized_data = row.normalized_data or {}
        values.update(
            {
                normalized_data.get("uber_order_id"),
                normalized_data.get("display_id"),
                normalized_data.get("order_id"),
                normalized_data.get("order_number"),
                normalized_data.get("numero_commande"),
                normalized_data.get("id_de_la_commande"),
            }
        )
        for payload in (normalized_data, row.raw_data or {}):
            if not isinstance(payload, dict):
                continue
            for key, value in payload.items():
                if normalize_payload_key(str(key)) in IMPORT_ROW_RAW_IDENTIFIER_KEYS:
                    if value is not None:
                        values.add(str(value))
        return clean_candidates(values)

    def identity_from_bulk_import_index(
        self,
        order: ClaimOrder,
        candidates: set[str],
        import_index: dict[str, list[IndexedImportRowIdentity]],
    ) -> ResolvedOrderIdentity | None:
        best: IndexedImportRowIdentity | None = None
        best_score = -1
        seen_row_ids: set[int] = set()
        for candidate in candidates:
            key = normalize_identifier(candidate)
            for indexed in import_index.get(key, []):
                if indexed.row_id in seen_row_ids:
                    continue
                seen_row_ids.add(indexed.row_id)
                if indexed.restaurant_id is not None and indexed.restaurant_id != order.restaurant_id:
                    continue
                score = indexed.score + (1 if indexed.restaurant_id == order.restaurant_id else 0)
                if score > best_score:
                    best = indexed
                    best_score = score
        return best.identity if best else None

    def indexed_import_rows_count(self, import_index: dict[str, list[IndexedImportRowIdentity]]) -> int:
        return len({indexed.row_id for rows in import_index.values() for indexed in rows})

    def apply_identity_to_order(self, order: ClaimOrder, identity: ResolvedOrderIdentity) -> bool:
        changed = False
        display_id = identity.best_order_label if identity.best_order_label and not is_uuid_like(identity.best_order_label) else None
        if display_id and self.should_replace_internal_reference(order.internal_reference):
            order.internal_reference = display_id
            changed = True
        customer_name = clean_customer_name(identity.customer_name)
        if customer_name and not order.customer_name:
            order.customer_name = customer_name
            changed = True
        if identity.order_date and not order.order_date:
            order.order_date = identity.order_date
            changed = True
        if identity.order_time and not order.order_time:
            order.order_time = identity.order_time
            changed = True
        if identity.order_amount is not None and order.order_amount is None:
            order.order_amount = identity.order_amount
            changed = True
        if identity.currency and not order.currency:
            order.currency = identity.currency
            changed = True
        return changed

    def should_replace_internal_reference(self, value: str | None) -> bool:
        if not value:
            return True
        cleaned = value.strip().upper()
        return is_uuid_like(cleaned) or cleaned.startswith(("CUST-REFUND-", "REFUND-", "AUTO-", "CLAIM-"))

    def apply_identity_to_disputes(self, order: ClaimOrder, identity: ResolvedOrderIdentity) -> int:
        changed_count = 0
        display_id = identity.best_order_label if identity.best_order_label and not is_uuid_like(identity.best_order_label) else None
        for dispute in order.customer_refund_disputes:
            changed = False
            if display_id and (not dispute.display_id or is_uuid_like(dispute.display_id)):
                dispute.display_id = display_id
                changed = True
            if identity.order_date and not dispute.order_date:
                dispute.order_date = identity.order_date
                changed = True
            if identity.order_amount is not None and dispute.order_amount is None:
                dispute.order_amount = identity.order_amount
                changed = True
            if changed:
                changed_count += 1
        return changed_count

    def apply_identity_to_reconciliation_results(
        self,
        results: list[UberReconciliationResult],
        identity: ResolvedOrderIdentity,
    ) -> int:
        display_id = identity.best_order_label if identity.best_order_label and not is_uuid_like(identity.best_order_label) else None
        if not display_id and identity.order_amount is None:
            return 0
        changed_count = 0
        for result in results:
            changed = False
            if display_id and (not result.display_id or is_uuid_like(result.display_id)):
                result.display_id = display_id
                changed = True
            if identity.order_amount is not None and result.order_amount is None:
                result.order_amount = identity.order_amount
                changed = True
            if changed:
                changed_count += 1
        return changed_count
