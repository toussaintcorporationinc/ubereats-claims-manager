from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_restaurant, get_accessible_restaurant_ids, get_current_user, require_owner, require_owner_or_manager
from app.core.database import get_db
from app.models import ClaimOrder, Restaurant, UberReconciliationResult, UberStoreMapping, User
from app.schemas.domain import (
    ClaimOrderRead,
    UberReconciliationResultsResponse,
    UberReconciliationRunResponse,
    UberReportingImportResponse,
    UberStatusRead,
    UberStoreMappingCreate,
    UberStoreMappingRead,
    UberStoreMappingUpdate,
)
from app.services.audit import add_audit_log
from app.services.uber_connector_service import UberConnectorService
from app.services.uber_reconciliation_service import UberReconciliationService
from app.services.uber_reporting_import_service import import_uber_reporting_file

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

