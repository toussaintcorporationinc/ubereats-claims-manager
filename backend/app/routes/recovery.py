import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_owner_or_manager
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User
from app.schemas.domain import RecoveryActionsResponse, RecoveryCasesResponse, RecoverySummary
from app.services.recovery_cockpit_service import (
    RecoveryCockpitService,
    RecoveryExportLimitError,
    RecoveryFilters,
    RecoveryPermissionError,
)

router = APIRouter(prefix="/v1/recovery", tags=["recovery"])


def recovery_filters(
    restaurant_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    loss_category: str | None = Query(default=None),
    include_ignored: bool = Query(default=False),
) -> RecoveryFilters:
    return RecoveryFilters(
        restaurant_id=restaurant_id,
        date_from=date_from,
        date_to=date_to,
        loss_category=loss_category,
        include_ignored=include_ignored,
    )


@router.get("/summary", response_model=RecoverySummary)
def recovery_summary(
    filters: RecoveryFilters = Depends(recovery_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> RecoverySummary:
    try:
        return RecoveryCockpitService(db, current_user, filters, max_source_rows=3000).summary()
    except RecoveryPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/cases", response_model=RecoveryCasesResponse)
def recovery_cases(
    filters: RecoveryFilters = Depends(recovery_filters),
    case_type: str | None = Query(default=None),
    recovery_stage: str | None = Query(default=None),
    min_amount: Decimal | None = Query(default=None),
    max_amount: Decimal | None = Query(default=None),
    needs_evidence: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> RecoveryCasesResponse:
    try:
        source_limit = max(1000, offset + limit * 3)
        cases = RecoveryCockpitService(db, current_user, filters, max_source_rows=source_limit).cases(limit=None, offset=0)
    except RecoveryPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    cases = filter_cases(
        cases,
        case_type=case_type,
        recovery_stage=recovery_stage,
        min_amount=min_amount,
        max_amount=max_amount,
        needs_evidence=needs_evidence,
    )
    return RecoveryCasesResponse(cases=cases[offset : offset + limit], limit=limit, offset=offset)


@router.get("/actions", response_model=RecoveryActionsResponse)
def recovery_actions(
    filters: RecoveryFilters = Depends(recovery_filters),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecoveryActionsResponse:
    try:
        actions = RecoveryCockpitService(db, current_user, filters).actions(limit=limit, offset=offset)
    except RecoveryPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return RecoveryActionsResponse(actions=actions, limit=limit, offset=offset)


@router.get("/export/summary.xlsx")
def export_recovery_summary_xlsx(
    filters: RecoveryFilters = Depends(recovery_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    try:
        service = RecoveryCockpitService(db, current_user, filters)
        summary = service.summary()
        service.ensure_export_limit(summary.top_recoverable_cases, get_settings().export_max_rows)
    except RecoveryPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RecoveryExportLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    sheets = {
        "Summary": (["metric", "value"], [{"metric": key, "value": value} for key, value in summary.totals.model_dump(mode="json").items()]),
        "By Restaurant": (
            list(summary.by_restaurant[0].model_dump(mode="json").keys()) if summary.by_restaurant else breakdown_headers("restaurant"),
            [row.model_dump(mode="json") for row in summary.by_restaurant],
        ),
        "By Category": (
            list(summary.by_loss_category[0].model_dump(mode="json").keys()) if summary.by_loss_category else breakdown_headers(),
            [row.model_dump(mode="json") for row in summary.by_loss_category],
        ),
        "By Stage": (
            list(summary.by_recovery_stage[0].model_dump(mode="json").keys()) if summary.by_recovery_stage else breakdown_headers(),
            [row.model_dump(mode="json") for row in summary.by_recovery_stage],
        ),
        "Top Recoverable": (
            list(summary.top_recoverable_cases[0].model_dump(mode="json").keys()) if summary.top_recoverable_cases else case_headers(),
            [row.model_dump(mode="json") for row in summary.top_recoverable_cases],
        ),
        "Actions": (
            action_headers(),
            [row.model_dump(mode="json") for row in service.actions(limit=None, offset=0)[:1000]],
        ),
    }
    return xlsx_response(sheets, "tennet_recovery_summary")


@router.get("/export/cases.csv")
def export_recovery_cases_csv(
    filters: RecoveryFilters = Depends(recovery_filters),
    case_type: str | None = Query(default=None),
    recovery_stage: str | None = Query(default=None),
    min_amount: Decimal | None = Query(default=None),
    max_amount: Decimal | None = Query(default=None),
    needs_evidence: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    try:
        service = RecoveryCockpitService(db, current_user, filters)
        cases = filter_cases(
            service.cases(limit=None, offset=0),
            case_type=case_type,
            recovery_stage=recovery_stage,
            min_amount=min_amount,
            max_amount=max_amount,
            needs_evidence=needs_evidence,
        )
        service.ensure_export_limit(cases, get_settings().export_max_rows)
    except RecoveryPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RecoveryExportLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return csv_response(case_headers(), [case.model_dump(mode="json") for case in cases], "tennet_recovery_cases")


def filter_cases(
    cases: list[Any],
    *,
    case_type: str | None,
    recovery_stage: str | None,
    min_amount: Decimal | None,
    max_amount: Decimal | None,
    needs_evidence: bool | None,
) -> list[Any]:
    filtered = cases
    if case_type:
        filtered = [case for case in filtered if case.case_type == case_type]
    if recovery_stage:
        filtered = [case for case in filtered if case.recovery_stage == recovery_stage]
    if min_amount is not None:
        filtered = [case for case in filtered if case.detected_amount >= min_amount]
    if max_amount is not None:
        filtered = [case for case in filtered if case.detected_amount <= max_amount]
    if needs_evidence is not None:
        filtered = [
            case
            for case in filtered
            if (case.recovery_stage == "needs_evidence" or case.evidence_status in {"missing", "partial"}) == needs_evidence
        ]
    return filtered


def csv_response(headers: list[str], rows: list[dict[str, Any]], filename_prefix: str) -> Response:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename_prefix}_{date.today():%Y%m%d}.csv"'},
    )


def xlsx_response(sheets: dict[str, tuple[list[str], list[dict[str, Any]]]], filename_prefix: str) -> Response:
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    for title, (headers, rows) in sheets.items():
        worksheet = workbook.create_sheet(title=title)
        write_sheet(worksheet, headers, rows)
    output = BytesIO()
    workbook.save(output)
    return Response(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename_prefix}_{date.today():%Y%m%d}.xlsx"'},
    )


def write_sheet(worksheet: Worksheet, headers: list[str], rows: list[dict[str, Any]]) -> None:
    worksheet.append(headers)
    for row in rows:
        worksheet.append([row.get(header) for header in headers])
    for column_cells in worksheet.columns:
        max_length = max([len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells] + [12])
        worksheet.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 36)


def case_headers() -> list[str]:
    return [
        "case_type",
        "case_id",
        "restaurant_id",
        "restaurant_name",
        "uber_order_number",
        "loss_category",
        "recovery_stage",
        "detected_amount",
        "claimable_amount",
        "recovered_amount",
        "status",
        "evidence_status",
        "next_action",
        "created_at",
        "link_url",
    ]


def action_headers() -> list[str]:
    return ["action_type", "case_type", "case_id", "restaurant_name", "priority", "amount", "due_at", "label", "url"]


def breakdown_headers(kind: str = "default") -> list[str]:
    if kind == "restaurant":
        return ["key", "restaurant_id", "restaurant_name", "count", "detected_amount", "claimable_amount", "recovered_amount", "refused_amount"]
    return ["key", "count", "detected_amount", "claimable_amount", "recovered_amount", "refused_amount"]
