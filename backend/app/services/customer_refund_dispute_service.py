from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant
from app.core.config import get_settings
from app.models import (
    ClaimOrder,
    CustomerRefundEvidenceRequirement,
    EmailDraft,
    EvidenceFile,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    UberOrderSnapshot,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.customer_refund_evidence_policy_service import evidence_policy_for_dispute
from app.services.email_draft_service import (
    build_order_identity_phrase,
    format_display_date,
    format_restaurant_signature,
    optional_line,
    restaurant_display_name,
)
from app.services.email_provider import EmailProvider, EmailProviderError

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "emails"

DISPUTE_DRAFT_TYPES = {
    "order_not_received": "customer_refund_order_not_received",
    "missing_item": "customer_refund_missing_item",
    "incorrect_item": "customer_refund_order_error_adjustment",
    "damaged_order": "customer_refund_generic",
    "quality_issue": "customer_refund_generic",
    "customer_refund": "customer_refund_generic",
    "order_error_adjustment": "customer_refund_order_error_adjustment",
    "chargeback": "customer_refund_generic",
    "unknown": "customer_refund_generic",
}


def ensure_evidence_requirements(
    db: Session,
    dispute: UberCustomerRefundDispute,
    required_evidence_types: tuple[str, ...],
) -> list[CustomerRefundEvidenceRequirement]:
    if dispute.id is None:
        db.flush()
    requirements: list[CustomerRefundEvidenceRequirement] = []
    existing = {
        requirement.required_evidence_type: requirement
        for requirement in db.scalars(
            select(CustomerRefundEvidenceRequirement).where(
                CustomerRefundEvidenceRequirement.dispute_id == dispute.id
            )
        ).all()
    }
    for evidence_type in required_evidence_types:
        requirement = existing.get(evidence_type)
        if requirement is None:
            requirement = CustomerRefundEvidenceRequirement(
                dispute_id=dispute.id,
                required_evidence_type=evidence_type,
                status="pending",
            )
            db.add(requirement)
            existing[evidence_type] = requirement
        requirements.append(requirement)
    db.flush()
    return requirements


def recalculate_dispute_evidence(
    db: Session,
    current_user: User,
    dispute: UberCustomerRefundDispute,
    *,
    create_tasks: bool,
) -> UberCustomerRefundDispute:
    ensure_can_access_restaurant(db, current_user, dispute.restaurant_id)
    policy = evidence_policy_for_dispute(dispute.dispute_type)
    requirements = ensure_evidence_requirements(db, dispute, policy.required)
    evidence_by_type = evidence_files_by_type(db, dispute.claim_order_id)
    uploaded_count = 0
    for requirement in requirements:
        matching_evidence = evidence_by_type.get(requirement.required_evidence_type)
        if matching_evidence is not None:
            requirement.status = "uploaded"
            requirement.evidence_file_id = matching_evidence.id
            uploaded_count += 1
        elif requirement.status == "uploaded" and requirement.evidence_file_id is not None:
            uploaded_count += 1

    previous_evidence_status = dispute.evidence_status
    if dispute.dispute_type == "unknown":
        dispute.evidence_status = "manual_review"
        dispute.status = "manual_review"
    elif not requirements:
        dispute.evidence_status = "not_required"
    elif uploaded_count == 0:
        dispute.evidence_status = "missing"
        if dispute.status in {"detected", "evidence_ready"}:
            dispute.status = "needs_evidence"
    elif uploaded_count < len(requirements):
        dispute.evidence_status = "partial"
        if dispute.status in {"detected", "evidence_ready"}:
            dispute.status = "needs_evidence"
    else:
        dispute.evidence_status = "complete"
        if dispute.status in {"detected", "needs_evidence", "manual_review"}:
            dispute.status = "evidence_ready"

    if create_tasks and dispute.claim_order_id is not None:
        for requirement in requirements:
            if requirement.status == "pending":
                create_evidence_task_for_requirement(db, current_user, dispute, requirement)

    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund_dispute.evidence_recalculated",
        user_id=current_user.id,
        old_value={"evidence_status": previous_evidence_status},
        new_value={"evidence_status": dispute.evidence_status, "status": dispute.status},
    )
    return dispute


def create_claim_order_from_dispute(
    db: Session,
    current_user: User,
    dispute: UberCustomerRefundDispute,
) -> ClaimOrder:
    ensure_can_access_restaurant(db, current_user, dispute.restaurant_id)
    if dispute.claim_order_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer refund dispute already has a ClaimOrder")
    order_number = dispute.uber_order_id or dispute.display_id or dispute.customer_refund_reference
    if not order_number:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uber order number is required")
    existing_order = db.scalar(
        select(ClaimOrder).where(
            ClaimOrder.restaurant_id == dispute.restaurant_id,
            ClaimOrder.uber_order_number == order_number,
        )
    )
    if existing_order is not None:
        dispute.claim_order_id = existing_order.id
        db.flush()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ClaimOrder already exists for this Uber order")

    initial_status = "manual_review" if dispute.dispute_type == "unknown" else "missing_evidence"
    if dispute.evidence_status in {"complete", "not_required"}:
        initial_status = "ready_to_send"

    snapshot = find_snapshot_for_dispute(db, dispute, order_number)
    order = ClaimOrder(
        restaurant_id=dispute.restaurant_id,
        internal_reference=f"CUST-REFUND-{dispute.id}",
        uber_order_number=order_number,
        customer_name=snapshot.customer_name if snapshot else None,
        order_date=dispute.order_date or (snapshot.placed_at.date() if snapshot and snapshot.placed_at else None),
        order_amount=dispute.customer_refund_amount,
        currency=dispute.currency,
        loss_type="customer_refund_dispute",
        status=initial_status,
        notes=build_claim_order_note(dispute),
    )
    db.add(order)
    db.flush()
    dispute.claim_order_id = order.id
    recalculate_dispute_evidence(db, current_user, dispute, create_tasks=True)
    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund_dispute.claim_order_created",
        user_id=current_user.id,
        new_value={"claim_order_id": order.id, "status": order.status},
    )
    db.commit()
    db.refresh(order)
    return order


def find_snapshot_for_dispute(
    db: Session,
    dispute: UberCustomerRefundDispute,
    order_number: str,
) -> UberOrderSnapshot | None:
    candidate_numbers = {order_number}
    candidate_numbers.update(value for value in (dispute.uber_order_id, dispute.display_id) if value)
    statement = select(UberOrderSnapshot).where(
        UberOrderSnapshot.restaurant_id == dispute.restaurant_id,
        UberOrderSnapshot.uber_order_id.in_(candidate_numbers),
    )
    if dispute.uber_store_id:
        statement = statement.where(UberOrderSnapshot.uber_store_id == dispute.uber_store_id)
    snapshot = db.scalar(statement.order_by(UberOrderSnapshot.id.desc()).limit(1))
    if snapshot is not None:
        return snapshot
    return db.scalar(
        select(UberOrderSnapshot)
        .where(
            UberOrderSnapshot.restaurant_id == dispute.restaurant_id,
            UberOrderSnapshot.display_id.in_(candidate_numbers),
        )
        .order_by(UberOrderSnapshot.id.desc())
        .limit(1)
    )


def create_customer_refund_draft(
    db: Session,
    current_user: User,
    dispute: UberCustomerRefundDispute,
) -> EmailDraft:
    ensure_can_access_restaurant(db, current_user, dispute.restaurant_id)
    if dispute.claim_order_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Create a ClaimOrder before drafting a dispute")
    if dispute.evidence_status not in {"complete", "not_required"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer refund dispute evidence is not complete")
    order = db.get(ClaimOrder, dispute.claim_order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Linked ClaimOrder not found")

    draft_type = DISPUTE_DRAFT_TYPES.get(dispute.dispute_type, "customer_refund_generic")
    draft = EmailDraft(
        order_id=order.id,
        draft_type=draft_type,
        subject=f"Contestation de remboursement de commande - {order.uber_order_number}",
        body=render_customer_refund_template(dispute, order, draft_type),
        status="created",
    )
    db.add(draft)
    db.flush()
    previous_status = dispute.status
    dispute.dispute_email_draft_id = draft.id
    dispute.status = "draft_created"
    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund_dispute.draft_created",
        user_id=current_user.id,
        old_value={"status": previous_status},
        new_value={"draft_id": draft.id, "draft_type": draft.draft_type, "status": dispute.status},
    )
    db.commit()
    db.refresh(draft)
    return draft


def create_customer_refund_gmail_draft(
    db: Session,
    current_user: User,
    dispute: UberCustomerRefundDispute,
    provider: EmailProvider,
):
    ensure_can_access_restaurant(db, current_user, dispute.restaurant_id)
    if dispute.dispute_email_draft_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Create an internal draft first")
    draft = db.get(EmailDraft, dispute.dispute_email_draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Internal draft not found")
    try:
        provider_draft = provider.create_draft(
            db,
            current_user,
            draft,
            to_email=get_settings().default_uber_eats_support_email,
            include_evidence=True,
        )
    except EmailProviderError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    previous_status = dispute.status
    dispute.provider_draft_id = provider_draft.id
    dispute.status = "gmail_draft_created"
    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund_dispute.gmail_draft_created",
        user_id=current_user.id,
        old_value={"status": previous_status},
        new_value={"provider_draft_id": provider_draft.id, "status": dispute.status},
    )
    db.commit()
    db.refresh(provider_draft)
    return provider_draft


def ignore_customer_refund_dispute(
    db: Session,
    current_user: User,
    dispute: UberCustomerRefundDispute,
    reason: str,
) -> UberCustomerRefundDispute:
    ensure_can_access_restaurant(db, current_user, dispute.restaurant_id)
    previous_status = dispute.status
    dispute.status = "ignored"
    dispute.ignored_at = utc_now()
    dispute.ignored_by_user_id = current_user.id
    dispute.ignore_reason = reason
    add_audit_log(
        db,
        entity_type="uber_customer_refund_dispute",
        entity_id=dispute.id,
        action="customer_refund_dispute.ignored",
        user_id=current_user.id,
        old_value={"status": previous_status},
        new_value={"status": dispute.status, "reason": reason},
    )
    db.commit()
    db.refresh(dispute)
    return dispute


def create_claim_orders_bulk(
    db: Session,
    current_user: User,
    dispute_ids: list[int],
) -> dict[str, object]:
    created_ids: list[int] = []
    errors: list[str] = []
    skipped_count = 0
    for dispute_id in dispute_ids:
        dispute = db.get(UberCustomerRefundDispute, dispute_id)
        if dispute is None:
            skipped_count += 1
            errors.append(f"dispute {dispute_id}: not found")
            continue
        try:
            order = create_claim_order_from_dispute(db, current_user, dispute)
            created_ids.append(order.id)
        except HTTPException as exc:
            skipped_count += 1
            errors.append(f"dispute {dispute_id}: {exc.detail}")
    return {"created_count": len(created_ids), "skipped_count": skipped_count, "errors": errors, "created_ids": created_ids}


def create_drafts_bulk(
    db: Session,
    current_user: User,
    dispute_ids: list[int],
) -> dict[str, object]:
    created_ids: list[int] = []
    errors: list[str] = []
    skipped_count = 0
    for dispute_id in dispute_ids:
        dispute = db.get(UberCustomerRefundDispute, dispute_id)
        if dispute is None:
            skipped_count += 1
            errors.append(f"dispute {dispute_id}: not found")
            continue
        try:
            draft = create_customer_refund_draft(db, current_user, dispute)
            created_ids.append(draft.id)
        except HTTPException as exc:
            skipped_count += 1
            errors.append(f"dispute {dispute_id}: {exc.detail}")
    return {"created_count": len(created_ids), "skipped_count": skipped_count, "errors": errors, "created_ids": created_ids}


def create_evidence_task_for_requirement(
    db: Session,
    current_user: User,
    dispute: UberCustomerRefundDispute,
    requirement: CustomerRefundEvidenceRequirement,
) -> EvidenceRequestTask | None:
    if dispute.claim_order_id is None:
        return None
    existing = db.scalar(
        select(EvidenceRequestTask).where(
            EvidenceRequestTask.order_id == dispute.claim_order_id,
            EvidenceRequestTask.customer_refund_dispute_id == dispute.id,
            EvidenceRequestTask.required_evidence_type == requirement.required_evidence_type,
            EvidenceRequestTask.status.in_(("pending", "uploaded")),
        )
    )
    if existing is not None:
        return existing
    task = EvidenceRequestTask(
        order_id=dispute.claim_order_id,
        restaurant_id=dispute.restaurant_id,
        customer_refund_dispute_id=dispute.id,
        task_type=task_type_for_evidence(requirement.required_evidence_type),
        required_evidence_type=requirement.required_evidence_type,
        status="pending",
        priority="high" if dispute.customer_refund_amount >= 50 else "normal",
        title=customer_refund_task_title(dispute, requirement.required_evidence_type),
        description=customer_refund_task_description(dispute, requirement.required_evidence_type),
        reason=f"customer_refund_{dispute.reason}",
        created_by_user_id=current_user.id,
    )
    db.add(task)
    db.flush()
    add_audit_log(
        db,
        entity_type="evidence_request_task",
        entity_id=task.id,
        action="customer_refund_dispute.evidence_task_created",
        user_id=current_user.id,
        new_value={
            "dispute_id": dispute.id,
            "required_evidence_type": requirement.required_evidence_type,
        },
    )
    return task


def customer_refund_task_title(dispute: UberCustomerRefundDispute, evidence_type: str) -> str:
    order_label = dispute.display_id or dispute.uber_order_id or dispute.customer_refund_reference or f"deduction #{dispute.id}"
    return f"Remboursement - {title_for_evidence(evidence_type)} - commande {order_label}"[:255]


def customer_refund_task_description(dispute: UberCustomerRefundDispute, evidence_type: str) -> str:
    order_label = dispute.display_id or dispute.uber_order_id or dispute.customer_refund_reference or "commande a verifier"
    return (
        f"Preuve requise pour contester une deduction Uber Eats. Type: {dispute.dispute_type}. "
        f"Commande: {order_label}. Montant deduit: {dispute.customer_refund_amount} {dispute.currency}. "
        f"Preuve attendue: {title_for_evidence(evidence_type)}. "
        "Une seule photo suffit si elle montre le ticket de caisse agrafe ou pose sur la commande du client, "
        "avec restaurant et numero de commande lisibles. Importe ensuite toutes les preuves en masse dans Smart Import."
    )


def sync_requirement_from_evidence_task(
    db: Session,
    task: EvidenceRequestTask,
    evidence_file: EvidenceFile,
    user_id: int | None,
) -> None:
    if task.customer_refund_dispute_id is None:
        return
    dispute = db.get(UberCustomerRefundDispute, task.customer_refund_dispute_id)
    if dispute is None:
        return
    requirement = db.scalar(
        select(CustomerRefundEvidenceRequirement).where(
            CustomerRefundEvidenceRequirement.dispute_id == dispute.id,
            CustomerRefundEvidenceRequirement.required_evidence_type == evidence_file.evidence_type,
        )
    )
    if requirement is not None:
        requirement.status = "uploaded"
        requirement.evidence_file_id = evidence_file.id
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None:
            recalculate_dispute_evidence(db, user, dispute, create_tasks=False)
            return
    refresh_dispute_evidence_status(dispute)


def evidence_files_by_type(db: Session, claim_order_id: int | None) -> dict[str, EvidenceFile]:
    if claim_order_id is None:
        return {}
    rows = db.scalars(
        select(EvidenceFile).where(
            EvidenceFile.order_id == claim_order_id,
            EvidenceFile.deleted_at.is_(None),
        )
    ).all()
    return {evidence.evidence_type: evidence for evidence in rows}


def refresh_dispute_evidence_status(dispute: UberCustomerRefundDispute) -> None:
    requirements = list(dispute.evidence_requirements)
    if dispute.dispute_type == "unknown":
        dispute.evidence_status = "manual_review"
        dispute.status = "manual_review"
        return
    if not requirements:
        dispute.evidence_status = "not_required"
        return
    uploaded_count = len([item for item in requirements if item.status == "uploaded"])
    if uploaded_count == 0:
        dispute.evidence_status = "missing"
        if dispute.status in {"detected", "evidence_ready"}:
            dispute.status = "needs_evidence"
    elif uploaded_count < len(requirements):
        dispute.evidence_status = "partial"
        if dispute.status in {"detected", "evidence_ready"}:
            dispute.status = "needs_evidence"
    else:
        dispute.evidence_status = "complete"
        if dispute.status in {"detected", "needs_evidence", "manual_review"}:
            dispute.status = "evidence_ready"


def build_claim_order_note(dispute: UberCustomerRefundDispute) -> str:
    return (
        f"Cree depuis deduction Uber #{dispute.id}. "
        f"Type: {dispute.dispute_type}. Raison: {dispute.reason}. "
        f"Montant deduit: {dispute.customer_refund_amount} {dispute.currency}. "
        f"Transaction liee: {dispute.financial_transaction_id}. "
        f"Preuves requises: {dispute.evidence_status}."
    )


def render_customer_refund_template(dispute: UberCustomerRefundDispute, order: ClaimOrder, draft_type: str) -> str:
    template_path = TEMPLATE_DIR / f"{draft_type}.txt"
    if not template_path.exists():
        template_path = TEMPLATE_DIR / "customer_refund_generic.txt"
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        uber_order_number=order.uber_order_number,
        order_identity_phrase=build_order_identity_phrase(order),
        restaurant_name=restaurant_display_name(order.restaurant),
        customer_name_line=optional_line("Client", order.customer_name),
        order_date_line=optional_line("Date de commande", format_display_date(order.order_date)),
        customer_refund_amount=f"{dispute.customer_refund_amount:.2f}",
        currency=dispute.currency,
        dispute_type=dispute.dispute_type,
        reason=dispute.reason,
        evidence_list=format_dispute_evidence(order),
        signature=format_restaurant_signature(order.restaurant),
    )


def format_dispute_evidence(order: ClaimOrder) -> str:
    if not order.evidence_files:
        return "- Aucune piece jointe pour le moment"
    return "\n".join(
        f"- {evidence.original_filename}"
        for evidence in sorted(order.evidence_files, key=lambda item: item.id)
    )


def task_type_for_evidence(evidence_type: str) -> str:
    if evidence_type == "receipt":
        return "missing_receipt"
    if evidence_type == "preparation_proof":
        return "missing_preparation_proof"
    if evidence_type == "waste_photo":
        return "missing_waste_photo"
    if evidence_type == "uber_screenshot":
        return "missing_uber_screenshot"
    return "evidence_review"


def title_for_evidence(evidence_type: str) -> str:
    labels = {
        "receipt": "Ticket agrafe sur commande requis",
        "delivery_proof": "Preuve de livraison requise",
        "preparation_proof": "Preuve de preparation requise",
        "packaging_photo": "Photo du packaging requise",
        "sealed_bag_photo": "Photo du sac scelle requise",
        "uber_screenshot": "Capture Uber requise",
        "order_details_screenshot": "Details commande requis",
    }
    return labels.get(evidence_type, "Preuve complementaire requise")
