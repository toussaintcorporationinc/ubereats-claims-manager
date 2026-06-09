from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner, require_owner_or_manager
from app.core.database import get_db
from app.models import ClaimOrder, Restaurant, UberReconciliationResult, UberReportingImportBatch, UberReportingImportRow, UberStoreMapping, User
from app.schemas.domain import (
    ClaimOrderRead,
    UberReconciliationResultsResponse,
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


@router.get("/reconciliation/results", response_model=UberReconciliationResultsResponse)
def list_reconciliation_results(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UberReconciliationResultsResponse:
    if current_user.role == "staff":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    statement = select(UberReconciliationResult).order_by(UberReconciliationResult.id.desc())
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        statement = statement.where(UberReconciliationResult.restaurant_id.in_(accessible_ids))
    if status_filter:
        statement = statement.where(UberReconciliationResult.status == status_filter)
    results = db.scalars(statement.limit(limit).offset(offset)).all()
    return UberReconciliationResultsResponse(results=list(results), limit=limit, offset=offset)


@router.post("/reconciliation/run", response_model=UberReconciliationRunResponse)
def run_reconciliation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> dict[str, object]:
    return UberReconciliationService().run(db, current_user)


@router.post("/reconciliation/results/{result_id}/claim-order", response_model=ClaimOrderRead, status_code=status.HTTP_201_CREATED)
def create_claim_from_reconciliation_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ClaimOrder:
    order = UberReconciliationService().create_claim_order_from_result(db, current_user, result_id)
    ensure_can_access_restaurant(db, current_user, order.restaurant_id)
    return order


def get_batch_or_404(db: Session, batch_id: int, current_user: User) -> UberReportingImportBatch:
    batch = db.get(UberReportingImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uber reporting import batch not found")
    if current_user.role != "owner" and batch.uploaded_by_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Import batch access denied")
    return batch

