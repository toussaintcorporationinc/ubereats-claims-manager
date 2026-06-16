from datetime import date, datetime, time
from typing import Any
import unicodedata

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, object_session, selectinload

from app.core.auth import ensure_can_access_order, ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner_or_manager
from app.core.database import get_db
from app.models import (
    ClaimOrder,
    EvidenceAnalysisResult,
    EvidenceImportBatch,
    EvidenceImportedFile,
    EvidenceMatchCandidate,
    EvidenceRequestTask,
    EvidenceUploadLink,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReconciliationResult,
    User,
)
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
from app.services.order_identity_resolution_service import resolve_identity_for_task

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
    statement = (
        select(EvidenceRequestTask)
        .join(ClaimOrder)
        .options(
            selectinload(EvidenceRequestTask.order).selectinload(ClaimOrder.restaurant),
            selectinload(EvidenceRequestTask.restaurant),
            selectinload(EvidenceRequestTask.reconciliation_result).selectinload(UberReconciliationResult.matched_snapshot),
            selectinload(EvidenceRequestTask.customer_refund_dispute).selectinload(UberCustomerRefundDispute.claim_order),
            selectinload(EvidenceRequestTask.customer_refund_dispute).selectinload(UberCustomerRefundDispute.financial_transaction),
        )
        .order_by(EvidenceRequestTask.id.desc())
    )
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
    return EvidenceRequestTasksResponse(
        tasks=[build_task_summary(task, allow_import_fallback=False) for task in tasks],
        limit=limit,
        offset=offset,
    )


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


def build_task_summary(
    task: EvidenceRequestTask,
    *,
    deep_identity: bool = True,
    allow_import_fallback: bool = True,
) -> EvidenceRequestTaskSummary:
    order = task.order
    db = object_session(task)
    identity = (
        resolve_identity_for_task(db, task, allow_import_fallback=allow_import_fallback)
        if deep_identity and db is not None
        else None
    )
    customer_name = identity.customer_name if identity else order.customer_name
    order_date = identity.order_date if identity else order.order_date
    order_time = identity.order_time if identity else order.order_time
    order_label = identity.best_order_label if identity and identity.best_order_label else order.uber_order_number
    amount = identity.order_amount if identity and identity.order_amount is not None else order.order_amount
    currency = (identity.currency or order.currency) if identity else order.currency
    if not deep_identity:
        customer_name = customer_name or fast_task_customer_name(task)
        order_date = order_date or fast_task_order_date(task)
        order_time = order_time or fast_task_order_time(task)
        order_label = fast_task_order_label(task, order_label)
        amount = amount if amount is not None else fast_task_amount(task)
        currency = currency or fast_task_currency(task)
    field_missing_info = build_field_missing_info(customer_name, order_date, amount)
    return EvidenceRequestTaskSummary(
        id=task.id,
        order_id=task.order_id,
        restaurant_id=order.restaurant_id,
        restaurant_name=order.restaurant.name,
        uber_order_number=order.uber_order_number,
        customer_name=customer_name,
        order_date=order_date,
        order_time=order_time,
        order_amount=amount,
        currency=currency,
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
        field_customer_label=customer_name or "Nom client non trouve dans les imports/preuves",
        field_order_label=order_label,
        field_date_label=format_field_date(order_date, order_time),
        field_amount_label=format_field_amount(amount, currency),
        field_search_hint=build_field_search_hint(
            restaurant_name=order.restaurant.name,
            customer_name=customer_name,
            order_number=order_label,
            order_date=order_date,
            order_time=order_time,
        ),
        field_photo_instruction=build_field_photo_instruction(task),
        field_missing_info=field_missing_info,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def fast_task_customer_name(task: EvidenceRequestTask) -> str | None:
    if task.customer_refund_dispute and task.customer_refund_dispute.claim_order:
        return task.customer_refund_dispute.claim_order.customer_name
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot:
        return task.reconciliation_result.matched_snapshot.customer_name
    return None


def fast_task_order_date(task: EvidenceRequestTask):
    if task.customer_refund_dispute and task.customer_refund_dispute.order_date:
        return task.customer_refund_dispute.order_date
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot and task.reconciliation_result.matched_snapshot.placed_at:
        return task.reconciliation_result.matched_snapshot.placed_at.date()
    return None


def fast_task_order_time(task: EvidenceRequestTask):
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot and task.reconciliation_result.matched_snapshot.placed_at:
        return task.reconciliation_result.matched_snapshot.placed_at.time().replace(microsecond=0)
    return None


def fast_task_order_label(task: EvidenceRequestTask, fallback: str) -> str:
    if task.customer_refund_dispute:
        for value in (task.customer_refund_dispute.display_id, task.customer_refund_dispute.uber_order_id):
            if value:
                return value
    if task.reconciliation_result:
        for value in (task.reconciliation_result.display_id, task.reconciliation_result.uber_order_id):
            if value:
                return value
    return fallback


def fast_task_amount(task: EvidenceRequestTask):
    if task.customer_refund_dispute:
        return task.customer_refund_dispute.order_amount or task.customer_refund_dispute.customer_refund_amount
    if task.reconciliation_result:
        return task.reconciliation_result.order_amount or task.reconciliation_result.missing_amount
    return None


def fast_task_currency(task: EvidenceRequestTask) -> str | None:
    if task.customer_refund_dispute:
        return task.customer_refund_dispute.currency
    if task.reconciliation_result:
        return task.reconciliation_result.currency
    return None


def resolve_customer_name(
    task: EvidenceRequestTask,
    related_snapshot: UberOrderSnapshot | None,
    related_analysis: EvidenceAnalysisResult | None = None,
    related_transaction_payload: dict[str, Any] | None = None,
) -> str | None:
    order = task.order
    if order.customer_name:
        return order.customer_name
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot:
        if task.reconciliation_result.matched_snapshot.customer_name:
            return task.reconciliation_result.matched_snapshot.customer_name
    if task.customer_refund_dispute and task.customer_refund_dispute.claim_order:
        if task.customer_refund_dispute.claim_order.customer_name:
            return task.customer_refund_dispute.claim_order.customer_name
    if related_snapshot and related_snapshot.customer_name:
        return related_snapshot.customer_name
    analysis_customer_name = extract_analysis_customer_name(related_analysis)
    if analysis_customer_name:
        return analysis_customer_name
    transaction_customer_name = payload_string_value(
        related_transaction_payload,
        {
            "customer_name",
            "client_name",
            "eater_name",
            "customer",
            "client",
            "nom_client",
            "nom_du_client",
            "nom",
        },
    )
    if transaction_customer_name:
        return transaction_customer_name
    return None


def resolve_order_date(
    task: EvidenceRequestTask,
    related_snapshot: UberOrderSnapshot | None,
    related_analysis: EvidenceAnalysisResult | None = None,
    related_transaction_payload: dict[str, Any] | None = None,
):
    order = task.order
    if order.order_date:
        return order.order_date
    if task.customer_refund_dispute and task.customer_refund_dispute.order_date:
        return task.customer_refund_dispute.order_date
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot and task.reconciliation_result.matched_snapshot.placed_at:
        return task.reconciliation_result.matched_snapshot.placed_at.date()
    if related_snapshot and related_snapshot.placed_at:
        return related_snapshot.placed_at.date()
    if related_analysis and related_analysis.detected_order_date:
        return related_analysis.detected_order_date
    transaction_date = payload_date_value(
        related_transaction_payload,
        {
            "order_date",
            "placed_at",
            "order_created_at",
            "date_commande",
            "date_de_commande",
            "date_de_la_commande",
        },
    )
    if transaction_date:
        return transaction_date
    return None


def resolve_order_time(
    task: EvidenceRequestTask,
    related_snapshot: UberOrderSnapshot | None,
    related_transaction_payload: dict[str, Any] | None = None,
):
    order = task.order
    if order.order_time:
        return order.order_time
    if task.reconciliation_result and task.reconciliation_result.matched_snapshot and task.reconciliation_result.matched_snapshot.placed_at:
        return task.reconciliation_result.matched_snapshot.placed_at.time().replace(microsecond=0)
    if related_snapshot and related_snapshot.placed_at:
        return related_snapshot.placed_at.time().replace(microsecond=0)
    transaction_time = payload_time_value(
        related_transaction_payload,
        {
            "order_time",
            "placed_at",
            "order_created_at",
            "heure_commande",
            "heure_de_commande",
            "heure_d_acceptation_de_la_commande",
            "heure_acceptation_commande",
            "time",
        },
    )
    if transaction_time:
        return transaction_time
    return None


def build_candidate_order_numbers(task: EvidenceRequestTask, related_snapshot: UberOrderSnapshot | None = None) -> set[str]:
    values = {task.order.uber_order_number}
    dispute = task.customer_refund_dispute
    if dispute:
        values.update(value for value in (dispute.uber_order_id, dispute.display_id) if value)
    result = task.reconciliation_result
    if result:
        values.update(value for value in (result.uber_order_id, result.display_id) if value)
    if related_snapshot:
        values.update(value for value in (related_snapshot.uber_order_id, related_snapshot.display_id) if value)
    return {value.strip() for value in values if value and value.strip()}


def find_related_snapshot(task: EvidenceRequestTask, candidate_numbers: set[str] | None = None) -> UberOrderSnapshot | None:
    db = object_session(task)
    if db is None:
        return None
    dispute = task.customer_refund_dispute
    candidate_numbers = candidate_numbers or build_candidate_order_numbers(task)
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


def find_related_analysis(task: EvidenceRequestTask, candidate_numbers: set[str]) -> EvidenceAnalysisResult | None:
    db = object_session(task)
    if db is None:
        return None
    conditions = []
    if candidate_numbers:
        conditions.extend(
            [
                EvidenceAnalysisResult.detected_uber_order_number.in_(candidate_numbers),
                EvidenceAnalysisResult.detected_display_id.in_(candidate_numbers),
            ]
        )
    candidate_pairs = [("claim_order", task.order_id), ("evidence_task", task.id)]
    if task.customer_refund_dispute_id:
        candidate_pairs.append(("customer_refund_dispute", task.customer_refund_dispute_id))
    if task.reconciliation_result_id:
        candidate_pairs.append(("reconciliation_result", task.reconciliation_result_id))
    linked_analysis_ids = select(EvidenceMatchCandidate.analysis_result_id).where(
        or_(
            *[
                (EvidenceMatchCandidate.candidate_type == candidate_type)
                & (EvidenceMatchCandidate.candidate_id == candidate_id)
                for candidate_type, candidate_id in candidate_pairs
                if candidate_id
            ]
        )
    )
    conditions.append(EvidenceAnalysisResult.id.in_(linked_analysis_ids))
    return db.scalar(
        select(EvidenceAnalysisResult)
        .join(EvidenceImportedFile)
        .join(EvidenceImportBatch)
        .where(
            or_(*conditions),
            or_(EvidenceImportBatch.restaurant_id == task.order.restaurant_id, EvidenceImportBatch.restaurant_id.is_(None)),
        )
        .order_by(
            EvidenceAnalysisResult.extraction_confidence.desc(),
            EvidenceAnalysisResult.matching_confidence.desc(),
            EvidenceAnalysisResult.id.desc(),
        )
        .limit(1)
    )


def find_related_transaction_payload(task: EvidenceRequestTask, candidate_numbers: set[str]) -> dict[str, Any] | None:
    db = object_session(task)
    if db is None:
        return None
    conditions = []
    if candidate_numbers:
        conditions.append(UberFinancialTransaction.uber_order_id.in_(candidate_numbers))
    if task.customer_refund_dispute and task.customer_refund_dispute.financial_transaction_id:
        conditions.append(UberFinancialTransaction.id == task.customer_refund_dispute.financial_transaction_id)
    if not conditions:
        return None
    transaction = db.scalar(
        select(UberFinancialTransaction)
        .where(
            UberFinancialTransaction.restaurant_id == task.order.restaurant_id,
            or_(*conditions),
        )
        .order_by(UberFinancialTransaction.id.desc())
        .limit(1)
    )
    if transaction is None:
        return None
    return transaction.raw_payload_json or None


def extract_analysis_customer_name(analysis: EvidenceAnalysisResult | None) -> str | None:
    if analysis is None:
        return None
    raw_result = analysis.raw_result_json or {}
    return payload_string_value(
        raw_result,
        {
            "customer_name",
            "client_name",
            "eater_name",
            "customer",
            "client",
            "nom_client",
            "nom_du_client",
            "nom",
        },
    )


def payload_string_value(payload: dict[str, Any] | None, accepted_keys: set[str]) -> str | None:
    value = payload_value(payload, accepted_keys)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def payload_date_value(payload: dict[str, Any] | None, accepted_keys: set[str]) -> date | None:
    value = payload_value(payload, accepted_keys)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    for parser_value in (cleaned, cleaned[:10]):
        try:
            return date.fromisoformat(parser_value)
        except ValueError:
            pass
    normalized = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def payload_time_value(payload: dict[str, Any] | None, accepted_keys: set[str]) -> time | None:
    value = payload_value(payload, accepted_keys)
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    normalized = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).time().replace(microsecond=0)
    except ValueError:
        pass
    try:
        return time.fromisoformat(cleaned[:8]).replace(microsecond=0)
    except ValueError:
        try:
            return time.fromisoformat(cleaned[:5]).replace(microsecond=0)
        except ValueError:
            return None


def payload_value(payload: dict[str, Any] | None, accepted_keys: set[str]) -> Any | None:
    if not payload:
        return None
    normalized_keys = {normalize_payload_key(key) for key in accepted_keys}
    for key, value in iter_payload_items(payload):
        if normalize_payload_key(key) in normalized_keys and value not in (None, ""):
            return value
    return None


def iter_payload_items(value: Any):
    if isinstance(value, dict):
        for key, nested_value in value.items():
            yield str(key), nested_value
            yield from iter_payload_items(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from iter_payload_items(nested_value)


def normalize_payload_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return "".join(char if char.isalnum() else "_" for char in ascii_value.lower()).strip("_")


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
        return "Date non trouvee dans les imports/preuves"
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
