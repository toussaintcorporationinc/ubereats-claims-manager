from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ClaimOrder, UberReconciliationResult, User
from app.services.audit import add_audit_log
from app.services.order_identity_resolution_service import (
    ResolvedOrderIdentity,
    clean_customer_name,
    is_uuid_like,
    resolve_identity_for_order,
)


class HistoricalOrderIdentityHydrationService:
    """Backfill missing client/date labels from already imported Uber/proof sources."""

    def apply(
        self,
        db: Session,
        current_user: User,
        *,
        restaurant_id: int | None = None,
        limit: int = 10000,
    ) -> dict[str, object]:
        statement = select(ClaimOrder).where(
            or_(
                ClaimOrder.customer_name.is_(None),
                ClaimOrder.customer_name == "",
                ClaimOrder.order_date.is_(None),
                ClaimOrder.order_time.is_(None),
                ClaimOrder.order_amount.is_(None),
            )
        )
        if restaurant_id is not None:
            statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
        orders = list(db.scalars(statement.order_by(ClaimOrder.id.desc()).limit(limit)).all())

        updated_order_ids: list[int] = []
        updated_disputes_count = 0
        updated_reconciliation_results_count = 0
        skipped_count = 0
        sources: set[str] = set()

        for order in orders:
            identity = resolve_identity_for_order(db, order)
            order_changed = self.apply_identity_to_order(order, identity)
            disputes_changed = self.apply_identity_to_disputes(order, identity)
            results_changed = self.apply_identity_to_reconciliation_results(db, order, identity)
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
                    "sample_order_ids": updated_order_ids[:25],
                    "sources": sorted(sources),
                },
            )

        return {
            "scanned_count": len(orders),
            "updated_orders_count": len(updated_order_ids),
            "updated_disputes_count": updated_disputes_count,
            "updated_reconciliation_results_count": updated_reconciliation_results_count,
            "skipped_count": skipped_count,
            "sample_order_ids": updated_order_ids[:25],
            "sources": sorted(sources),
        }

    def apply_identity_to_order(self, order: ClaimOrder, identity: ResolvedOrderIdentity) -> bool:
        changed = False
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
        db: Session,
        order: ClaimOrder,
        identity: ResolvedOrderIdentity,
    ) -> int:
        display_id = identity.best_order_label if identity.best_order_label and not is_uuid_like(identity.best_order_label) else None
        if not display_id and identity.order_amount is None:
            return 0
        results = db.scalars(select(UberReconciliationResult).where(UberReconciliationResult.claim_order_id == order.id)).all()
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
