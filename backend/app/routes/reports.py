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

from app.core.auth import require_owner_or_manager
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User
from app.schemas.domain import (
    CommercialSummary,
    ReportFollowupsResponse,
    ReportOrdersResponse,
    ReportResponsesResponse,
)
from app.services.reporting_service import (
    ReportingExportLimitError,
    ReportingFilters,
    ReportingPermissionError,
    ReportingService,
)

router = APIRouter(prefix="/v1/reports", tags=["reports"])


def reporting_filters(
    restaurant_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    result: str | None = Query(default=None),
    min_amount: Decimal | None = Query(default=None),
    max_amount: Decimal | None = Query(default=None),
    include_customer_names: bool = Query(default=False),
) -> ReportingFilters:
    return ReportingFilters(
        restaurant_id=restaurant_id,
        date_from=date_from,
        date_to=date_to,
        status=status_filter,
        result=result,
        min_amount=min_amount,
        max_amount=max_amount,
        include_customer_names=include_customer_names,
    )


@router.get("/commercial-summary", response_model=CommercialSummary)
def commercial_summary(
    filters: ReportingFilters = Depends(reporting_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> CommercialSummary:
    try:
        return ReportingService(db, current_user, filters).commercial_summary()
    except ReportingPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/orders", response_model=ReportOrdersResponse, response_model_exclude_none=True)
def report_orders(
    filters: ReportingFilters = Depends(reporting_filters),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ReportOrdersResponse:
    try:
        rows = ReportingService(db, current_user, filters).order_rows(limit=limit, offset=offset)
    except ReportingPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ReportOrdersResponse(orders=rows, limit=limit, offset=offset)


@router.get("/followups", response_model=ReportFollowupsResponse)
def report_followups(
    filters: ReportingFilters = Depends(reporting_filters),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ReportFollowupsResponse:
    try:
        rows = ReportingService(db, current_user, filters).followup_rows(limit=limit, offset=offset)
    except ReportingPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ReportFollowupsResponse(followups=rows, limit=limit, offset=offset)


@router.get("/responses", response_model=ReportResponsesResponse)
def report_responses(
    filters: ReportingFilters = Depends(reporting_filters),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> ReportResponsesResponse:
    try:
        rows = ReportingService(db, current_user, filters).response_rows(limit=limit, offset=offset)
    except ReportingPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ReportResponsesResponse(responses=rows, limit=limit, offset=offset)


@router.get("/export/orders.csv")
def export_orders_csv(
    filters: ReportingFilters = Depends(reporting_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    service = ReportingService(db, current_user, filters)
    rows = export_limited(lambda: service.order_rows(limit=None, offset=0), service)
    headers = order_headers(filters.include_customer_names)
    return csv_response(headers, [row.model_dump(mode="json", exclude_none=True) for row in rows], "ubereats_claims_orders")


@router.get("/export/orders.xlsx")
def export_orders_xlsx(
    filters: ReportingFilters = Depends(reporting_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    service = ReportingService(db, current_user, filters)
    rows = export_limited(lambda: service.order_rows(limit=None, offset=0), service)
    headers = order_headers(filters.include_customer_names)
    return xlsx_response({"Orders": (headers, [row.model_dump(mode="json", exclude_none=True) for row in rows])}, "ubereats_claims_orders")


@router.get("/export/followups.csv")
def export_followups_csv(
    filters: ReportingFilters = Depends(reporting_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    service = ReportingService(db, current_user, filters)
    rows = export_limited(lambda: service.followup_rows(limit=None, offset=0), service)
    headers = list(rows[0].model_dump(mode="json").keys()) if rows else report_followup_headers()
    return csv_response(headers, [row.model_dump(mode="json") for row in rows], "ubereats_claims_followups")


@router.get("/export/responses.csv")
def export_responses_csv(
    filters: ReportingFilters = Depends(reporting_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    service = ReportingService(db, current_user, filters)
    rows = export_limited(lambda: service.response_rows(limit=None, offset=0), service)
    headers = list(rows[0].model_dump(mode="json").keys()) if rows else report_response_headers()
    return csv_response(headers, [row.model_dump(mode="json") for row in rows], "ubereats_claims_responses")


@router.get("/export/commercial-summary.xlsx")
def export_commercial_summary_xlsx(
    filters: ReportingFilters = Depends(reporting_filters),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> Response:
    try:
        summary = ReportingService(db, current_user, filters).commercial_summary()
    except ReportingPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    sheets = {
        "Summary": (
            ["metric", "value"],
            [
                {"metric": key, "value": value}
                for key, value in summary.totals.model_dump(mode="json").items()
            ],
        ),
        "By Restaurant": (
            list(summary.by_restaurant[0].model_dump(mode="json").keys()) if summary.by_restaurant else commercial_restaurant_headers(),
            [row.model_dump(mode="json") for row in summary.by_restaurant],
        ),
        "By Status": (
            list(summary.by_status[0].model_dump(mode="json").keys()) if summary.by_status else breakdown_headers(),
            [row.model_dump(mode="json") for row in summary.by_status],
        ),
        "By Result": (
            list(summary.by_result[0].model_dump(mode="json").keys()) if summary.by_result else breakdown_headers(),
            [row.model_dump(mode="json") for row in summary.by_result],
        ),
        "Followups": (
            list(summary.followups.model_dump(mode="json").keys()),
            [summary.followups.model_dump(mode="json")],
        ),
        "Responses": (
            list(summary.responses.model_dump(mode="json").keys()),
            [summary.responses.model_dump(mode="json")],
        ),
    }
    return xlsx_response(sheets, "ubereats_claims_commercial_summary")


def export_limited(get_rows: Any, service: ReportingService) -> list[Any]:
    try:
        rows = get_rows()
        service.ensure_export_limit(rows, get_settings().export_max_rows)
    except ReportingPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ReportingExportLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return rows


def csv_response(headers: list[str], rows: list[dict[str, Any]], filename_prefix: str) -> Response:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    content = buffer.getvalue()
    return Response(
        content,
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
        header_value = str(column_cells[0].value or "")
        max_length = max([len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells] + [len(header_value)])
        worksheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 32)


def order_headers(include_customer_names: bool) -> list[str]:
    headers = [
        "order_id",
        "restaurant_id",
        "restaurant_name",
        "uber_order_number",
        "order_date",
        "order_amount",
        "currency",
        "status",
        "result",
        "recovered_amount",
        "retry_count",
        "last_followup_sent_at",
        "next_action_at",
        "evidence_count",
        "drafts_count",
        "inbound_messages_count",
        "response_reviews_count",
    ]
    if include_customer_names:
        headers.insert(4, "customer_name")
    return headers


def report_followup_headers() -> list[str]:
    return [
        "task_id",
        "restaurant_name",
        "order_id",
        "uber_order_number",
        "task_type",
        "task_status",
        "due_at",
        "claim_status",
        "order_amount",
        "currency",
        "retry_count",
    ]


def report_response_headers() -> list[str]:
    return [
        "review_id",
        "restaurant_name",
        "order_id",
        "uber_order_number",
        "review_type",
        "previous_order_status",
        "new_order_status",
        "recovered_amount",
        "refusal_reason",
        "evidence_requested",
        "created_at",
        "reviewed_by_user_id",
    ]


def commercial_restaurant_headers() -> list[str]:
    return [
        "restaurant_id",
        "restaurant_name",
        "orders_count",
        "claimed_amount",
        "recovered_amount",
        "pending_amount",
        "refused_amount",
        "accepted_count",
        "refused_count",
        "manual_review_count",
    ]


def breakdown_headers() -> list[str]:
    return ["key", "count", "claimed_amount", "recovered_amount"]
