from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import (
    AppealAttempt,
    AppealWorkflow,
    ClaimOrder,
    ClaimResponseReview,
    CustomerRefundDisputeReview,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EvidenceRequestTask,
    RefusalAnalysis,
    Restaurant,
    UberCustomerRefundDispute,
    UberReconciliationResult,
    User,
)
from app.models.domain import utc_now
from app.services.appeal_draft_service import AppealDraftError, create_appeal_email_draft
from app.services.audit import add_audit_log
from app.services.refusal_policy_service import (
    analyze_refusal_text,
    appeal_type_for_policy,
    next_action_type_for_policy,
)

TERMINAL_WORKFLOW_STATUSES = {"payment_confirmed", "accepted", "manually_closed"}
ACTIVE_WORKFLOW_STATUSES = {
    "active",
    "appeal_needed",
    "evidence_needed",
    "draft_needed",
    "gmail_draft_needed",
    "appeal_sent",
    "response_received",
    "escalated",
    "payment_to_verify",
    "paused",
}


@dataclass(frozen=True)
class AppealRecalculateResult:
    created_workflows: int
    existing_workflows: int
    errors: list[str]


class AppealWorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def sync_claim_response_review(
    db: Session,
    *,
    order: ClaimOrder,
    review: ClaimResponseReview,
    user: User,
) -> AppealWorkflow | None:
    if not get_settings().appeals_enabled:
        return None
    if review.review_type == "refused":
        workflow = ensure_workflow_for_claim_order(db, order, user)
        workflow.refusal_count += 1
        workflow.last_refusal_at = utc_now()
        analysis = create_refusal_analysis(
            db,
            workflow=workflow,
            user=user,
            refusal_source="claim_response_review",
            review_id=review.id,
            refusal_reason=review.refusal_reason,
            notes=review.notes,
            inbound_message_id=review.inbound_message_id,
        )
        workflow.status = "appeal_needed"
        workflow.next_action_type = next_action_type_for_policy(analysis.recommended_next_action)
        workflow.next_action_at = utc_now()
        workflow.updated_at = utc_now()
        add_workflow_audit(db, workflow, user, "appeal_workflow.opened_from_claim_refusal")
        return workflow
    return sync_resolution_status(db, case_type="claim_order", case_id=order.id, review_type=review.review_type, user=user)


def sync_customer_refund_review(
    db: Session,
    *,
    dispute: UberCustomerRefundDispute,
    review: CustomerRefundDisputeReview,
    user: User,
) -> AppealWorkflow | None:
    if not get_settings().appeals_enabled:
        return None
    if review.review_type == "refused":
        workflow = ensure_workflow_for_customer_refund(db, dispute, user)
        workflow.refusal_count += 1
        workflow.last_refusal_at = utc_now()
        analysis = create_refusal_analysis(
            db,
            workflow=workflow,
            user=user,
            refusal_source="customer_refund_review",
            review_id=review.id,
            refusal_reason=review.refusal_reason,
            notes=review.notes,
            inbound_message_id=review.inbound_message_id,
        )
        workflow.status = "appeal_needed"
        workflow.next_action_type = next_action_type_for_policy(analysis.recommended_next_action)
        workflow.next_action_at = utc_now()
        workflow.updated_at = utc_now()
        add_workflow_audit(db, workflow, user, "appeal_workflow.opened_from_customer_refund_refusal")
        return workflow
    return sync_resolution_status(
        db,
        case_type="customer_refund_dispute",
        case_id=dispute.id,
        review_type=review.review_type,
        user=user,
    )


def sync_resolution_status(
    db: Session,
    *,
    case_type: str,
    case_id: int,
    review_type: str,
    user: User,
) -> AppealWorkflow | None:
    workflow = get_workflow_by_case(db, case_type, case_id)
    if workflow is None:
        return None
    previous_status = workflow.status
    if review_type == "payment_confirmed":
        workflow.status = "payment_confirmed"
        workflow.next_action_type = None
        workflow.next_action_at = None
    elif review_type == "accepted":
        workflow.status = "accepted"
        workflow.next_action_type = None
        workflow.next_action_at = None
    elif review_type == "payment_to_verify":
        workflow.status = "payment_to_verify"
        workflow.next_action_type = "payment_verification"
        workflow.next_action_at = utc_now()
    elif review_type == "evidence_requested":
        workflow.status = "evidence_needed"
        workflow.next_action_type = "request_more_evidence"
        workflow.next_action_at = utc_now()
    elif review_type in {"information_requested", "followup_needed", "manual_review"}:
        workflow.status = "appeal_needed"
        workflow.next_action_type = "manual_review"
        workflow.next_action_at = utc_now()
    else:
        return workflow
    workflow.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=workflow.id,
        action="appeal_workflow.synced_from_review",
        user_id=user.id,
        old_value={"status": previous_status},
        new_value={"status": workflow.status, "review_type": review_type},
    )
    return workflow


def ensure_workflow_for_claim_order(db: Session, order: ClaimOrder, user: User) -> AppealWorkflow:
    workflow = get_workflow_by_case(db, "claim_order", order.id)
    if workflow is not None:
        return workflow
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        current_level=0,
        refusal_count=0,
        appeal_attempt_count=0,
        next_action_type="review_refusal",
        next_action_at=utc_now(),
        opened_by_user_id=user.id,
    )
    db.add(workflow)
    db.flush()
    add_workflow_audit(db, workflow, user, "appeal_workflow.created")
    return workflow


def ensure_workflow_for_customer_refund(
    db: Session,
    dispute: UberCustomerRefundDispute,
    user: User,
) -> AppealWorkflow:
    workflow = get_workflow_by_case(db, "customer_refund_dispute", dispute.id)
    if workflow is not None:
        return workflow
    workflow = AppealWorkflow(
        case_type="customer_refund_dispute",
        case_id=dispute.id,
        restaurant_id=dispute.restaurant_id,
        claim_order_id=dispute.claim_order_id,
        customer_refund_dispute_id=dispute.id,
        status="appeal_needed",
        current_level=0,
        refusal_count=0,
        appeal_attempt_count=0,
        next_action_type="review_refusal",
        next_action_at=utc_now(),
        opened_by_user_id=user.id,
    )
    db.add(workflow)
    db.flush()
    add_workflow_audit(db, workflow, user, "appeal_workflow.created")
    return workflow


def ensure_workflow_for_reconciliation(
    db: Session,
    result: UberReconciliationResult,
    user: User,
) -> AppealWorkflow:
    workflow = get_workflow_by_case(db, "reconciliation_result", result.id)
    if workflow is not None:
        return workflow
    workflow = AppealWorkflow(
        case_type="reconciliation_result",
        case_id=result.id,
        restaurant_id=result.restaurant_id,
        claim_order_id=result.claim_order_id,
        reconciliation_result_id=result.id,
        status="appeal_needed",
        current_level=0,
        refusal_count=1,
        appeal_attempt_count=0,
        next_action_type="review_refusal",
        next_action_at=utc_now(),
        opened_by_user_id=user.id,
    )
    db.add(workflow)
    db.flush()
    add_workflow_audit(db, workflow, user, "appeal_workflow.created")
    return workflow


def recalculate_appeal_workflows(
    db: Session,
    user: User,
    *,
    restaurant_id: int | None = None,
) -> AppealRecalculateResult:
    if user.role == "staff":
        raise AppealWorkflowError("Staff cannot recalculate appeal workflows", 403)
    if restaurant_id is not None and not can_access_restaurant(db, user, restaurant_id):
        raise AppealWorkflowError("Restaurant access denied", 403)
    created = 0
    existing = 0
    errors: list[str] = []

    order_statement = select(ClaimOrder).where(ClaimOrder.status == "refused")
    dispute_statement = select(UberCustomerRefundDispute).where(UberCustomerRefundDispute.status == "refused")
    if restaurant_id is not None:
        order_statement = order_statement.where(ClaimOrder.restaurant_id == restaurant_id)
        dispute_statement = dispute_statement.where(UberCustomerRefundDispute.restaurant_id == restaurant_id)
    else:
        accessible_ids = get_accessible_restaurant_ids(db, user)
        if accessible_ids is not None:
            order_statement = order_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids or {-1}))
            dispute_statement = dispute_statement.where(UberCustomerRefundDispute.restaurant_id.in_(accessible_ids or {-1}))

    for order in db.scalars(order_statement).all():
        try:
            if get_workflow_by_case(db, "claim_order", order.id) is None:
                ensure_workflow_for_claim_order(db, order, user)
                created += 1
            else:
                existing += 1
        except Exception as exc:  # pragma: no cover - defensive audit path
            errors.append(f"order:{order.id}:{exc}")
    for dispute in db.scalars(dispute_statement).all():
        try:
            if get_workflow_by_case(db, "customer_refund_dispute", dispute.id) is None:
                ensure_workflow_for_customer_refund(db, dispute, user)
                created += 1
            else:
                existing += 1
        except Exception as exc:  # pragma: no cover - defensive audit path
            errors.append(f"customer_refund:{dispute.id}:{exc}")

    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=0,
        action="appeal_workflows.recalculate",
        user_id=user.id,
        new_value={"created_workflows": created, "existing_workflows": existing, "errors": errors},
    )
    return AppealRecalculateResult(created_workflows=created, existing_workflows=existing, errors=errors)


def create_refusal_analysis(
    db: Session,
    *,
    workflow: AppealWorkflow,
    user: User,
    refusal_source: str = "manual",
    review_id: int | None = None,
    refusal_reason: str | None = None,
    notes: str | None = None,
    inbound_message_id: int | None = None,
) -> RefusalAnalysis:
    if refusal_reason is None and notes is None:
        refusal_reason, notes, inbound_message_id, review_id, refusal_source = latest_refusal_context(db, workflow)
    result = analyze_refusal_text(refusal_reason, notes, refusal_count=max(workflow.refusal_count, 1))
    analysis = RefusalAnalysis(
        workflow_id=workflow.id,
        inbound_message_id=inbound_message_id,
        review_id=review_id,
        refusal_source=refusal_source,
        refusal_reason=result.reason,
        refusal_text_excerpt=excerpt(" ".join([refusal_reason or "", notes or ""]).strip()),
        recommended_next_action=result.recommended_next_action,
        required_evidence_types_json=result.required_evidence_types,
        confidence=result.confidence,
    )
    db.add(analysis)
    workflow.next_action_type = next_action_type_for_policy(result.recommended_next_action)
    workflow.next_action_at = utc_now()
    workflow.status = status_for_policy_action(result.recommended_next_action)
    workflow.updated_at = utc_now()
    db.flush()
    add_audit_log(
        db,
        entity_type="refusal_analysis",
        entity_id=analysis.id,
        action="refusal_analysis.created",
        user_id=user.id,
        new_value={
            "workflow_id": workflow.id,
            "recommended_next_action": analysis.recommended_next_action,
            "required_evidence_types": analysis.required_evidence_types_json,
        },
    )
    return analysis


def create_appeal_draft(
    db: Session,
    *,
    workflow: AppealWorkflow,
    user: User,
    appeal_type: str | None = None,
) -> AppealAttempt:
    ensure_can_manage_workflow(db, user, workflow)
    ensure_workflow_can_continue(workflow)
    enforce_cooldown(workflow)

    analysis = latest_analysis(db, workflow)
    if analysis is None:
        analysis = create_refusal_analysis(db, workflow=workflow, user=user)
    chosen_appeal_type = appeal_type or appeal_type_for_policy(analysis.recommended_next_action)
    enforce_no_duplicate_unprocessed_attempt(db, workflow, chosen_appeal_type)

    try:
        draft = create_appeal_email_draft(
            db,
            workflow=workflow,
            appeal_type=chosen_appeal_type,
            analysis=analysis,
            user_id=user.id,
        )
    except AppealDraftError as exc:
        raise AppealWorkflowError(exc.message, exc.status_code) from exc

    attempt = AppealAttempt(
        workflow_id=workflow.id,
        attempt_number=next_attempt_number(db, workflow),
        appeal_type=chosen_appeal_type,
        status="draft_created",
        based_on_refusal_message_id=analysis.inbound_message_id,
        email_draft_id=draft.id,
        argument_summary=analysis.recommended_next_action,
        new_evidence_summary=", ".join(analysis.required_evidence_types_json or []),
        created_by_user_id=user.id,
    )
    db.add(attempt)
    workflow.status = "gmail_draft_needed"
    workflow.next_action_type = "create_gmail_draft"
    workflow.next_action_at = utc_now()
    workflow.updated_at = utc_now()
    db.flush()
    add_audit_log(
        db,
        entity_type="appeal_attempt",
        entity_id=attempt.id,
        action="appeal_attempt.draft_created",
        user_id=user.id,
        new_value={"workflow_id": workflow.id, "email_draft_id": draft.id, "appeal_type": chosen_appeal_type},
    )
    return attempt


def create_appeal_gmail_draft(
    db: Session,
    *,
    workflow: AppealWorkflow,
    user: User,
    to_email: str | None = None,
) -> AppealAttempt:
    ensure_can_manage_workflow(db, user, workflow)
    ensure_workflow_can_continue(workflow)
    attempt = latest_attempt_with_draft(db, workflow)
    if attempt is None or attempt.email_draft is None:
        raise AppealWorkflowError("An internal appeal draft is required before creating a Gmail draft", 409)
    if attempt.provider_draft_id is not None:
        raise AppealWorkflowError("A Gmail draft is already linked to this appeal attempt", 409)

    settings = get_settings()
    if not settings.email_provider_enabled:
        raise AppealWorkflowError("email_provider_disabled", 503)
    gmail_account = db.scalar(
        select(EmailAccount.id)
        .where(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "gmail",
            EmailAccount.disconnected_at.is_(None),
        )
        .order_by(EmailAccount.id.desc())
    )
    if gmail_account is None:
        raise AppealWorkflowError("gmail_account_not_connected", 409)

    provider_draft = EmailProviderDraft(
        email_draft_id=attempt.email_draft.id,
        provider="gmail",
        provider_draft_id=f"tennet-appeal-{workflow.id}-{attempt.id}",
        provider_thread_id=None,
        to_email=to_email or settings.default_uber_eats_support_email,
        subject=attempt.email_draft.subject,
        status="provider_draft_created",
        created_by_user_id=user.id,
    )
    db.add(provider_draft)
    db.flush()

    attempt.provider_draft_id = provider_draft.id
    attempt.status = "gmail_draft_created"
    workflow.status = "appeal_needed"
    workflow.next_action_type = "send_manual_appeal"
    workflow.next_action_at = utc_now()
    workflow.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="appeal_attempt",
        entity_id=attempt.id,
        action="appeal_attempt.gmail_draft_created",
        user_id=user.id,
        new_value={"workflow_id": workflow.id, "provider_draft_id": provider_draft.id},
    )
    return attempt


def mark_appeal_sent(db: Session, *, workflow: AppealWorkflow, user: User) -> AppealAttempt:
    ensure_can_manage_workflow(db, user, workflow)
    ensure_workflow_can_continue(workflow)
    attempt = latest_attempt_with_draft(db, workflow)
    if attempt is None:
        raise AppealWorkflowError("No appeal attempt is ready to mark as sent", 409)
    if attempt.status == "sent":
        raise AppealWorkflowError("Appeal attempt is already marked as sent", 409)
    if attempt.provider_draft is not None:
        attempt.provider_draft.status = "sent"
        attempt.provider_draft.sent_by_user_id = user.id
        attempt.provider_draft.sent_at = utc_now()
    attempt.status = "sent"
    attempt.sent_by_user_id = user.id
    attempt.sent_at = utc_now()
    attempt.completed_at = utc_now()

    workflow.appeal_attempt_count += 1
    workflow.current_level = max(workflow.current_level, workflow.appeal_attempt_count)
    workflow.last_appeal_sent_at = utc_now()
    workflow.status = "appeal_sent"
    workflow.next_action_at = utc_now() + timedelta(days=get_settings().appeal_min_days_between_attempts)
    workflow.next_action_type = "review_refusal"
    if workflow.appeal_attempt_count >= get_settings().appeal_max_attempts_before_manual_review:
        workflow.status = "paused"
        workflow.next_action_type = "manual_review"
    elif workflow.appeal_attempt_count >= get_settings().appeal_max_attempts_before_escalation:
        workflow.status = "escalated"
        workflow.next_action_type = "escalation"
    workflow.updated_at = utc_now()

    add_audit_log(
        db,
        entity_type="appeal_attempt",
        entity_id=attempt.id,
        action="appeal_attempt.marked_sent",
        user_id=user.id,
        new_value={
            "workflow_id": workflow.id,
            "appeal_attempt_count": workflow.appeal_attempt_count,
            "next_action_type": workflow.next_action_type,
        },
    )
    return attempt


def pause_workflow(db: Session, *, workflow: AppealWorkflow, user: User, reason: str) -> AppealWorkflow:
    ensure_can_manage_workflow(db, user, workflow)
    previous_status = workflow.status
    workflow.status = "paused"
    workflow.next_action_type = "manual_review"
    workflow.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=workflow.id,
        action="appeal_workflow.paused",
        user_id=user.id,
        old_value={"status": previous_status},
        new_value={"status": workflow.status, "reason": reason},
    )
    return workflow


def manual_close_workflow(db: Session, *, workflow: AppealWorkflow, user: User, reason: str) -> AppealWorkflow:
    if user.role != "owner":
        raise AppealWorkflowError("Only owner can manually close an appeal workflow", 403)
    previous_status = workflow.status
    workflow.status = "manually_closed"
    workflow.next_action_type = None
    workflow.next_action_at = None
    workflow.manually_closed_by_user_id = user.id
    workflow.manually_closed_at = utc_now()
    workflow.manual_close_reason = reason
    workflow.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=workflow.id,
        action="appeal_workflow.manually_closed",
        user_id=user.id,
        old_value={"status": previous_status},
        new_value={"status": workflow.status, "reason": reason},
    )
    return workflow


def reopen_workflow(db: Session, *, workflow: AppealWorkflow, user: User) -> AppealWorkflow:
    if user.role != "owner":
        raise AppealWorkflowError("Only owner can reopen an appeal workflow", 403)
    previous_status = workflow.status
    workflow.status = "appeal_needed"
    workflow.next_action_type = "review_refusal"
    workflow.next_action_at = utc_now()
    workflow.manually_closed_by_user_id = None
    workflow.manually_closed_at = None
    workflow.manual_close_reason = None
    workflow.updated_at = utc_now()
    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=workflow.id,
        action="appeal_workflow.reopened",
        user_id=user.id,
        old_value={"status": previous_status},
        new_value={"status": workflow.status},
    )
    return workflow


def get_workflow_by_case(db: Session, case_type: str, case_id: int) -> AppealWorkflow | None:
    return db.scalar(
        select(AppealWorkflow).where(
            AppealWorkflow.case_type == case_type,
            AppealWorkflow.case_id == case_id,
        )
    )


def ensure_can_manage_workflow(db: Session, user: User, workflow: AppealWorkflow) -> None:
    if user.role == "staff":
        raise AppealWorkflowError("Staff cannot manage appeal workflows", 403)
    if not can_access_restaurant(db, user, workflow.restaurant_id):
        raise AppealWorkflowError("Restaurant access denied", 403)


def ensure_workflow_can_continue(workflow: AppealWorkflow) -> None:
    if workflow.status in TERMINAL_WORKFLOW_STATUSES:
        raise AppealWorkflowError(f"Appeal workflow cannot continue from status {workflow.status}", 409)


def enforce_cooldown(workflow: AppealWorkflow) -> None:
    if workflow.last_appeal_sent_at is None:
        return
    now = utc_now()
    last_sent_at = workflow.last_appeal_sent_at
    if last_sent_at.tzinfo is None:
        last_sent_at = last_sent_at.replace(tzinfo=now.tzinfo)
    if now < last_sent_at + timedelta(days=get_settings().appeal_min_days_between_attempts):
        raise AppealWorkflowError("Appeal cooldown is still active", 409)


def enforce_no_duplicate_unprocessed_attempt(db: Session, workflow: AppealWorkflow, appeal_type: str) -> None:
    if get_settings().appeal_allow_same_template_resend:
        return
    existing = db.scalar(
        select(AppealAttempt.id).where(
            AppealAttempt.workflow_id == workflow.id,
            AppealAttempt.appeal_type == appeal_type,
            AppealAttempt.status.in_(("planned", "draft_created", "gmail_draft_created")),
        )
    )
    if existing is not None:
        raise AppealWorkflowError("An unprocessed appeal draft of this type already exists", 409)


def latest_attempt_with_draft(db: Session, workflow: AppealWorkflow) -> AppealAttempt | None:
    return db.scalar(
        select(AppealAttempt)
        .where(
            AppealAttempt.workflow_id == workflow.id,
            AppealAttempt.email_draft_id.is_not(None),
            AppealAttempt.status.in_(("draft_created", "gmail_draft_created", "sent")),
        )
        .order_by(AppealAttempt.id.desc())
    )


def latest_analysis(db: Session, workflow: AppealWorkflow) -> RefusalAnalysis | None:
    return db.scalar(
        select(RefusalAnalysis)
        .where(RefusalAnalysis.workflow_id == workflow.id)
        .order_by(RefusalAnalysis.id.desc())
    )


def latest_refusal_context(
    db: Session,
    workflow: AppealWorkflow,
) -> tuple[str | None, str | None, int | None, int | None, str]:
    if workflow.case_type == "claim_order" and workflow.claim_order_id is not None:
        review = db.scalar(
            select(ClaimResponseReview)
            .where(
                ClaimResponseReview.order_id == workflow.claim_order_id,
                ClaimResponseReview.review_type == "refused",
            )
            .order_by(ClaimResponseReview.id.desc())
        )
        if review is not None:
            return review.refusal_reason, review.notes, review.inbound_message_id, review.id, "claim_response_review"
    if workflow.case_type == "customer_refund_dispute" and workflow.customer_refund_dispute_id is not None:
        review = db.scalar(
            select(CustomerRefundDisputeReview)
            .where(
                CustomerRefundDisputeReview.dispute_id == workflow.customer_refund_dispute_id,
                CustomerRefundDisputeReview.review_type == "refused",
            )
            .order_by(CustomerRefundDisputeReview.id.desc())
        )
        if review is not None:
            return review.refusal_reason, review.notes, review.inbound_message_id, review.id, "customer_refund_review"
    return "Refus a reexaminer", None, None, None, "manual"


def next_attempt_number(db: Session, workflow: AppealWorkflow) -> int:
    current = db.scalar(select(func.max(AppealAttempt.attempt_number)).where(AppealAttempt.workflow_id == workflow.id))
    return int(current or 0) + 1


def status_for_policy_action(action: str) -> str:
    if action == "provide_missing_evidence":
        return "evidence_needed"
    if action == "request_escalation":
        return "escalated"
    if action == "payment_verification":
        return "payment_to_verify"
    if action == "manual_review":
        return "paused"
    return "draft_needed"


def add_workflow_audit(db: Session, workflow: AppealWorkflow, user: User, action: str) -> None:
    add_audit_log(
        db,
        entity_type="appeal_workflow",
        entity_id=workflow.id,
        action=action,
        user_id=user.id,
        new_value={
            "case_type": workflow.case_type,
            "case_id": workflow.case_id,
            "status": workflow.status,
            "next_action_type": workflow.next_action_type,
        },
    )


def excerpt(value: str, length: int = 500) -> str | None:
    clean = value.strip()
    if not clean:
        return None
    return clean[:length]


def workflow_amount(workflow: AppealWorkflow) -> Decimal:
    if workflow.claim_order is not None:
        return Decimal(str(workflow.claim_order.order_amount or 0))
    if workflow.customer_refund_dispute is not None:
        return Decimal(str(workflow.customer_refund_dispute.customer_refund_amount or 0))
    if workflow.reconciliation_result is not None:
        return Decimal(str(workflow.reconciliation_result.missing_amount or workflow.reconciliation_result.order_amount or 0))
    return Decimal("0")


def workflow_currency(workflow: AppealWorkflow) -> str:
    if workflow.claim_order is not None:
        return workflow.claim_order.currency
    if workflow.customer_refund_dispute is not None:
        return workflow.customer_refund_dispute.currency
    if workflow.reconciliation_result is not None:
        return workflow.reconciliation_result.currency
    return "EUR"


def workflow_order_number(workflow: AppealWorkflow) -> str | None:
    if workflow.claim_order is not None:
        return workflow.claim_order.uber_order_number
    if workflow.customer_refund_dispute is not None:
        return workflow.customer_refund_dispute.display_id or workflow.customer_refund_dispute.uber_order_id
    if workflow.reconciliation_result is not None:
        return workflow.reconciliation_result.display_id or workflow.reconciliation_result.uber_order_id
    return None


def workflow_restaurant_name(db: Session, workflow: AppealWorkflow) -> str:
    if workflow.restaurant is not None:
        return workflow.restaurant.name
    name = db.scalar(select(Restaurant.name).where(Restaurant.id == workflow.restaurant_id))
    return name or f"#{workflow.restaurant_id}"


def evidence_tasks_for_workflow(db: Session, workflow: AppealWorkflow) -> list[EvidenceRequestTask]:
    statement = select(EvidenceRequestTask).where(EvidenceRequestTask.restaurant_id == workflow.restaurant_id)
    if workflow.claim_order_id is not None:
        statement = statement.where(EvidenceRequestTask.order_id == workflow.claim_order_id)
    elif workflow.customer_refund_dispute_id is not None:
        statement = statement.where(EvidenceRequestTask.customer_refund_dispute_id == workflow.customer_refund_dispute_id)
    elif workflow.reconciliation_result_id is not None:
        statement = statement.where(EvidenceRequestTask.reconciliation_result_id == workflow.reconciliation_result_id)
    else:
        return []
    return list(db.scalars(statement.order_by(EvidenceRequestTask.id.desc())).all())


def email_history_for_workflow(db: Session, workflow: AppealWorkflow) -> list[EmailDraft]:
    if workflow.claim_order_id is None:
        return []
    return list(
        db.scalars(
            select(EmailDraft)
            .where(EmailDraft.order_id == workflow.claim_order_id)
            .order_by(EmailDraft.id.desc())
        ).all()
    )


def accessible_workflow_statement(db: Session, user: User):
    statement = select(AppealWorkflow).order_by(AppealWorkflow.updated_at.desc(), AppealWorkflow.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, user)
    if accessible_ids is not None:
        return statement.where(AppealWorkflow.restaurant_id.in_(accessible_ids or {-1}))
    return statement


def active_workflows_for_cases(
    db: Session,
    cases: Iterable[tuple[str, int]],
) -> dict[tuple[str, int], AppealWorkflow]:
    case_pairs = list(cases)
    if not case_pairs:
        return {}
    workflows = db.scalars(
        select(AppealWorkflow).where(
            AppealWorkflow.status.in_(ACTIVE_WORKFLOW_STATUSES),
        )
    ).all()
    wanted = set(case_pairs)
    return {
        (workflow.case_type, workflow.case_id): workflow
        for workflow in workflows
        if (workflow.case_type, workflow.case_id) in wanted
    }
