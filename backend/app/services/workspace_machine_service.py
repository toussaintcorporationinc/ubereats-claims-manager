from collections.abc import Callable
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import ClaimOrder, UberCustomerRefundDispute, User
from app.schemas.domain import (
    WorkspaceMachineRunRequest,
    WorkspaceMachineRunResponse,
    WorkspaceMachineStage,
)
from app.services.appeal_workflow_service import AppealWorkflowError, recalculate_appeal_workflows
from app.services.audit import add_audit_log
from app.services.autopilot_service import AutopilotError, run_autopilot
from app.services.customer_refund_detection_service import detect_customer_refund_disputes
from app.services.customer_refund_dispute_service import create_claim_orders_bulk, create_drafts_bulk
from app.services.evidence_ai_analysis_service import EvidenceAIAnalysisService
from app.services.evidence_request_service import recalculate_evidence_tasks
from app.services.email_provider import EmailProvider, EmailProviderError
from app.services.followup_policy_service import FOLLOWUP_ELIGIBLE_STATUSES, FollowUpPolicyService
from app.services.gmail_inbound_sync_service import GmailInboundSyncService
from app.services.historical_order_identity_hydration_service import HistoricalOrderIdentityHydrationService
from app.services.historical_restaurant_reclassification_service import HistoricalRestaurantReclassificationService
from app.services.historical_uber_reporting_repair_service import HistoricalUberReportingRepairService
from app.services.proof_intake_service import ProofIntakeService
from app.services.workspace_action_service import WorkspaceActionService
from app.services.workspace_unclassified_service import WorkspaceUnclassifiedService


class WorkspaceMachineError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WorkspaceMachineService:
    def __init__(self, db: Session, current_user: User, provider: EmailProvider) -> None:
        self.db = db
        self.current_user = current_user
        self.provider = provider
        self.settings = get_settings()

    def run(self, payload: WorkspaceMachineRunRequest) -> WorkspaceMachineRunResponse:
        if self.current_user.role == "staff":
            raise WorkspaceMachineError("Insufficient permissions", 403)
        if payload.restaurant_id is not None and not can_access_restaurant(self.db, self.current_user, payload.restaurant_id):
            raise WorkspaceMachineError("Restaurant access denied", 403)

        stages = [
            *self.historical_cleanup_stages(payload),
            self.stage("deductions", lambda: self.detect_customer_refunds(payload.restaurant_id)),
            self.stage("claim_orders", lambda: self.create_customer_refund_claim_orders(payload.restaurant_id)),
            self.stage("evidence", lambda: self.process_evidence_queue(payload)),
            self.stage("proof_intake", lambda: self.process_proof_intake(payload)),
            self.stage("unclassified", self.inspect_unclassified),
            self.stage("drafts", lambda: self.create_customer_refund_drafts(payload.restaurant_id)),
            self.stage("followups", lambda: self.recalculate_followups(payload.restaurant_id)),
            self.stage("appeals", lambda: self.recalculate_appeals(payload.restaurant_id)),
        ]
        if payload.sync_gmail:
            stages.append(self.stage("gmail_sync", self.sync_gmail))
        else:
            stages.append(WorkspaceMachineStage(name="gmail_sync", status="skipped", warnings=["sync_gmail_disabled_for_run"]))
        if payload.run_autopilot:
            stages.append(self.stage("autopilot", lambda: self.run_autopilot(payload.restaurant_id)))
        else:
            stages.append(WorkspaceMachineStage(name="autopilot", status="skipped", warnings=["autopilot_disabled_for_run"]))

        add_audit_log(
            self.db,
            entity_type="workspace_machine",
            entity_id=self.current_user.id,
            action="workspace_machine.run",
            user_id=self.current_user.id,
            new_value={
                "trigger": payload.trigger,
                "restaurant_id": payload.restaurant_id,
                "smart_import_batch_id": payload.smart_import_batch_id,
                "run_historical_cleanup": payload.run_historical_cleanup,
                "stages": [stage.model_dump() for stage in stages],
            },
        )
        self.db.commit()

        response_status = aggregate_status(stages)
        return WorkspaceMachineRunResponse(
            status=response_status,
            trigger=payload.trigger,
            recipient_email=self.settings.default_uber_eats_support_email,
            stages=stages,
            next_actions=WorkspaceActionService(self.db, self.current_user).next_actions(),
        )

    def historical_cleanup_stages(self, payload: WorkspaceMachineRunRequest) -> list[WorkspaceMachineStage]:
        if not payload.run_historical_cleanup:
            return [
                WorkspaceMachineStage(
                    name="historical_reclassification",
                    status="skipped",
                    warnings=["historical_cleanup_not_requested_for_fast_go"],
                ),
                WorkspaceMachineStage(
                    name="historical_import_repair",
                    status="skipped",
                    warnings=["historical_cleanup_not_requested_for_fast_go"],
                ),
                WorkspaceMachineStage(
                    name="historical_identity_hydration",
                    status="skipped",
                    warnings=["historical_cleanup_not_requested_for_fast_go"],
                ),
            ]
        return [
            self.stage("historical_reclassification", lambda: self.reclassify_historical_restaurants(payload.restaurant_id)),
            self.stage("historical_import_repair", lambda: self.repair_historical_import_rows(payload.restaurant_id)),
            self.stage("historical_identity_hydration", lambda: self.hydrate_historical_order_identity(payload.restaurant_id)),
        ]

    def stage(self, name: str, callback: Callable[[], WorkspaceMachineStage]) -> WorkspaceMachineStage:
        try:
            return callback()
        except WorkspaceMachineError as exc:
            return WorkspaceMachineStage(name=name, status="failed", errors=[exc.message], failed_count=1)
        except HTTPException as exc:
            return WorkspaceMachineStage(name=name, status="warning", warnings=[str(exc.detail)], skipped_count=1)
        except Exception as exc:  # noqa: BLE001 - the cockpit must report per-stage failures without hiding other work.
            return WorkspaceMachineStage(name=name, status="failed", errors=[str(exc)], failed_count=1)

    def detect_customer_refunds(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        result = detect_customer_refund_disputes(self.db, self.current_user, restaurant_id=restaurant_id)
        status = "warning" if result.errors else "completed"
        return WorkspaceMachineStage(
            name="deductions",
            status=status,
            processed_count=result.detected_count + result.needs_evidence_count + result.manual_review_count,
            created_count=result.detected_count,
            warnings=result.errors,
        )

    def reclassify_historical_restaurants(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        if self.current_user.role != "owner":
            return WorkspaceMachineStage(
                name="historical_reclassification",
                status="skipped",
                warnings=["owner_required_for_historical_cleanup"],
            )
        result = HistoricalRestaurantReclassificationService().apply(
            self.db,
            self.current_user,
            restaurant_id=restaurant_id,
            min_confidence=Decimal("0.90"),
            limit=5000,
        )
        blocked_count = int(result.get("blocked_count", 0))
        moved_count = int(result.get("moved_count", 0))
        warnings = [f"{blocked_count}_historical_case(s)_need_manual_review"] if blocked_count else []
        return WorkspaceMachineStage(
            name="historical_reclassification",
            status="warning" if blocked_count else "completed",
            processed_count=int(result.get("total_candidates", 0)),
            created_count=moved_count,
            skipped_count=int(result.get("skipped_count", 0)) + blocked_count,
            warnings=warnings,
        )

    def repair_historical_import_rows(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        if self.current_user.role != "owner":
            return WorkspaceMachineStage(
                name="historical_import_repair",
                status="skipped",
                warnings=["owner_required_for_import_repair"],
            )
        result = HistoricalUberReportingRepairService().apply(
            self.db,
            self.current_user,
            restaurant_id=restaurant_id,
            min_confidence=Decimal("0.90"),
            limit=10000,
        )
        blocked_count = int(result.get("blocked_count", 0))
        repaired_count = int(result.get("repaired_count", 0))
        warnings = [f"{blocked_count}_import_row(s)_need_manual_review"] if blocked_count else []
        return WorkspaceMachineStage(
            name="historical_import_repair",
            status="warning" if blocked_count else "completed",
            processed_count=int(result.get("scanned_count", 0)),
            created_count=repaired_count,
            skipped_count=int(result.get("skipped_count", 0)) + blocked_count,
            warnings=warnings,
        )

    def hydrate_historical_order_identity(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        if self.current_user.role != "owner":
            return WorkspaceMachineStage(
                name="historical_identity_hydration",
                status="skipped",
                warnings=["owner_required_for_identity_hydration"],
            )
        result = HistoricalOrderIdentityHydrationService().apply(
            self.db,
            self.current_user,
            restaurant_id=restaurant_id,
            limit=10000,
        )
        return WorkspaceMachineStage(
            name="historical_identity_hydration",
            status="completed",
            processed_count=int(result.get("scanned_count", 0)),
            created_count=int(result.get("updated_orders_count", 0)),
            skipped_count=int(result.get("skipped_count", 0)),
            warnings=[f"sources:{','.join(result.get('sources', []))}"] if result.get("sources") else [],
        )

    def create_customer_refund_claim_orders(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        dispute_ids = self.dispute_ids_without_claim_order(restaurant_id)
        if not dispute_ids:
            return WorkspaceMachineStage(name="claim_orders", status="skipped", warnings=["no_eligible_customer_refund_disputes"])
        result = create_claim_orders_bulk(self.db, self.current_user, dispute_ids)
        errors = [str(item) for item in result.get("errors", [])]
        return WorkspaceMachineStage(
            name="claim_orders",
            status="warning" if errors else "completed",
            processed_count=len(dispute_ids),
            created_count=int(result.get("created_count", 0)),
            skipped_count=int(result.get("skipped_count", 0)),
            warnings=errors,
        )

    def create_customer_refund_drafts(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        dispute_ids = self.dispute_ids_ready_for_internal_draft(restaurant_id)
        if not dispute_ids:
            return WorkspaceMachineStage(name="drafts", status="skipped", warnings=["no_customer_refund_disputes_ready_for_draft"])
        result = create_drafts_bulk(self.db, self.current_user, dispute_ids)
        errors = [str(item) for item in result.get("errors", [])]
        return WorkspaceMachineStage(
            name="drafts",
            status="warning" if errors else "completed",
            processed_count=len(dispute_ids),
            created_count=int(result.get("created_count", 0)),
            skipped_count=int(result.get("skipped_count", 0)),
            warnings=errors,
        )

    def process_evidence_queue(self, payload: WorkspaceMachineRunRequest) -> WorkspaceMachineStage:
        evidence_batch_ids = ProofIntakeService().evidence_batch_ids_for_preview(
            self.db,
            self.current_user,
            payload.smart_import_batch_id,
        )
        recalc = recalculate_evidence_tasks(
            self.db,
            self.current_user,
            restaurant_id=payload.restaurant_id,
            dry_run=False,
        )
        self.db.flush()
        evidence_result = EvidenceAIAnalysisService().analyze_pending_batches(
            self.db,
            self.current_user,
            restaurant_id=payload.restaurant_id,
            limit=2000,
            batch_ids=evidence_batch_ids,
        )
        warnings = [*recalc.get("errors", []), *evidence_result.get("errors", [])]
        processed_count = (
            int(recalc.get("created_tasks", 0))
            + int(recalc.get("existing_tasks", 0))
            + int(recalc.get("completed_tasks", 0))
            + int(evidence_result.get("analyzed_files_count", 0))
        )
        return WorkspaceMachineStage(
            name="evidence",
            status="warning" if warnings else "completed",
            processed_count=processed_count,
            created_count=int(recalc.get("created_tasks", 0)) + int(evidence_result.get("auto_matched_count", 0)),
            skipped_count=int(recalc.get("skipped_orders", 0)) + int(evidence_result.get("needs_review_count", 0)),
            failed_count=int(evidence_result.get("failed_files_count", 0)),
            warnings=warnings,
        )

    def process_proof_intake(self, payload: WorkspaceMachineRunRequest) -> WorkspaceMachineStage:
        result = ProofIntakeService().process(
            self.db,
            self.current_user,
            trigger=payload.trigger,
            restaurant_id=payload.restaurant_id,
            smart_import_batch_id=payload.smart_import_batch_id,
            limit=2000,
        )
        return WorkspaceMachineStage(
            name="proof_intake",
            status="warning" if result.warnings else "completed",
            processed_count=result.processed_count,
            created_count=result.created_count,
            skipped_count=result.skipped_count,
            warnings=result.warnings[:50],
        )

    def inspect_unclassified(self) -> WorkspaceMachineStage:
        result = WorkspaceUnclassifiedService(self.db, self.current_user).list_items(limit=200)
        return WorkspaceMachineStage(
            name="unclassified",
            status="warning" if result.total_count else "completed",
            processed_count=result.total_count,
            skipped_count=result.total_count,
            warnings=[f"{result.total_count}_source(s)_non_classee(s)_need_context"] if result.total_count else [],
        )

    def recalculate_followups(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        statement = select(ClaimOrder).where(ClaimOrder.status.in_(FOLLOWUP_ELIGIBLE_STATUSES))
        statement = self.filter_by_accessible_restaurants(statement, ClaimOrder.restaurant_id, restaurant_id)
        result = FollowUpPolicyService().recalculate(self.db, self.current_user, statement.order_by(ClaimOrder.id), dry_run=False)
        self.db.commit()
        return WorkspaceMachineStage(
            name="followups",
            status="warning" if result.errors else "completed",
            processed_count=result.created_tasks + result.skipped_orders + result.manual_review_orders,
            created_count=result.created_tasks,
            skipped_count=result.skipped_orders,
            warnings=result.errors,
        )

    def recalculate_appeals(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        try:
            result = recalculate_appeal_workflows(self.db, self.current_user, restaurant_id=restaurant_id)
        except AppealWorkflowError as exc:
            raise WorkspaceMachineError(exc.message, exc.status_code) from exc
        self.db.commit()
        return WorkspaceMachineStage(
            name="appeals",
            status="warning" if result.errors else "completed",
            processed_count=result.created_workflows + result.existing_workflows,
            created_count=result.created_workflows,
            skipped_count=result.existing_workflows,
            warnings=result.errors,
        )

    def sync_gmail(self) -> WorkspaceMachineStage:
        if not self.settings.email_provider_enabled or not self.settings.gmail_inbound_sync_enabled:
            return WorkspaceMachineStage(name="gmail_sync", status="skipped", warnings=["gmail_sync_disabled"])
        service = GmailInboundSyncService(self.provider)
        try:
            result = service.sync(
                self.db,
                self.current_user,
                lookback_days=self.settings.gmail_inbound_sync_lookback_days,
                max_messages=self.settings.gmail_inbound_max_messages_per_sync,
                analyze_responses=True,
                apply_reviews=True,
                run_autopilot_after_sync=True,
            )
        except EmailProviderError as exc:
            self.db.commit()
            return WorkspaceMachineStage(name="gmail_sync", status="warning", warnings=[exc.message], skipped_count=1)
        self.db.commit()
        return WorkspaceMachineStage(
            name="gmail_sync",
            status="warning" if result.errors else "completed",
            processed_count=result.synced_messages,
            created_count=result.applied_reviews,
            sent_count=result.autopilot_sent_count,
            skipped_count=result.manual_review_messages + result.autopilot_skipped_count,
            failed_count=result.autopilot_failed_count,
            warnings=result.errors,
        )

    def run_autopilot(self, restaurant_id: int | None) -> WorkspaceMachineStage:
        try:
            result = run_autopilot(
                self.db,
                self.current_user,
                mode="all",
                restaurant_id=restaurant_id,
                dry_run=False,
                provider=self.provider,
            )
        except AutopilotError as exc:
            self.db.commit()
            return WorkspaceMachineStage(name="autopilot", status="skipped", warnings=[exc.message], skipped_count=1)
        self.db.commit()
        return WorkspaceMachineStage(
            name="autopilot",
            status="warning" if result.run.failed_count else "completed",
            processed_count=result.run.total_candidates,
            sent_count=result.run.sent_count,
            skipped_count=result.run.skipped_count,
            failed_count=result.run.failed_count,
            warnings=[result.run.error_message] if result.run.error_message else [],
        )

    def dispute_ids_without_claim_order(self, restaurant_id: int | None) -> list[int]:
        statement = select(UberCustomerRefundDispute.id).where(
            UberCustomerRefundDispute.claim_order_id.is_(None),
            UberCustomerRefundDispute.status.notin_(["ignored", "sent", "accepted", "payment_confirmed", "refused"]),
        )
        statement = self.filter_by_accessible_restaurants(statement, UberCustomerRefundDispute.restaurant_id, restaurant_id)
        return list(self.db.scalars(statement.order_by(UberCustomerRefundDispute.id)).all())

    def dispute_ids_ready_for_internal_draft(self, restaurant_id: int | None) -> list[int]:
        statement = select(UberCustomerRefundDispute.id).where(
            UberCustomerRefundDispute.claim_order_id.is_not(None),
            UberCustomerRefundDispute.dispute_email_draft_id.is_(None),
            UberCustomerRefundDispute.evidence_status.in_(["complete", "not_required"]),
            UberCustomerRefundDispute.status.in_(["evidence_ready", "needs_evidence", "manual_review"]),
        )
        statement = self.filter_by_accessible_restaurants(statement, UberCustomerRefundDispute.restaurant_id, restaurant_id)
        return list(self.db.scalars(statement.order_by(UberCustomerRefundDispute.id)).all())

    def filter_by_accessible_restaurants(self, statement, restaurant_column, restaurant_id: int | None):
        if restaurant_id is not None:
            return statement.where(restaurant_column == restaurant_id)
        accessible_ids = get_accessible_restaurant_ids(self.db, self.current_user)
        if accessible_ids is not None:
            return statement.where(restaurant_column.in_(accessible_ids or {-1}))
        return statement


def aggregate_status(stages: list[WorkspaceMachineStage]) -> str:
    if any(stage.status == "failed" for stage in stages):
        return "failed"
    if any(stage.status in {"warning", "skipped"} for stage in stages):
        return "warning"
    return "completed"
