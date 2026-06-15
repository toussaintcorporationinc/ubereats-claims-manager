from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.core.auth import ensure_can_access_order, ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.models import ClaimOrder, EvidenceRequestTask, EvidenceUploadLink, UberOrderSnapshot, User
from app.schemas.domain import (
    EvidenceRequestPriority,
    EvidencePrintTicketCreateRequest,
    EvidencePrintTicketResponse,
    EvidenceRequestRecalculateRequest,
    EvidenceRequestRecalculateResponse,
    EvidenceRequestSkipRequest,
    EvidenceRequestTaskRead,
    EvidenceRequestTaskStatus,
    EvidenceRequestTasksResponse,
    EvidenceRequestTaskSummary,
    EvidenceTaskUploadResponse,
    EvidenceType,
    EvidenceUploadLinkCreateRequest,
    EvidenceUploadLinkCreateResponse,
    EvidenceUploadLinkRead,
    PublicEvidenceUploadLinkRead,
)
from app.services.evidence_request_service import (
    complete_evidence_task,
    create_upload_link,
    get_valid_upload_link_by_token,
    recalculate_evidence_tasks,
    revoke_upload_link,
    skip_evidence_task,
    upload_evidence_for_task,
    upload_evidence_with_link,
)
from app.services.evidence_print_ticket_service import create_print_ticket

router = APIRouter(tags=["evidence-tasks"])


@router.post("/v1/evidence-tasks/recalculate", response_model=EvidenceRequestRecalculateResponse)
def recalculate_tasks(
    payload: EvidenceRequestRecalculateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    result = recalculate_evidence_tasks(
        db,
        current_user,
        restaurant_id=payload.restaurant_id,
        order_id=payload.order_id,
        dry_run=payload.dry_run,
    )
    db.commit()
    return result


@router.get("/v1/evidence-tasks", response_model=EvidenceRequestTasksResponse)
def list_tasks(
    restaurant_id: int | None = Query(default=None),
    status_filter: EvidenceRequestTaskStatus | None = Query(default=None, alias="status"),
    required_evidence_type: EvidenceType | None = Query(default=None),
    priority: EvidenceRequestPriority | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceRequestTasksResponse:
    statement = select(EvidenceRequestTask).join(ClaimOrder).order_by(EvidenceRequestTask.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(ClaimOrder.restaurant_id == restaurant_id)
    elif accessible_ids is not None:
        if not accessible_ids:
            return EvidenceRequestTasksResponse(tasks=[], limit=limit, offset=offset)
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
    if status_filter:
        statement = statement.where(EvidenceRequestTask.status == status_filter)
    if required_evidence_type:
        statement = statement.where(EvidenceRequestTask.required_evidence_type == required_evidence_type)
    if priority:
        statement = statement.where(EvidenceRequestTask.priority == priority)
    if assigned_to_me:
        statement = statement.where(EvidenceRequestTask.assigned_to_user_id == current_user.id)

    tasks = db.scalars(statement.offset(offset).limit(limit)).all()
    return EvidenceRequestTasksResponse(tasks=[build_task_summary(task) for task in tasks], limit=limit, offset=offset)


@router.get("/v1/evidence-tasks/{task_id}", response_model=EvidenceRequestTaskRead)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceRequestTask:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    return task


@router.post("/v1/evidence-tasks/{task_id}/upload", response_model=EvidenceTaskUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_task_evidence(
    task_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceTaskUploadResponse:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    result = upload_evidence_for_task(db, task, file, user_id=current_user.id)
    db.commit()
    db.refresh(result.task)
    db.refresh(result.evidence_file)
    return EvidenceTaskUploadResponse(task=result.task, evidence_file=result.evidence_file, validation=result.validation)


@router.post("/v1/evidence-tasks/{task_id}/skip", response_model=EvidenceRequestTaskRead)
def skip_task(
    task_id: int,
    payload: EvidenceRequestSkipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceRequestTask:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    task = skip_evidence_task(db, task, current_user, payload.skip_reason)
    db.commit()
    db.refresh(task)
    return task


@router.post("/v1/evidence-tasks/{task_id}/complete", response_model=EvidenceRequestTaskRead)
def complete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceRequestTask:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    task = complete_evidence_task(db, task, current_user)
    db.commit()
    db.refresh(task)
    return task


@router.post("/v1/evidence-tasks/{task_id}/upload-link", response_model=EvidenceUploadLinkCreateResponse, status_code=status.HTTP_201_CREATED)
def create_task_upload_link(
    task_id: int,
    payload: EvidenceUploadLinkCreateRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceUploadLinkCreateResponse:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    payload = payload or EvidenceUploadLinkCreateRequest()
    upload_link, token, upload_url = create_upload_link(
        db,
        task,
        current_user,
        expires_in_hours=payload.expires_in_hours,
        max_uses=payload.max_uses,
    )
    db.commit()
    db.refresh(upload_link)
    link_read = EvidenceUploadLinkRead.model_validate(upload_link)
    return EvidenceUploadLinkCreateResponse(**link_read.model_dump(), token=token, upload_url=upload_url)


@router.post("/v1/evidence-tasks/{task_id}/print-ticket", response_model=EvidencePrintTicketResponse, status_code=status.HTTP_201_CREATED)
def create_task_print_ticket(
    task_id: int,
    payload: EvidencePrintTicketCreateRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    task = get_task_or_404(task_id, db)
    ensure_can_access_order(db, current_user, task.order)
    payload = payload or EvidencePrintTicketCreateRequest()
    ticket = create_print_ticket(
        db,
        task,
        current_user,
        expires_in_hours=payload.expires_in_hours,
        max_uses=payload.max_uses,
    )
    db.commit()
    db.refresh(ticket.upload_link)
    return ticket.as_response_dict()


@router.get("/v1/evidence-upload-links/{token}", response_model=PublicEvidenceUploadLinkRead)
def get_public_upload_link(
    token: str,
    db: Session = Depends(get_db),
) -> PublicEvidenceUploadLinkRead:
    upload_link = get_valid_upload_link_by_token(db, token)
    db.commit()
    return build_public_link_response(upload_link)


@router.post("/v1/evidence-upload-links/{token}/upload", response_model=EvidenceTaskUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_public_link_evidence(
    token: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> EvidenceTaskUploadResponse:
    upload_link = get_valid_upload_link_by_token(db, token)
    result = upload_evidence_with_link(db, upload_link, file)
    db.commit()
    db.refresh(result.task)
    db.refresh(result.evidence_file)
    return EvidenceTaskUploadResponse(task=result.task, evidence_file=result.evidence_file, validation=result.validation)


@router.post("/v1/evidence-upload-links/{link_id}/revoke", response_model=EvidenceUploadLinkRead)
def revoke_public_upload_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> EvidenceUploadLink:
    upload_link = db.get(EvidenceUploadLink, link_id)
    if upload_link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence upload link not found")
    ensure_can_access_order(db, current_user, upload_link.task.order)
    upload_link = revoke_upload_link(db, upload_link, current_user)
    db.commit()
    db.refresh(upload_link)
    return upload_link


def get_task_or_404(task_id: int, db: Session) -> EvidenceRequestTask:
    task = db.get(EvidenceRequestTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence task not found")
    return task


def build_task_summary(task: EvidenceRequestTask) -> EvidenceRequestTaskSummary:
    order = task.order
    related_snapshot = None
    if not order.customer_name or not order.order_date or not order.order_time:
        related_snapshot = find_related_snapshot(task)
    customer_name = resolve_customer_name(task, related_snapshot)
    order_date = resolve_order_date(task, related_snapshot)
    order_time = resolve_order_time(task, related_snapshot)
    field_missing_info = build_field_missing_info(customer_name, order_date, order.order_amount)
    return EvidenceRequestTaskSummary(
        id=task.id,
        order_id=task.order_id,
        restaurant_id=order.restaurant_id,
        restaurant_name=order.restaurant.name,
        uber_order_number=order.uber_order_number,
        customer_name=customer_name,
        order_date=order_date,
        order_time=order_time,
        order_amount=order.order_amount,
        currency=order.currency,
        claim_status=order.status,
        task_type=task.task_type,
        required_evidence_type=task.required_evidence_type,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        title=task.title,
        description=task.description,
        reason=task.reason,
        reconciliation_result_id=task.reconciliation_result_id,
        customer_refund_dispute_id=task.customer_refund_dispute_id,
        last_upload_evidence_id=task.last_upload_evidence_id,
        field_context_label=build_field_context_label(task),
        field_restaurant_label=order.restaurant.name,
        field_customer_label=customer_name or "Nom client non trouve dans l'import",
        field_order_label=order.uber_order_number,
        field_date_label=format_field_date(order_date, order_time),
        field_amount_label=format_field_amount(order.order_amount, order.currency),
        field_search_hint=build_field_search_hint(
            restaurant_name=order.restaurant.name,
            customer_name=customer_name,
            order_number=order.uber_order_number,
            order_date=order_date,
            order_time=order_time,
        ),
        field_photo_instruction=build_field_photo_instruction(task),
        field_missing_info=field_missing_info,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def resolve_customer_name(task: EvidenceRequestTask, related_snapshot: UberOrderSnapshot | None) -> str | None:
    order = task.order
    if order.customer_name:
        return order.customer_name
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot:
        return task.reconciliation_result.matched_snapshot.customer_name
    if task.customer_refund_dispute and task.customer_refund_dispute.claim_order:
        if task.customer_refund_dispute.claim_order.customer_name:
            return task.customer_refund_dispute.claim_order.customer_name
    if related_snapshot:
        return related_snapshot.customer_name
    return None


def resolve_order_date(task: EvidenceRequestTask, related_snapshot: UberOrderSnapshot | None):
    order = task.order
    if order.order_date:
        return order.order_date
    if task.customer_refund_dispute and task.customer_refund_dispute.order_date:
        return task.customer_refund_dispute.order_date
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot and task.reconciliation_result.matched_snapshot.placed_at:
        return task.reconciliation_result.matched_snapshot.placed_at.date()
    if related_snapshot and related_snapshot.placed_at:
        return related_snapshot.placed_at.date()
    return None


def resolve_order_time(task: EvidenceRequestTask, related_snapshot: UberOrderSnapshot | None):
    order = task.order
    if order.order_time:
        return order.order_time
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot and task.reconciliation_result.matched_snapshot.placed_at:
        return task.reconciliation_result.matched_snapshot.placed_at.time().replace(microsecond=0)
    if related_snapshot and related_snapshot.placed_at:
        return related_snapshot.placed_at.time().replace(microsecond=0)
    return None


def find_related_snapshot(task: EvidenceRequestTask) -> UberOrderSnapshot | None:
    db = object_session(task)
    if db is None:
        return None
    dispute = task.customer_refund_dispute
    order_number = task.order.uber_order_number
    candidate_numbers = {order_number}
    if dispute:
        candidate_numbers.update(value for value in (dispute.uber_order_id, dispute.display_id) if value)
    statement = select(UberOrderSnapshot).where(
        UberOrderSnapshot.restaurant_id == task.order.restaurant_id,
        UberOrderSnapshot.uber_order_id.in_(candidate_numbers),
    )
    if dispute and dispute.uber_store_id:
        statement = statement.where(UberOrderSnapshot.uber_store_id == dispute.uber_store_id)
    snapshot = db.scalar(statement.order_by(UberOrderSnapshot.id.desc()).limit(1))
    if snapshot is not None:
        return snapshot
    return db.scalar(
        select(UberOrderSnapshot)
        .where(
            UberOrderSnapshot.restaurant_id == task.order.restaurant_id,
            UberOrderSnapshot.display_id.in_(candidate_numbers),
        )
        .order_by(UberOrderSnapshot.id.desc())
        .limit(1)
    )


def build_field_context_label(task: EvidenceRequestTask) -> str:
    if task.customer_refund_dispute:
        return "Remboursement client / deduction Uber"
    if task.reconciliation_result:
        return "Annulation / compensation Uber"
    loss_type = (task.order.loss_type or "").strip()
    return loss_type or "Dossier Uber"


def build_field_missing_info(customer_name: str | None, order_date, order_amount) -> list[str]:
    missing: list[str] = []
    if not customer_name:
        missing.append("nom_client")
    if not order_date:
        missing.append("date_commande")
    if order_amount is None:
        missing.append("montant_commande")
    return missing


def build_field_search_hint(
    *,
    restaurant_name: str,
    customer_name: str | None,
    order_number: str,
    order_date,
    order_time,
) -> str:
    parts = [restaurant_name, order_number]
    if customer_name:
        parts.append(customer_name)
    if order_date:
        date_part = order_date.strftime("%d/%m/%Y")
        if order_time:
            date_part = f"{date_part} {order_time.strftime('%H:%M')}"
        parts.append(date_part)
    return " - ".join(parts)


def build_field_photo_instruction(task: EvidenceRequestTask) -> str:
    evidence_label = FIELD_EVIDENCE_LABELS.get(task.required_evidence_type, "preuve")
    return (
        f"Retrouve la commande avec les informations ci-dessus, imprime le vrai ticket Uber, "
        f"agrafe-le sur la commande, prends une photo nette ({evidence_label}) puis importe-la ici."
    )


def format_field_date(order_date, order_time) -> str:
    if not order_date:
        return "Date non trouvee dans l'import"
    value = order_date.strftime("%d/%m/%Y")
    if order_time:
        value = f"{value} a {order_time.strftime('%H:%M')}"
    return value


def format_field_amount(amount, currency: str) -> str:
    if amount is None:
        return "Montant non trouve"
    return f"{amount:.2f} {currency}"


FIELD_EVIDENCE_LABELS = {
    "receipt": "ticket de caisse agrafe sur la commande",
    "cancellation_proof": "preuve d'annulation",
    "preparation_proof": "commande preparee / emballee",
    "waste_photo": "commande / gaspillage visible",
    "uber_screenshot": "capture Uber",
    "delivery_proof": "preuve de livraison",
    "packaging_photo": "photo emballage",
    "sealed_bag_photo": "photo sac ferme",
    "courier_statement": "message livreur",
    "gps_or_route_proof": "preuve GPS / trajet",
    "customer_contact_proof": "preuve contact client",
    "order_details_screenshot": "details commande Uber",
    "other": "preuve demandee",
}


def build_public_link_response(upload_link: EvidenceUploadLink) -> PublicEvidenceUploadLinkRead:
    task = upload_link.task
    order = task.order
    return PublicEvidenceUploadLinkRead(
        id=upload_link.id,
        task_id=task.id,
        order_id=order.id,
        restaurant_name=order.restaurant.name,
        uber_order_number=mask_order_number(order.uber_order_number),
        customer_name=mask_customer_name(order.customer_name),
        task_type=task.task_type,
        required_evidence_type=task.required_evidence_type,
        status=task.status,
        priority=task.priority,
        due_at=task.due_at,
        title=task.title,
        description=task.description,
        reason=task.reason,
        expires_at=upload_link.expires_at,
        max_uses=upload_link.max_uses,
        use_count=upload_link.use_count,
    )


def mask_order_number(order_number: str) -> str:
    if len(order_number) <= 8:
        return "****"
    return f"{order_number[:4]}...{order_number[-4:]}"


def mask_customer_name(customer_name: str | None) -> str | None:
    if not customer_name:
        return None
    stripped = customer_name.strip()
    if len(stripped) <= 2:
        return "***"
    return f"{stripped[0]}***"
