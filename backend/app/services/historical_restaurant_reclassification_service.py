from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AppealWorkflow,
    AutopilotAction,
    ClaimOrder,
    EvidenceRequestTask,
    Restaurant,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReconciliationResult,
    UberStoreMapping,
    User,
)
from app.services.audit import add_audit_log
from app.services.uber_reporting_import_service import (
    get_column_value,
    normalize_restaurant_lookup_key,
    resolve_mapping,
    resolve_mapping_by_store_name,
    resolve_restaurant_by_store_name,
)


RECLASSIFICATION_LIMIT_DEFAULT = 500
RECLASSIFICATION_LIMIT_MAX = 5000
RECLASSIFICATION_MIN_CONFIDENCE = Decimal("0.85")


@dataclass(slots=True)
class ReclassificationTarget:
    restaurant_id: int
    restaurant_name: str
    reason: str
    confidence: Decimal
    source_value: str


@dataclass(slots=True)
class ReclassificationCandidate:
    entity_type: str
    entity_id: int
    uber_store_id: str | None
    uber_store_name: str | None
    uber_order_id: str | None
    display_id: str | None
    current_restaurant_id: int
    current_restaurant_name: str
    target_restaurant_id: int
    target_restaurant_name: str
    reason: str
    confidence: Decimal
    status: str = "eligible"
    blockers: list[str] = field(default_factory=list)
    linked_updates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.entity_type}:{self.entity_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "uber_store_id": self.uber_store_id,
            "uber_store_name": self.uber_store_name,
            "uber_order_id": self.uber_order_id,
            "display_id": self.display_id,
            "current_restaurant_id": self.current_restaurant_id,
            "current_restaurant_name": self.current_restaurant_name,
            "target_restaurant_id": self.target_restaurant_id,
            "target_restaurant_name": self.target_restaurant_name,
            "reason": self.reason,
            "confidence": self.confidence,
            "status": self.status,
            "blockers": self.blockers,
            "linked_updates": self.linked_updates,
        }


class HistoricalRestaurantReclassificationService:
    def preview(
        self,
        db: Session,
        current_user: User,
        *,
        restaurant_id: int | None = None,
        min_confidence: Decimal = RECLASSIFICATION_MIN_CONFIDENCE,
        limit: int = RECLASSIFICATION_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        candidates = self.scan_candidates(
            db,
            restaurant_id=restaurant_id,
            min_confidence=min_confidence,
            limit=limit,
        )
        return self.build_response(candidates, applied=False, current_user=current_user)

    def apply(
        self,
        db: Session,
        current_user: User,
        *,
        restaurant_id: int | None = None,
        min_confidence: Decimal = RECLASSIFICATION_MIN_CONFIDENCE,
        limit: int = RECLASSIFICATION_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        candidates = self.scan_candidates(
            db,
            restaurant_id=restaurant_id,
            min_confidence=min_confidence,
            limit=limit,
        )
        moved: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.blockers:
                candidate.status = "blocked"
                skipped.append(candidate.to_dict())
                continue
            linked_updates = self.apply_candidate(db, current_user, candidate)
            candidate.linked_updates = linked_updates
            candidate.status = "applied"
            moved.append(candidate.to_dict())
        add_audit_log(
            db,
            entity_type="historical_restaurant_reclassification",
            entity_id=current_user.id,
            action="historical_restaurant_reclassification.apply",
            user_id=current_user.id,
            new_value={
                "moved_count": len(moved),
                "skipped_count": len(skipped),
                "restaurant_id": restaurant_id,
                "min_confidence": str(min_confidence),
            },
        )
        db.commit()
        return self.build_response(candidates, applied=True, current_user=current_user, moved=moved, skipped=skipped)

    def scan_candidates(
        self,
        db: Session,
        *,
        restaurant_id: int | None,
        min_confidence: Decimal,
        limit: int,
    ) -> list[ReclassificationCandidate]:
        bounded_limit = min(max(limit, 1), RECLASSIFICATION_LIMIT_MAX)
        restaurants = {restaurant.id: restaurant.name for restaurant in db.scalars(select(Restaurant)).all()}
        candidates: list[ReclassificationCandidate] = []
        seen: set[str] = set()

        snapshot_statement = select(UberOrderSnapshot).order_by(UberOrderSnapshot.id)
        if restaurant_id is not None:
            snapshot_statement = snapshot_statement.where(UberOrderSnapshot.restaurant_id == restaurant_id)
        for snapshot in db.scalars(snapshot_statement).all():
            candidate = self.snapshot_candidate(db, snapshot, restaurants, min_confidence)
            if candidate and candidate.key not in seen:
                self.attach_linked_preview(db, candidate)
                candidates.append(candidate)
                seen.add(candidate.key)
            if len(candidates) >= bounded_limit:
                return candidates

        transaction_statement = select(UberFinancialTransaction).order_by(UberFinancialTransaction.id)
        if restaurant_id is not None:
            transaction_statement = transaction_statement.where(UberFinancialTransaction.restaurant_id == restaurant_id)
        for transaction in db.scalars(transaction_statement).all():
            candidate = self.transaction_candidate(db, transaction, restaurants, min_confidence)
            if candidate and candidate.key not in seen:
                self.attach_linked_preview(db, candidate)
                candidates.append(candidate)
                seen.add(candidate.key)
            if len(candidates) >= bounded_limit:
                return candidates
        return candidates

    def snapshot_candidate(
        self,
        db: Session,
        snapshot: UberOrderSnapshot,
        restaurants: dict[int, str],
        min_confidence: Decimal,
    ) -> ReclassificationCandidate | None:
        target = self.resolve_target(db, snapshot.uber_store_id, snapshot.raw_payload_json)
        if target is None or target.confidence < min_confidence or target.restaurant_id == snapshot.restaurant_id:
            return None
        return ReclassificationCandidate(
            entity_type="uber_order_snapshot",
            entity_id=snapshot.id,
            uber_store_id=snapshot.uber_store_id,
            uber_store_name=self.extract_store_name(snapshot.raw_payload_json),
            uber_order_id=snapshot.uber_order_id,
            display_id=snapshot.display_id,
            current_restaurant_id=snapshot.restaurant_id,
            current_restaurant_name=restaurants.get(snapshot.restaurant_id, f"Restaurant #{snapshot.restaurant_id}"),
            target_restaurant_id=target.restaurant_id,
            target_restaurant_name=target.restaurant_name,
            reason=target.reason,
            confidence=target.confidence,
        )

    def transaction_candidate(
        self,
        db: Session,
        transaction: UberFinancialTransaction,
        restaurants: dict[int, str],
        min_confidence: Decimal,
    ) -> ReclassificationCandidate | None:
        target = self.resolve_target(db, transaction.uber_store_id, transaction.raw_payload_json)
        if target is None or target.confidence < min_confidence or target.restaurant_id == transaction.restaurant_id:
            return None
        return ReclassificationCandidate(
            entity_type="uber_financial_transaction",
            entity_id=transaction.id,
            uber_store_id=transaction.uber_store_id,
            uber_store_name=self.extract_store_name(transaction.raw_payload_json),
            uber_order_id=transaction.uber_order_id,
            display_id=self.extract_display_id(transaction.raw_payload_json),
            current_restaurant_id=transaction.restaurant_id,
            current_restaurant_name=restaurants.get(transaction.restaurant_id, f"Restaurant #{transaction.restaurant_id}"),
            target_restaurant_id=target.restaurant_id,
            target_restaurant_name=target.restaurant_name,
            reason=target.reason,
            confidence=target.confidence,
        )

    def resolve_target(
        self,
        db: Session,
        uber_store_id: object,
        payload: dict[str, Any] | None,
    ) -> ReclassificationTarget | None:
        store_id = clean_text(uber_store_id) or clean_text((payload or {}).get("uber_store_id"))
        if store_id and not store_id.startswith("restaurant-name:"):
            mapping = resolve_mapping(db, store_id)
            if mapping and mapping.active:
                return self.target_from_mapping(db, mapping, "store_id_mapping", Decimal("1.00"), store_id)

        store_name = self.extract_store_name(payload)
        if store_name:
            mapping = resolve_mapping_by_store_name(db, store_name)
            if mapping and mapping.active:
                return self.target_from_mapping(db, mapping, "store_name_mapping", Decimal("0.95"), store_name)
            restaurant = resolve_restaurant_by_store_name(db, store_name)
            if restaurant:
                return ReclassificationTarget(
                    restaurant_id=restaurant.id,
                    restaurant_name=restaurant.name,
                    reason="restaurant_name_exact_match",
                    confidence=Decimal("0.90"),
                    source_value=store_name,
                )
        return None

    def target_from_mapping(
        self,
        db: Session,
        mapping: UberStoreMapping,
        reason: str,
        confidence: Decimal,
        source_value: str,
    ) -> ReclassificationTarget | None:
        restaurant = db.get(Restaurant, mapping.restaurant_id)
        if restaurant is None or not restaurant.active:
            return None
        return ReclassificationTarget(
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            reason=reason,
            confidence=confidence,
            source_value=source_value,
        )

    def attach_linked_preview(self, db: Session, candidate: ReclassificationCandidate) -> None:
        linked: list[dict[str, Any]] = []
        if candidate.entity_type == "uber_order_snapshot":
            snapshot = db.get(UberOrderSnapshot, candidate.entity_id)
            if snapshot is not None:
                linked.extend(self.preview_snapshot_dependents(db, snapshot, candidate))
        if candidate.entity_type == "uber_financial_transaction":
            transaction = db.get(UberFinancialTransaction, candidate.entity_id)
            if transaction is not None:
                linked.extend(self.preview_transaction_dependents(db, transaction, candidate))
        candidate.linked_updates = linked

    def preview_snapshot_dependents(
        self,
        db: Session,
        snapshot: UberOrderSnapshot,
        candidate: ReclassificationCandidate,
    ) -> list[dict[str, Any]]:
        linked: list[dict[str, Any]] = []
        for result in db.scalars(select(UberReconciliationResult).where(UberReconciliationResult.matched_snapshot_id == snapshot.id)):
            linked.append(self.preview_linked_entity("uber_reconciliation_result", result.id, result.restaurant_id, candidate))
            self.add_conflict_if_reconciliation_exists(db, result, candidate)
        for order in self.find_claim_orders_for_order_numbers(db, snapshot.restaurant_id, [snapshot.uber_order_id, snapshot.display_id]):
            linked.append(self.preview_linked_entity("claim_order", order.id, order.restaurant_id, candidate))
            self.add_conflict_if_claim_order_exists(db, order, candidate)
        return linked

    def preview_transaction_dependents(
        self,
        db: Session,
        transaction: UberFinancialTransaction,
        candidate: ReclassificationCandidate,
    ) -> list[dict[str, Any]]:
        linked: list[dict[str, Any]] = []
        for dispute in db.scalars(
            select(UberCustomerRefundDispute).where(UberCustomerRefundDispute.financial_transaction_id == transaction.id)
        ):
            linked.append(self.preview_linked_entity("customer_refund_dispute", dispute.id, dispute.restaurant_id, candidate))
            if dispute.claim_order_id:
                order = db.get(ClaimOrder, dispute.claim_order_id)
                if order:
                    linked.append(self.preview_linked_entity("claim_order", order.id, order.restaurant_id, candidate))
                    self.add_conflict_if_claim_order_exists(db, order, candidate)
        for result in db.scalars(select(UberReconciliationResult)).all():
            if transaction.id in (result.matched_transaction_ids_json or []):
                linked.append(self.preview_linked_entity("uber_reconciliation_result", result.id, result.restaurant_id, candidate))
                self.add_conflict_if_reconciliation_exists(db, result, candidate)
        return linked

    def preview_linked_entity(
        self,
        entity_type: str,
        entity_id: int,
        current_restaurant_id: int,
        candidate: ReclassificationCandidate,
    ) -> dict[str, Any]:
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "current_restaurant_id": current_restaurant_id,
            "target_restaurant_id": candidate.target_restaurant_id,
            "action": "move_with_parent" if current_restaurant_id != candidate.target_restaurant_id else "already_target",
        }

    def apply_candidate(self, db: Session, current_user: User, candidate: ReclassificationCandidate) -> list[dict[str, Any]]:
        linked_updates: list[dict[str, Any]] = []
        if candidate.entity_type == "uber_order_snapshot":
            snapshot = db.get(UberOrderSnapshot, candidate.entity_id)
            if snapshot is None:
                return [{"entity_type": candidate.entity_type, "entity_id": candidate.entity_id, "status": "missing"}]
            linked_updates.append(self.move_entity(db, current_user, snapshot, "uber_order_snapshot", candidate))
            for result in db.scalars(select(UberReconciliationResult).where(UberReconciliationResult.matched_snapshot_id == snapshot.id)):
                linked_updates.append(self.move_reconciliation_result(db, current_user, result, candidate))
            for order in self.find_claim_orders_for_order_numbers(db, candidate.current_restaurant_id, [snapshot.uber_order_id, snapshot.display_id]):
                linked_updates.append(self.move_claim_order(db, current_user, order, candidate))
        elif candidate.entity_type == "uber_financial_transaction":
            transaction = db.get(UberFinancialTransaction, candidate.entity_id)
            if transaction is None:
                return [{"entity_type": candidate.entity_type, "entity_id": candidate.entity_id, "status": "missing"}]
            linked_updates.append(self.move_entity(db, current_user, transaction, "uber_financial_transaction", candidate))
            for dispute in db.scalars(
                select(UberCustomerRefundDispute).where(UberCustomerRefundDispute.financial_transaction_id == transaction.id)
            ):
                linked_updates.append(self.move_customer_refund_dispute(db, current_user, dispute, candidate, transaction))
            for result in db.scalars(select(UberReconciliationResult)).all():
                if transaction.id in (result.matched_transaction_ids_json or []):
                    linked_updates.append(self.move_reconciliation_result(db, current_user, result, candidate))
        return linked_updates

    def move_entity(
        self,
        db: Session,
        current_user: User,
        entity: Any,
        entity_type: str,
        candidate: ReclassificationCandidate,
    ) -> dict[str, Any]:
        old_restaurant_id = entity.restaurant_id
        if old_restaurant_id == candidate.target_restaurant_id:
            return {"entity_type": entity_type, "entity_id": entity.id, "status": "already_target"}
        entity.restaurant_id = candidate.target_restaurant_id
        if hasattr(entity, "raw_payload_json"):
            entity.raw_payload_json = self.updated_payload(
                getattr(entity, "raw_payload_json", None),
                old_restaurant_id,
                candidate,
                entity_type,
            )
        add_audit_log(
            db,
            entity_type=entity_type,
            entity_id=entity.id,
            action="historical_restaurant_reclassification.move",
            user_id=current_user.id,
            old_value={"restaurant_id": old_restaurant_id},
            new_value={
                "restaurant_id": candidate.target_restaurant_id,
                "reason": candidate.reason,
                "confidence": str(candidate.confidence),
            },
        )
        return {
            "entity_type": entity_type,
            "entity_id": entity.id,
            "status": "moved",
            "from_restaurant_id": old_restaurant_id,
            "to_restaurant_id": candidate.target_restaurant_id,
        }

    def move_customer_refund_dispute(
        self,
        db: Session,
        current_user: User,
        dispute: UberCustomerRefundDispute,
        candidate: ReclassificationCandidate,
        transaction: UberFinancialTransaction,
    ) -> dict[str, Any]:
        update = self.move_entity(db, current_user, dispute, "customer_refund_dispute", candidate)
        dispute.uber_store_id = transaction.uber_store_id
        if dispute.claim_order_id:
            order = db.get(ClaimOrder, dispute.claim_order_id)
            if order:
                claim_update = self.move_claim_order(db, current_user, order, candidate)
                update.setdefault("linked_updates", []).append(claim_update)
        self.move_evidence_tasks(db, current_user, candidate, customer_refund_dispute_id=dispute.id)
        self.move_appeals(db, current_user, candidate, customer_refund_dispute_id=dispute.id)
        self.move_autopilot_actions(db, current_user, candidate, "customer_refund_dispute", dispute.id)
        return update

    def move_reconciliation_result(
        self,
        db: Session,
        current_user: User,
        result: UberReconciliationResult,
        candidate: ReclassificationCandidate,
    ) -> dict[str, Any]:
        conflict = self.reconciliation_conflict(db, result, candidate.target_restaurant_id)
        if conflict:
            return {
                "entity_type": "uber_reconciliation_result",
                "entity_id": result.id,
                "status": "blocked",
                "reason": "target_reconciliation_result_exists",
                "conflicting_entity_id": conflict.id,
            }
        update = self.move_entity(db, current_user, result, "uber_reconciliation_result", candidate)
        if result.claim_order_id:
            order = db.get(ClaimOrder, result.claim_order_id)
            if order:
                claim_update = self.move_claim_order(db, current_user, order, candidate)
                update.setdefault("linked_updates", []).append(claim_update)
        self.move_evidence_tasks(db, current_user, candidate, reconciliation_result_id=result.id)
        self.move_appeals(db, current_user, candidate, reconciliation_result_id=result.id)
        self.move_autopilot_actions(db, current_user, candidate, "reconciliation_result", result.id)
        return update

    def move_claim_order(
        self,
        db: Session,
        current_user: User,
        order: ClaimOrder,
        candidate: ReclassificationCandidate,
    ) -> dict[str, Any]:
        conflict = self.claim_order_conflict(db, order, candidate.target_restaurant_id)
        if conflict:
            return {
                "entity_type": "claim_order",
                "entity_id": order.id,
                "status": "blocked",
                "reason": "target_claim_order_exists",
                "conflicting_entity_id": conflict.id,
            }
        update = self.move_entity(db, current_user, order, "claim_order", candidate)
        self.move_evidence_tasks(db, current_user, candidate, order_id=order.id)
        self.move_appeals(db, current_user, candidate, claim_order_id=order.id)
        self.move_autopilot_actions(db, current_user, candidate, "claim_order", order.id)
        return update

    def move_evidence_tasks(
        self,
        db: Session,
        current_user: User,
        candidate: ReclassificationCandidate,
        **filters: int,
    ) -> None:
        statement = select(EvidenceRequestTask)
        for field_name, value in filters.items():
            statement = statement.where(getattr(EvidenceRequestTask, field_name) == value)
        for task in db.scalars(statement).all():
            self.move_entity(db, current_user, task, "evidence_request_task", candidate)

    def move_appeals(
        self,
        db: Session,
        current_user: User,
        candidate: ReclassificationCandidate,
        **filters: int,
    ) -> None:
        statement = select(AppealWorkflow)
        for field_name, value in filters.items():
            statement = statement.where(getattr(AppealWorkflow, field_name) == value)
        for workflow in db.scalars(statement).all():
            self.move_entity(db, current_user, workflow, "appeal_workflow", candidate)

    def move_autopilot_actions(
        self,
        db: Session,
        current_user: User,
        candidate: ReclassificationCandidate,
        case_type: str,
        case_id: int,
    ) -> None:
        for action in db.scalars(
            select(AutopilotAction).where(
                AutopilotAction.case_type == case_type,
                AutopilotAction.case_id == case_id,
            )
        ):
            self.move_entity(db, current_user, action, "autopilot_action", candidate)

    def find_claim_orders_for_order_numbers(
        self,
        db: Session,
        restaurant_id: int,
        order_numbers: list[str | None],
    ) -> list[ClaimOrder]:
        clean_numbers = [number for number in {clean_text(number) for number in order_numbers} if number]
        if not clean_numbers:
            return []
        return list(
            db.scalars(
                select(ClaimOrder).where(
                    ClaimOrder.restaurant_id == restaurant_id,
                    ClaimOrder.uber_order_number.in_(clean_numbers),
                )
            ).all()
        )

    def add_conflict_if_claim_order_exists(
        self,
        db: Session,
        order: ClaimOrder,
        candidate: ReclassificationCandidate,
    ) -> None:
        conflict = self.claim_order_conflict(db, order, candidate.target_restaurant_id)
        if conflict:
            candidate.blockers.append(f"target_claim_order_exists:{conflict.id}")

    def claim_order_conflict(
        self,
        db: Session,
        order: ClaimOrder,
        target_restaurant_id: int,
    ) -> ClaimOrder | None:
        return db.scalar(
            select(ClaimOrder).where(
                ClaimOrder.restaurant_id == target_restaurant_id,
                ClaimOrder.uber_order_number == order.uber_order_number,
                ClaimOrder.id != order.id,
            )
        )

    def add_conflict_if_reconciliation_exists(
        self,
        db: Session,
        result: UberReconciliationResult,
        candidate: ReclassificationCandidate,
    ) -> None:
        conflict = self.reconciliation_conflict(db, result, candidate.target_restaurant_id)
        if conflict:
            candidate.blockers.append(f"target_reconciliation_result_exists:{conflict.id}")

    def reconciliation_conflict(
        self,
        db: Session,
        result: UberReconciliationResult,
        target_restaurant_id: int,
    ) -> UberReconciliationResult | None:
        return db.scalar(
            select(UberReconciliationResult).where(
                UberReconciliationResult.restaurant_id == target_restaurant_id,
                UberReconciliationResult.uber_order_id == result.uber_order_id,
                UberReconciliationResult.id != result.id,
            )
        )

    def extract_store_name(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        direct = clean_text(payload.get("uber_store_name") or payload.get("store_name") or payload.get("restaurant_name"))
        if direct:
            return direct
        raw_data = payload.get("raw_data")
        if isinstance(raw_data, dict):
            value = get_column_value(raw_data, "uber_store_name")
            if value:
                return clean_text(value)
            for key, item in raw_data.items():
                key_match = normalize_restaurant_lookup_key(key)
                if key_match in {"nomdurestaurant", "restaurant", "storename", "merchantname"}:
                    cleaned = clean_text(item)
                    if cleaned:
                        return cleaned
        return None

    def extract_display_id(self, payload: dict[str, Any] | None) -> str | None:
        if not payload:
            return None
        return clean_text(payload.get("display_id"))

    def updated_payload(
        self,
        payload: dict[str, Any] | None,
        old_restaurant_id: int,
        candidate: ReclassificationCandidate,
        entity_type: str,
    ) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return payload
        updated = dict(payload)
        updated["restaurant_id"] = candidate.target_restaurant_id
        history = list(updated.get("restaurant_reclassification_history") or [])
        history.append(
            {
                "entity_type": entity_type,
                "from_restaurant_id": old_restaurant_id,
                "to_restaurant_id": candidate.target_restaurant_id,
                "reason": candidate.reason,
                "confidence": str(candidate.confidence),
            }
        )
        updated["restaurant_reclassification_history"] = history[-10:]
        return updated

    def build_response(
        self,
        candidates: list[ReclassificationCandidate],
        *,
        applied: bool,
        current_user: User,
        moved: list[dict[str, Any]] | None = None,
        skipped: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        eligible = [candidate for candidate in candidates if not candidate.blockers]
        blocked = [candidate for candidate in candidates if candidate.blockers]
        return {
            "status": "applied" if applied else "preview",
            "total_candidates": len(candidates),
            "eligible_count": len(eligible),
            "blocked_count": len(blocked),
            "moved_count": len(moved or []),
            "skipped_count": len(skipped or []),
            "candidates": [candidate.to_dict() for candidate in candidates],
            "moved": moved or [],
            "skipped": skipped or [],
            "run_by_user_id": current_user.id,
        }


def clean_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
