from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner, require_owner_or_manager
from app.core.database import get_db
from app.models import (
    ClaimOrder,
    Restaurant,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReconciliationResult,
    UberReconciliationRun,
    UberReportingImportBatch,
    UberReportingImportRow,
    UberStoreMapping,
    User,
)
from app.schemas.domain import (
    ClaimOrderRead,
    UberReconciliationBulkCreateRequest,
    UberReconciliationBulkCreateResponse,
    UberHistoricalReclassificationApplyRequest,
    UberHistoricalReclassificationRequest,
    UberHistoricalReclassificationResponse,
    UberReconciliationIgnoreRequest,
    UberReconciliationResultDetail,
    UberReconciliationResultsResponse,
    UberReconciliationRunRead,
    UberReconciliationRunRequest,
    UberReconciliationRunResponse,
    UberReportingConfirmResponse,
    UberReportingImportBatchRead,
    UberReportingImportResponse,
    UberReportingPreviewResponse,
    UberReportingReportType,
    UberReportingRowStatus,
    UberReportingRowsResponse,
    UberStatusRead,
    UberStoreMappingCreate,
    UberStoreMappingRead,
    UberStoreMappingUpdate,
    UberUnmappedStoreMapRequest,
    UberUnmappedStoreRead,
)
from app.services.audit import add_audit_log
from app.services.historical_restaurant_reclassification_service import HistoricalRestaurantReclassificationService
from app.services.uber_connector_service import UberConnectorService
from app.services.uber_reconciliation_service import UberReconciliationService
from app.services.uber_reporting_import_service import (
    ROW_PREVIEW_LIMIT,
    confirm_uber_reporting_batch,
    create_uber_reporting_preview,
    import_uber_reporting_file,
    map_unmapped_store,
    preview_metadata,
    unmapped_stores,
)

router = APIRouter(prefix="/v1/uber", tags=["uber"])


@router.get("/status", response_model=UberStatusRead)
def uber_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    if current_user.role == "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return UberConnectorService().get_status(db, current_user)


@router.get("/store-mappings", response_model=list[UberStoreMappingRead])
def list_store_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UberStoreMapping]:
    if current_user.role == "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    statement = select(UberStoreMapping).order_by(UberStoreMapping.id)
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        statement = statement.where(UberStoreMapping.restaurant_id.in_(accessible_ids))
    return list(db.scalars(statement).all())


@router.post("/store-mappings", response_model=UberStoreMappingRead, status_code=status.HTTP_201_CREATED)
def create_store_mapping(
    payload: UberStoreMappingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> UberStoreMapping:
    if db.get(Restaurant, payload.restaurant_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    existing = db.scalar(select(UberStoreMapping).where(UberStoreMapping.uber_store_id == payload.uber_store_id))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Uber store mapping already exists")
    mapping = UberStoreMapping(**payload.model_dump())
    db.add(mapping)
    db.flush()
    add_audit_log(
        db,
        entity_type="uber_store_mapping",
        entity_id=mapping.id,
        action="create_uber_store_mapping",
        user_id=current_user.id,
        new_value=payload.model_dump(),
    )
    db.commit()
    db.refresh(mapping)
    return mapping


@router.patch("/store-mappings/{mapping_id}", response_model=UberStoreMappingRead)
def update_store_mapping(
    mapping_id: int,
    payload: UberStoreMappingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> UberStoreMapping:
    mapping = db.get(UberStoreMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uber store mapping not found")
    old_value = {
        "uber_store_id": mapping.uber_store_id,
        "uber_store_name": mapping.uber_store_name,
        "merchant_store_id": mapping.merchant_store_id,
        "external_reference_id": mapping.external_reference_id,
        "active": mapping.active,
    }
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mapping, field, value)
    add_audit_log(
        db,
        entity_type="uber_store_mapping",
        entity_id=mapping.id,
        action="update_uber_store_mapping",
        user_id=current_user.id,
        old_value=old_value,
        new_value=payload.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post("/reporting/import", response_model=UberReportingImportResponse)
async def import_reporting(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    return await import_uber_reporting_file(db, current_user, file)


@router.post("/reporting/preview", response_model=UberReportingPreviewResponse)
async def preview_reporting(
    report_type: UberReportingReportType,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReportingPreviewResponse:
    batch = await create_uber_reporting_preview(db, current_user, file, report_type)
    detected_columns, unmapped_store_ids = preview_metadata(db, batch)
    rows_preview = db.scalars(
        select(UberReportingImportRow)
        .where(UberReportingImportRow.batch_id == batch.id)
        .order_by(UberReportingImportRow.row_number)
        .limit(ROW_PREVIEW_LIMIT)
    ).all()
    payload = UberReportingImportBatchRead.model_validate(batch).model_dump()
    return UberReportingPreviewResponse(
        **payload,
        batch_id=batch.id,
        unmapped_store_ids=unmapped_store_ids,
        detected_columns=detected_columns,
        rows_preview=list(rows_preview),
    )


@router.get("/reporting/batches", response_model=list[UberReportingImportBatchRead])
def list_reporting_batches(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> list[UberReportingImportBatch]:
    statement = select(UberReportingImportBatch).order_by(UberReportingImportBatch.id.desc())
    if current_user.role != "owner":
        statement = statement.where(UberReportingImportBatch.uploaded_by_user_id == current_user.id)
    return list(db.scalars(statement).all())


@router.get("/reporting/batches/{batch_id}", response_model=UberReportingImportBatchRead)
def get_reporting_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReportingImportBatch:
    batch = get_batch_or_404(db, batch_id, current_user)
    return batch


@router.get("/reporting/batches/{batch_id}/rows", response_model=UberReportingRowsResponse)
def get_reporting_rows(
    batch_id: int,
    status_filter: UberReportingRowStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReportingRowsResponse:
    get_batch_or_404(db, batch_id, current_user)
    statement = select(UberReportingImportRow).where(UberReportingImportRow.batch_id == batch_id)
    if status_filter:
        statement = statement.where(UberReportingImportRow.status == status_filter)
    rows = db.scalars(statement.order_by(UberReportingImportRow.row_number).limit(limit).offset(offset)).all()
    return UberReportingRowsResponse(rows=list(rows), limit=limit, offset=offset)


@router.post("/reporting/batches/{batch_id}/confirm", response_model=UberReportingConfirmResponse)
def confirm_reporting_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    batch = get_batch_or_404(db, batch_id, current_user)
    return confirm_uber_reporting_batch(db, current_user, batch)


@router.post("/reporting/batches/{batch_id}/cancel", response_model=UberReportingImportBatchRead)
def cancel_reporting_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReportingImportBatch:
    batch = get_batch_or_404(db, batch_id, current_user)
    if batch.status in {"confirmed", "partially_imported"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmed batch cannot be cancelled")
    batch.status = "cancelled"
    add_audit_log(
        db,
        entity_type="uber_reporting_import_batch",
        entity_id=batch.id,
        action="cancel_uber_reporting_import",
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/reporting/unmapped-stores", response_model=list[UberUnmappedStoreRead])
def list_unmapped_stores(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> list[dict[str, object]]:
    return unmapped_stores(db, current_user)


@router.post("/reporting/unmapped-stores/{uber_store_id}/map", response_model=UberStoreMappingRead)
def map_reporting_unmapped_store(
    uber_store_id: str,
    payload: UberUnmappedStoreMapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> UberStoreMapping:
    return map_unmapped_store(db, current_user, uber_store_id, payload.restaurant_id)


@router.post(
    "/historical-reclassification/preview",
    response_model=UberHistoricalReclassificationResponse,
)
def preview_historical_reclassification(
    payload: UberHistoricalReclassificationRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> dict[str, object]:
    payload = payload or UberHistoricalReclassificationRequest()
    if payload.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, payload.restaurant_id, include_inactive=True)
    return HistoricalRestaurantReclassificationService().preview(
        db,
        current_user,
        restaurant_id=payload.restaurant_id,
        min_confidence=payload.min_confidence,
        limit=payload.limit,
    )


@router.post(
    "/historical-reclassification/apply",
    response_model=UberHistoricalReclassificationResponse,
)
def apply_historical_reclassification(
    payload: UberHistoricalReclassificationApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> dict[str, object]:
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Set confirm=true after reviewing the preview.",
        )
    if payload.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, payload.restaurant_id, include_inactive=True)
    return HistoricalRestaurantReclassificationService().apply(
        db,
        current_user,
        restaurant_id=payload.restaurant_id,
        min_confidence=payload.min_confidence,
        limit=payload.limit,
    )


@router.get("/reconciliation/results", response_model=UberReconciliationResultsResponse)
def list_reconciliation_results(
    run_id: int | None = None,
    restaurant_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    min_missing_amount: float | None = None,
    evidence_required: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UberReconciliationResultsResponse:
    if current_user.role == "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    statement = select(UberReconciliationResult).order_by(UberReconciliationResult.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, restaurant_id)
        statement = statement.where(UberReconciliationResult.restaurant_id == restaurant_id)
    if accessible_ids is not None:
        statement = statement.where(UberReconciliationResult.restaurant_id.in_(accessible_ids))
    if run_id:
        statement = statement.where(UberReconciliationResult.run_id == run_id)
    if status_filter:
        statement = statement.where(UberReconciliationResult.status == status_filter)
    if min_missing_amount is not None:
        statement = statement.where(UberReconciliationResult.missing_amount >= min_missing_amount)
    if evidence_required is not None:
        statement = statement.where(UberReconciliationResult.evidence_required == evidence_required)
    if date_from is not None:
        statement = statement.where(UberReconciliationResult.created_at >= date_from)
    if date_to is not None:
        statement = statement.where(UberReconciliationResult.created_at <= date_to)
    results = db.scalars(statement.limit(limit).offset(offset)).all()
    return UberReconciliationResultsResponse(results=list(results), limit=limit, offset=offset)


@router.post("/reconciliation/run", response_model=UberReconciliationRunResponse)
def run_reconciliation(
    payload: UberReconciliationRunRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    payload = payload or UberReconciliationRunRequest()
    return UberReconciliationService().run(
        db,
        current_user,
        restaurant_id=payload.restaurant_id,
        date_from=payload.date_from,
        date_to=payload.date_to,
        dry_run=payload.dry_run,
    )


@router.get("/reconciliation/runs", response_model=list[UberReconciliationRunRead])
def list_reconciliation_runs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> list[UberReconciliationRun]:
    statement = select(UberReconciliationRun).order_by(UberReconciliationRun.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        statement = statement.where(UberReconciliationRun.restaurant_id.in_(accessible_ids) | (UberReconciliationRun.restaurant_id.is_(None)))
    return list(db.scalars(statement).all())


@router.get("/reconciliation/runs/{run_id}", response_model=UberReconciliationRunRead)
def get_reconciliation_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReconciliationRun:
    run = db.get(UberReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation run not found")
    if run.restaurant_id is not None:
        ensure_can_access_restaurant(db, current_user, run.restaurant_id)
    return run


@router.post(
    "/reconciliation/results/bulk-create-claim-orders",
    response_model=UberReconciliationBulkCreateResponse,
)
def bulk_create_claims_from_reconciliation_results(
    payload: UberReconciliationBulkCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    return UberReconciliationService().bulk_create_claim_orders_from_results(db, current_user, payload.result_ids)


@router.get("/reconciliation/results/{result_id}", response_model=UberReconciliationResultDetail)
def get_reconciliation_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReconciliationResultDetail:
    result = get_reconciliation_result_or_404(db, current_user, result_id)
    snapshot = db.get(UberOrderSnapshot, result.matched_snapshot_id) if result.matched_snapshot_id else None
    transactions = []
    if result.matched_transaction_ids_json:
        transactions = list(
            db.scalars(
                select(UberFinancialTransaction).where(UberFinancialTransaction.id.in_(result.matched_transaction_ids_json))
            ).all()
        )
    claim_order = db.get(ClaimOrder, result.claim_order_id) if result.claim_order_id else None
    return UberReconciliationResultDetail(result=result, snapshot=snapshot, transactions=transactions, claim_order=claim_order)


@router.post("/reconciliation/results/{result_id}/claim-order", response_model=ClaimOrderRead, status_code=status.HTTP_201_CREATED)
def create_claim_from_reconciliation_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ClaimOrder:
    order = UberReconciliationService().create_claim_order_from_result(db, current_user, result_id)
    ensure_can_access_restaurant(db, current_user, order.restaurant_id)
    return order


@router.post("/reconciliation/results/{result_id}/ignore", response_model=UberReconciliationResultsResponse)
def ignore_reconciliation_result(
    result_id: int,
    payload: UberReconciliationIgnoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> UberReconciliationResultsResponse:
    result = UberReconciliationService().ignore_result(db, current_user, result_id, payload.reason)
    return UberReconciliationResultsResponse(results=[result], limit=1, offset=0)


def get_batch_or_404(db: Session, batch_id: int, current_user: User) -> UberReportingImportBatch:
    batch = db.get(UberReportingImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uber reporting import batch not found")
    if current_user.role != "owner" and batch.uploaded_by_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Import batch access denied")
    return batch


def get_reconciliation_result_or_404(db: Session, current_user: User, result_id: int) -> UberReconciliationResult:
    result = db.get(UberReconciliationResult, result_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation result not found")
    ensure_can_access_restaurant(db, current_user, result.restaurant_id)
    return result

