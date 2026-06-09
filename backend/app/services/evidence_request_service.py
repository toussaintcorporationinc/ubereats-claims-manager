from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import (
    ClaimOrder,
    EvidenceFile,
    EvidenceRequestTask,
    EvidenceUploadLink,
    UberReconciliationResult,
    User,
)
from app.models.domain import EVIDENCE_TYPES, utc_now
from app.schemas.domain import ClaimValidationResponse
from app.services.audit import add_audit_log
from app.services.claim_validation_service import FINAL_CLAIM_STATUSES, get_claim_validation_gaps, validate_claim_order
from app.services.file_storage_service import FileStorageError, store_evidence_upload

ACTIVE_TASK_STATUSES = {"pending", "uploaded"}
TASK_SOURCE_STATUSES = {"draft", "missing_evidence", "sent", "waiting_uber_response", "response_received", "manual_review"}
RECONCILIATION_EVIDENCE_STATUSES = {"not_compensated", "partially_compensated", "needs_evidence"}


@dataclass(frozen=True)
class EvidenceTaskUploadResult:
    task: EvidenceRequestTask
    evidence_file: EvidenceFile
    validation: ClaimValidationResponse


@dataclass(frozen=True)
class EvidenceTaskSpec:
    evidence_type: str
    task_type: str
    title: str
    description: str
    reason: str
    priority: str
    reconciliation_result_id: int | None


def recalculate_evidence_tasks(
    db: Session,
    current_user: User,
    *,
    restaurant_id: int | None = None,
    order_id: int | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    statement = select(ClaimOrder).order_by(ClaimOrder.id)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if order_id is not None:
        order = db.get(ClaimOrder, order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if not can_access_restaurant(db, current_user, order.restaurant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")
        if restaurant_id is not None and restaurant_id != order.restaurant_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="order_id does not match restaurant_id")
        statement = statement.where(ClaimOrder.id == order_id)
    elif restaurant_id is not None:
        if not can_access_restaurant(db, current_user, restaurant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant access denied")
        statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return {
                "created_tasks": 0,
                "existing_tasks": 0,
                "completed_tasks": 0,
                "skipped_orders": 0,
                "errors": [],
            }
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))

    created_tasks = 0
    existing_tasks = 0
    completed_tasks = 0
    skipped_orders = 0
    errors: list[str] = []

    orders = db.scalars(statement).all()
    reconciliation_by_order = get_reconciliation_results_by_order(db, [order.id for order in orders])
    for order in orders:
        try:
            if order.status in FINAL_CLAIM_STATUSES or order.status not in TASK_SOURCE_STATUSES:
                skipped_orders += 1
                continue

            missing_items, _ = get_claim_validation_gaps(db, order)
            task_specs = build_task_specs(order, missing_items, reconciliation_by_order.get(order.id))
            if not task_specs:
                completed_tasks += complete_satisfied_tasks(db, order, current_user, dry_run=dry_run)
                skipped_orders += 1
                continue

            for task_spec in task_specs:
                active_task = get_active_task(db, order.id, task_spec.evidence_type)
                if active_task is not None:
                    existing_tasks += 1
                    continue
                if dry_run:
                    created_tasks += 1
                    continue
                task = EvidenceRequestTask(
                    order_id=order.id,
                    restaurant_id=order.restaurant_id,
                    reconciliation_result_id=task_spec.reconciliation_result_id,
                    task_type=task_spec.task_type,
                    required_evidence_type=task_spec.evidence_type,
                    status="pending",
                    priority=task_spec.priority,
                    title=task_spec.title,
                    description=task_spec.description,
                    due_at=order.next_action_at,
                    reason=task_spec.reason,
                    created_by_user_id=current_user.id,
                )
                db.add(task)
                db.flush()
                created_tasks += 1
                add_audit_log(
                    db,
                    entity_type="evidence_request_task",
                    entity_id=task.id,
                    action="evidence_task.created",
                    user_id=current_user.id,
                    new_value={
                        "order_id": order.id,
                        "restaurant_id": order.restaurant_id,
                        "task_type": task_spec.task_type,
                        "required_evidence_type": task_spec.evidence_type,
                        "priority": task_spec.priority,
                        "reason": task_spec.reason,
                        "reconciliation_result_id": task_spec.reconciliation_result_id,
                    },
                )
        except Exception as exc:  # pragma: no cover - defensive audit path
            errors.append(f"order {order.id}: {exc}")

    if not dry_run:
        add_audit_log(
            db,
            entity_type="evidence_request_task",
            entity_id=0,
            action="evidence_task.recalculate",
            user_id=current_user.id,
            new_value={
                "restaurant_id": restaurant_id,
                "order_id": order_id,
                "created_tasks": created_tasks,
                "existing_tasks": existing_tasks,
                "completed_tasks": completed_tasks,
                "skipped_orders": skipped_orders,
                "errors": errors,
            },
        )

    return {
        "created_tasks": created_tasks,
        "existing_tasks": existing_tasks,
        "completed_tasks": completed_tasks,
        "skipped_orders": skipped_orders,
        "errors": errors,
    }


def upload_evidence_for_task(
    db: Session,
    task: EvidenceRequestTask,
    upload_file: UploadFile,
    *,
    user_id: int | None,
) -> EvidenceTaskUploadResult:
    if task.status in {"completed", "skipped", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Evidence task is not uploadable")
    if task.required_evidence_type not in EVIDENCE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid evidence task type")

    try:
        stored_file = store_evidence_upload(task.order, upload_file)
    except FileStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    evidence_file = EvidenceFile(
        order_id=task.order_id,
        evidence_type=task.required_evidence_type,
        original_filename=stored_file.original_filename,
        storage_path=stored_file.storage_path,
        storage_backend=stored_file.storage_backend,
        mime_type=stored_file.mime_type,
        file_size=stored_file.file_size,
        checksum_sha256=stored_file.checksum_sha256,
        uploaded_by_user_id=user_id,
    )
    db.add(evidence_file)
    db.flush()
    if task.customer_refund_dispute_id is not None:
        from app.services.customer_refund_dispute_service import sync_requirement_from_evidence_task

        sync_requirement_from_evidence_task(db, task, evidence_file, user_id)

    previous_status = task.status
    now = utc_now()
    task.status = "completed"
    task.completed_at = now
    task.completed_by_user_id = user_id
    task.last_upload_evidence_id = evidence_file.id

    add_audit_log(
        db,
        entity_type="evidence_file",
        entity_id=evidence_file.id,
        action="evidence_file.uploaded_from_task",
        user_id=user_id,
        new_value={
            "task_id": task.id,
            "order_id": task.order_id,
            "evidence_type": evidence_file.evidence_type,
            "original_filename": evidence_file.original_filename,
            "checksum_sha256": evidence_file.checksum_sha256,
        },
    )
    add_audit_log(
        db,
        entity_type="evidence_request_task",
        entity_id=task.id,
        action="evidence_task.completed_by_upload",
        user_id=user_id,
        old_value={"status": previous_status},
        new_value={"status": task.status, "evidence_file_id": evidence_file.id},
    )

    validation = validate_claim_order(db, task.order_id, user_id=user_id)
    return EvidenceTaskUploadResult(task=task, evidence_file=evidence_file, validation=validation)


def skip_evidence_task(db: Session, task: EvidenceRequestTask, current_user: User, skip_reason: str) -> EvidenceRequestTask:
    if task.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Completed evidence task cannot be skipped")
    previous_status = task.status
    task.status = "skipped"
    task.skipped_by_user_id = current_user.id
    task.skipped_at = utc_now()
    task.skip_reason = skip_reason
    add_audit_log(
        db,
        entity_type="evidence_request_task",
        entity_id=task.id,
        action="evidence_task.skipped",
        user_id=current_user.id,
        old_value={"status": previous_status},
        new_value={"status": task.status, "skip_reason": skip_reason},
    )
    return task


def complete_evidence_task(db: Session, task: EvidenceRequestTask, current_user: User) -> EvidenceRequestTask:
    if task.status in {"skipped", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skipped or cancelled evidence task cannot be completed")
    previous_status = task.status
    task.status = "completed"
    task.completed_by_user_id = current_user.id
    task.completed_at = utc_now()
    add_audit_log(
        db,
        entity_type="evidence_request_task",
        entity_id=task.id,
        action="evidence_task.completed",
        user_id=current_user.id,
        old_value={"status": previous_status},
        new_value={"status": task.status},
    )
    return task


def create_upload_link(
    db: Session,
    task: EvidenceRequestTask,
    current_user: User,
    *,
    expires_in_hours: int | None = None,
    max_uses: int | None = None,
) -> tuple[EvidenceUploadLink, str, str]:
    if task.status not in ACTIVE_TASK_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Upload link can only be created for active tasks")

    settings = get_settings()
    token = token_urlsafe(32)
    token_hash = hash_upload_token(token)
    expiry_hours = expires_in_hours or settings.evidence_upload_link_expiry_hours
    link_max_uses = max_uses or settings.evidence_upload_link_max_uses
    upload_link = EvidenceUploadLink(
        task_id=task.id,
        token_hash=token_hash,
        created_by_user_id=current_user.id,
        expires_at=utc_now() + timedelta(hours=expiry_hours),
        max_uses=link_max_uses,
        use_count=0,
    )
    db.add(upload_link)
    db.flush()
    add_audit_log(
        db,
        entity_type="evidence_upload_link",
        entity_id=upload_link.id,
        action="evidence_upload_link.created",
        user_id=current_user.id,
        new_value={
            "task_id": task.id,
            "expires_at": upload_link.expires_at,
            "max_uses": upload_link.max_uses,
        },
    )
    frontend_url = (settings.frontend_url or "http://localhost:3000").rstrip("/")
    return upload_link, token, f"{frontend_url}/evidence-upload/{token}"


def revoke_upload_link(db: Session, upload_link: EvidenceUploadLink, current_user: User) -> EvidenceUploadLink:
    if upload_link.revoked_at is None:
        upload_link.revoked_at = utc_now()
        add_audit_log(
            db,
            entity_type="evidence_upload_link",
            entity_id=upload_link.id,
            action="evidence_upload_link.revoked",
            user_id=current_user.id,
            new_value={"task_id": upload_link.task_id},
        )
    return upload_link


def get_valid_upload_link_by_token(db: Session, token: str) -> EvidenceUploadLink:
    token_hash = hash_upload_token(token)
    upload_link = db.scalar(select(EvidenceUploadLink).where(EvidenceUploadLink.token_hash == token_hash))
    if upload_link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence upload link not found")
    if upload_link.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Evidence upload link has been revoked")
    now = utc_now()
    expires_at = upload_link.expires_at
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    if expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Evidence upload link has expired")
    if upload_link.use_count >= upload_link.max_uses:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Evidence upload link has already been used")
    if upload_link.task.status not in ACTIVE_TASK_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Evidence task is not uploadable")
    return upload_link


def upload_evidence_with_link(
    db: Session,
    upload_link: EvidenceUploadLink,
    upload_file: UploadFile,
) -> EvidenceTaskUploadResult:
    result = upload_evidence_for_task(db, upload_link.task, upload_file, user_id=None)
    upload_link.use_count += 1
    upload_link.last_used_at = utc_now()
    add_audit_log(
        db,
        entity_type="evidence_upload_link",
        entity_id=upload_link.id,
        action="evidence_upload_link.used",
        new_value={"task_id": upload_link.task_id, "use_count": upload_link.use_count},
    )
    return result


def hash_upload_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def get_active_task(db: Session, order_id: int, evidence_type: str) -> EvidenceRequestTask | None:
    return db.scalar(
        select(EvidenceRequestTask).where(
            EvidenceRequestTask.order_id == order_id,
            EvidenceRequestTask.required_evidence_type == evidence_type,
            EvidenceRequestTask.status.in_(ACTIVE_TASK_STATUSES),
        )
    )


def build_task_specs(
    order: ClaimOrder,
    missing_items: list[str],
    reconciliation_result: UberReconciliationResult | None,
) -> list[EvidenceTaskSpec]:
    specs: list[EvidenceTaskSpec] = []
    priority = get_task_priority(order, reconciliation_result)
    reconciliation_result_id = reconciliation_result.id if reconciliation_result else None
    if "cancellation_proof" in missing_items:
        specs.append(
            EvidenceTaskSpec(
                evidence_type="cancellation_proof",
                task_type="missing_cancellation_proof",
                title="Preuve d'annulation requise",
                description="Ajoutez une capture ou un document montrant l'annulation Uber Eats.",
                reason="missing_cancellation_proof",
                priority=priority,
                reconciliation_result_id=reconciliation_result_id,
            )
        )
    if "preparation_or_waste_proof" in missing_items:
        evidence_type = choose_preparation_or_waste_type(order)
        task_type = "missing_waste_photo" if evidence_type == "waste_photo" else "missing_preparation_proof"
        title = "Photo de gaspillage requise" if evidence_type == "waste_photo" else "Preuve de preparation requise"
        description = (
            "Ajoutez une photo de gaspillage ou de commande jetee."
            if evidence_type == "waste_photo"
            else "Ajoutez une preuve montrant que la commande etait preparee avant l'annulation."
        )
        specs.append(
            EvidenceTaskSpec(
                evidence_type=evidence_type,
                task_type=task_type,
                title=title,
                description=description,
                reason="missing_preparation_or_waste_proof",
                priority=priority,
                reconciliation_result_id=reconciliation_result_id,
            )
        )
    return specs


def choose_preparation_or_waste_type(order: ClaimOrder) -> str:
    loss_type = (order.loss_type or "").strip().lower()
    if "waste" in loss_type or "gaspillage" in loss_type:
        return "waste_photo"
    return "preparation_proof"


def get_task_priority(order: ClaimOrder, reconciliation_result: UberReconciliationResult | None) -> str:
    settings = get_settings()
    amount = reconciliation_result.missing_amount if reconciliation_result and reconciliation_result.missing_amount else order.order_amount
    if amount is None:
        return "normal"
    decimal_amount = Decimal(str(amount))
    if decimal_amount >= Decimal(str(settings.evidence_task_urgent_amount)):
        return "urgent"
    if decimal_amount >= Decimal(str(settings.evidence_task_high_amount)):
        return "high"
    return "normal"


def get_reconciliation_results_by_order(db: Session, order_ids: list[int]) -> dict[int, UberReconciliationResult]:
    if not order_ids:
        return {}
    rows = db.scalars(
        select(UberReconciliationResult).where(
            UberReconciliationResult.claim_order_id.in_(order_ids),
            UberReconciliationResult.evidence_required.is_(True),
            UberReconciliationResult.status.in_(RECONCILIATION_EVIDENCE_STATUSES),
        )
    ).all()
    return {result.claim_order_id: result for result in rows if result.claim_order_id is not None}


def complete_satisfied_tasks(db: Session, order: ClaimOrder, current_user: User, *, dry_run: bool) -> int:
    completed = 0
    evidence_types = {
        evidence.evidence_type
        for evidence in order.evidence_files
        if getattr(evidence, "deleted_at", None) is None
    }
    active_tasks = db.scalars(
        select(EvidenceRequestTask).where(
            EvidenceRequestTask.order_id == order.id,
            EvidenceRequestTask.status.in_(ACTIVE_TASK_STATUSES),
        )
    ).all()
    for task in active_tasks:
        if task.required_evidence_type in evidence_types:
            completed += 1
            if not dry_run:
                previous_status = task.status
                task.status = "completed"
                task.completed_at = utc_now()
                task.completed_by_user_id = current_user.id
                add_audit_log(
                    db,
                    entity_type="evidence_request_task",
                    entity_id=task.id,
                    action="evidence_task.completed_by_recalculate",
                    user_id=current_user.id,
                    old_value={"status": previous_status},
                    new_value={"status": task.status},
                )
    return completed
