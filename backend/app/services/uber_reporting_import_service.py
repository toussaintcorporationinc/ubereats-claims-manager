from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import can_access_restaurant
from app.models import (
    Restaurant,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReportingImportBatch,
    UberReportingImportRow,
    UberStoreMapping,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.smart_import_classifier_service import normalize_for_match, read_tabular_rows, rows_to_dicts_with_detected_header

REPORT_TYPES = {"orders_report", "payments_report", "adjustments_report", "combined_report"}
ROW_PREVIEW_LIMIT = 100
MAX_ROWS = 20000

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "uber_store_id": ("uber_store_id", "store_id", "store_uuid", "restaurant_uuid", "merchant_store_id", "store id", "store uuid"),
    "uber_store_name": ("store_name", "restaurant_name", "merchant_name", "restaurant", "store"),
    "uber_order_id": (
        "uber_order_id",
        "order_id",
        "order_uuid",
        "workflow_uuid",
        "commande_uber",
        "numéro_commande",
        "numero_commande",
        "uber_id",
    ),
    "display_id": ("display_id", "visible_id", "short_order_id", "order_display_id"),
    "customer_name": ("customer_name", "customer", "client", "eater_name", "nom_client", "nom du client", "client name"),
    "order_status": ("order_status", "status", "current_state", "state", "statut"),
    "placed_at": ("placed_at", "order_date", "date", "date_commande", "created_at"),
    "canceled_at": ("canceled_at", "cancellation_date", "cancellation_time", "heure_annulation", "annulation"),
    "order_total_amount": ("order_total_amount", "total", "amount", "order_amount", "montant", "montant_commande"),
    "transaction_type": ("transaction_type", "type", "adjustment_type", "payment_type", "line_item_type"),
    "transaction_date": ("transaction_date", "payout_date", "payment_date", "date_transaction", "date_paiement"),
    "payout_reference": ("payout_reference", "payout_id", "payment_reference", "versement", "reference_paiement"),
    "amount": ("amount", "montant", "total", "value", "net_amount", "payout_amount"),
    "currency": ("currency", "devise"),
}

COLUMN_ALIASES["uber_store_id"] += ("id. du restaurant", "id du restaurant")
COLUMN_ALIASES["uber_store_id"] += ("id. externe du restaurant", "id externe du restaurant", "external restaurant id")
COLUMN_ALIASES["uber_store_name"] += ("nom du restaurant",)
COLUMN_ALIASES["uber_order_id"] += ("id. du flux", "id du flux", "id. de la commande", "id de la commande")
COLUMN_ALIASES["uber_order_id"] += ("uuid du processus", "process uuid")
COLUMN_ALIASES["display_id"] += ("id. de la commande", "id de la commande")
COLUMN_ALIASES["order_status"] += ("statut de la commande",)
COLUMN_ALIASES["placed_at"] += ("date de la commande", "heure d'acceptation de la commande")
COLUMN_ALIASES["placed_at"] += ("heure de la commande", "heure d'acceptation par le marchand")
COLUMN_ALIASES["order_total_amount"] += ("ventes (tva incluse)",)
COLUMN_ALIASES["transaction_date"] += ("date de la commande", "heure du remboursement", "heure de la commande")
COLUMN_ALIASES["payout_reference"] += ("id. de reference du versement", "id. de référence du versement")
COLUMN_ALIASES["transaction_type"] += (
    "probleme avec la commande",
    "problème avec la commande",
    "informations concernant le probleme lie a l'article",
    "informations concernant le problème lié à l'article",
    "articles incorrects",
    "personnalisations incorrectes",
)
COLUMN_ALIASES["currency"] += ("code de devise",)
COLUMN_ALIASES["uber_store_id"] += (
    "merchant_uuid",
    "merchant_id",
    "merchant store id",
    "merchant store uuid",
    "restaurant id",
    "restaurant uuid",
)
COLUMN_ALIASES["uber_order_id"] += (
    "workflow uuid",
    "workflow id",
    "order uuid",
    "order id",
    "order workflow id",
    "order workflow uuid",
    "uuid du workflow",
    "id du workflow",
)
COLUMN_ALIASES["placed_at"] += (
    "order date",
    "refund date",
    "refunded at",
    "date du remboursement",
    "date de remboursement",
    "date remboursement",
)
COLUMN_ALIASES["transaction_date"] += (
    "order date",
    "refund date",
    "refunded at",
    "date du remboursement",
    "date de remboursement",
    "date remboursement",
)
COLUMN_ALIASES["transaction_type"] += (
    "issue",
    "problem",
    "reason",
    "refund reason",
    "order issue",
    "accuracy issue",
    "defect category",
    "motif",
    "motif remboursement",
    "motif du remboursement",
    "categorie probleme",
    "categorie du probleme",
)
COLUMN_ALIASES["amount"] += (
    "refund amount",
    "refunded amount",
    "amount refunded",
    "customer refund",
    "customer refund amount",
    "merchant refund amount",
    "merchant charged amount",
    "amount charged to merchant",
    "deduction amount",
    "montant remboursement",
    "montant du remboursement",
    "montant rembourse",
    "montant facture au commercant",
    "montant deduit",
    "montant debit",
)
COLUMN_ALIASES["amount"] += (
    "ajustements lies a des erreurs de commande (tva incluse)",
    "ajustements liés à des erreurs de commande (tva incluse)",
    "remboursements",
    "remboursement pris en charge par le commercant",
    "remboursement pris en charge par le commerçant",
    "client rembourse",
    "client remboursé",
)

ORDER_ERROR_ADJUSTMENT_AMOUNT_ALIASES = (
    "ajustements lies a des erreurs de commande (tva incluse)",
    "ajustements liés à des erreurs de commande (tva incluse)",
    "ajustements lies a des erreurs de commande (hors tva)",
    "ajustements liés à des erreurs de commande (hors tva)",
)
CUSTOMER_REFUND_AMOUNT_ALIASES = (
    "remboursement pris en charge par le commercant",
    "remboursement pris en charge par le commerçant",
    "remboursements",
    "remboursements du client",
    "client rembourse",
    "client remboursé",
)

CUSTOMER_REFUND_AMOUNT_ALIASES += (
    "refund amount",
    "refunded amount",
    "amount refunded",
    "customer refund",
    "customer refund amount",
    "merchant refund amount",
    "merchant charged amount",
    "amount charged to merchant",
    "deduction amount",
    "montant remboursement",
    "montant du remboursement",
    "montant rembourse",
    "montant facture au commercant",
    "montant deduit",
    "montant debit",
)

ORDER_FIELDS = {
    "uber_store_id",
    "uber_store_name",
    "uber_order_id",
    "display_id",
    "customer_name",
    "order_status",
    "placed_at",
    "canceled_at",
    "order_total_amount",
    "currency",
}
TRANSACTION_FIELDS = {
    "uber_store_id",
    "uber_order_id",
    "transaction_type",
    "transaction_date",
    "payout_reference",
    "amount",
    "currency",
}
CANCELLED_MARKERS = {
    "canceled",
    "cancelled",
    "cancel",
    "annulé",
    "annule",
    "annulée",
    "cancellation",
    "customer_cancelled",
    "eater_cancelled",
    "failed_delivery",
    "unfulfilled",
}


def is_cancelled_order_status(value: object) -> bool:
    normalized = normalize_text(value).replace(" ", "_")
    return normalized in CANCELLED_MARKERS or any(marker in normalized for marker in ("cancel", "annul"))


async def create_uber_reporting_preview(
    db: Session,
    current_user: User,
    file: UploadFile,
    report_type: str,
) -> UberReportingImportBatch:
    filename = file.filename or "uber-report"
    return create_uber_reporting_preview_from_content(
        db,
        current_user,
        filename=filename,
        content=await file.read(),
        report_type=report_type,
    )


def create_uber_reporting_preview_from_content(
    db: Session,
    current_user: User,
    *,
    filename: str,
    content: bytes,
    report_type: str,
) -> UberReportingImportBatch:
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported report_type")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in {"csv", "xlsx"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV and XLSX reports are supported")

    parsed_rows = parse_rows(content, suffix)
    batch = UberReportingImportBatch(
        uploaded_by_user_id=current_user.id,
        original_filename=filename,
        report_type=report_type,
        file_type=suffix,
        status="parsed",
    )
    db.add(batch)
    db.flush()

    seen: set[tuple[Any, ...]] = set()
    for index, raw_row in enumerate(parsed_rows[:MAX_ROWS], start=2):
        normalized_raw = normalize_keys(raw_row)
        if is_empty_row(normalized_raw):
            continue
        normalized_data, errors, warnings = normalize_report_row(db, current_user, normalized_raw, report_type)
        dedupe_key = row_dedupe_key(normalized_data, report_type)
        row_status = "invalid" if errors else "warning" if warnings else "valid"
        if dedupe_key and dedupe_key in seen:
            row_status = "duplicate"
            warnings.append("duplicate_in_file")
        elif dedupe_key:
            seen.add(dedupe_key)
        db.add(
            UberReportingImportRow(
                batch_id=batch.id,
                row_number=index,
                raw_data=safe_json(normalized_raw),
                normalized_data=normalized_data or None,
                status=row_status,
                errors=errors,
                warnings=warnings,
            )
        )

    db.flush()
    refresh_batch_counts(db, batch)
    add_audit_log(
        db,
        entity_type="uber_reporting_import_batch",
        entity_id=batch.id,
        action="preview_uber_reporting_import",
        user_id=current_user.id,
        new_value={"report_type": report_type, "filename": filename, "rows": batch.total_rows},
    )
    db.commit()
    db.refresh(batch)
    return batch


def confirm_uber_reporting_batch(
    db: Session,
    current_user: User,
    batch: UberReportingImportBatch,
) -> dict[str, object]:
    if batch.status in {"confirmed", "partially_imported"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Batch already confirmed")
    if batch.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Batch cancelled")
    rows = db.scalars(
        select(UberReportingImportRow)
        .where(UberReportingImportRow.batch_id == batch.id)
        .order_by(UberReportingImportRow.row_number)
    ).all()
    errors: list[str] = []
    skipped = 0
    created_snapshots = 0
    created_transactions = 0
    for row in rows:
        if row.status not in {"valid", "warning"} or not row.normalized_data:
            skipped += 1
            continue
        restaurant_id = row.normalized_data.get("restaurant_id")
        if not isinstance(restaurant_id, int) or not can_access_restaurant(db, current_user, restaurant_id):
            row.status = "skipped"
            row.errors = [*row.errors, "restaurant_access_denied"]
            skipped += 1
            continue
        try:
            if row.normalized_data.get("row_kind") == "order":
                snapshot, created = create_or_update_snapshot(db, row.normalized_data)
                row.created_snapshot_id = snapshot.id
                created_snapshots += int(created)
            elif row.normalized_data.get("row_kind") == "transaction":
                transaction, created = create_transaction_if_missing(db, row.normalized_data)
                row.created_transaction_id = transaction.id if transaction else None
                created_transactions += int(created)
                if not created:
                    skipped += 1
            row.status = "created"
        except Exception as exc:
            row.status = "skipped"
            row.errors = [*row.errors, str(exc)]
            errors.append(f"Row {row.row_number}: {exc}")
            skipped += 1

    batch.created_snapshots_count = created_snapshots
    batch.created_transactions_count = created_transactions
    batch.confirmed_at = utc_now()
    batch.status = "confirmed" if not errors else "partially_imported"
    add_audit_log(
        db,
        entity_type="uber_reporting_import_batch",
        entity_id=batch.id,
        action="confirm_uber_reporting_import",
        user_id=current_user.id,
        new_value={
            "created_snapshots_count": created_snapshots,
            "created_transactions_count": created_transactions,
            "skipped_rows": skipped,
        },
    )
    db.commit()
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "created_snapshots_count": created_snapshots,
        "created_transactions_count": created_transactions,
        "skipped_rows": skipped,
        "errors": errors,
    }


async def import_uber_reporting_file(db: Session, current_user: User, file: UploadFile) -> dict[str, object]:
    batch = await create_uber_reporting_preview(db, current_user, file, "combined_report")
    result = confirm_uber_reporting_batch(db, current_user, batch)
    return {
        "snapshots_created": result["created_snapshots_count"],
        "transactions_created": result["created_transactions_count"],
        "rows_skipped": result["skipped_rows"],
        "errors": result["errors"],
    }


def normalize_report_row(
    db: Session,
    current_user: User,
    row: dict[str, Any],
    report_type: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    normalized: dict[str, Any] = {
        "currency": get_column_value(row, "currency") or "EUR",
        "raw_data": safe_json({key: value for key, value in row.items() if value not in {None, ""}}),
    }
    errors: list[str] = []
    warnings: list[str] = []
    for field in ORDER_FIELDS | TRANSACTION_FIELDS:
        value = get_column_value(row, field)
        if value not in {None, ""}:
            normalized[field] = value
    infer_combined_report_transaction_type(row, normalized, report_type)
    normalize_order_accuracy_identifiers(row, normalized)

    mapping = resolve_mapping(db, normalized.get("uber_store_id"))
    if not mapping:
        mapping = resolve_mapping_by_store_name(db, normalized.get("uber_store_name"))
        if mapping and not normalized.get("uber_store_id"):
            normalized["uber_store_id"] = mapping.uber_store_id
            warnings.append("missing_store_id_resolved_by_store_name")
    if mapping:
        normalized["restaurant_id"] = mapping.restaurant_id
        if not can_access_restaurant(db, current_user, mapping.restaurant_id):
            errors.append("restaurant_access_denied")
    else:
        restaurant = resolve_restaurant_by_store_name(db, normalized.get("uber_store_name"))
        if restaurant:
            normalized["restaurant_id"] = restaurant.id
            if not normalized.get("uber_store_id"):
                normalized["uber_store_id"] = derived_store_id_from_restaurant(restaurant)
                warnings.append("missing_store_id_resolved_by_restaurant_name")
            else:
                warnings.append("restaurant_matched_by_store_name")
            if not can_access_restaurant(db, current_user, restaurant.id):
                errors.append("restaurant_access_denied")
        elif normalized.get("uber_store_id"):
            warnings.append("unmapped_store")
        elif normalized.get("uber_store_name"):
            warnings.append("unmapped_store_name")
            errors.append("missing_uber_store_id")
        else:
            errors.append("missing_uber_store_id")

    row_kind = infer_row_kind(normalized, report_type)
    normalized["row_kind"] = row_kind
    if row_kind == "order":
        normalize_order_values(normalized, errors, warnings)
    elif row_kind == "transaction":
        normalize_transaction_values(normalized, errors)
    else:
        errors.append("unable_to_determine_row_type")
    return normalized, errors, warnings


def infer_row_kind(row: dict[str, Any], report_type: str) -> str:
    if report_type == "orders_report":
        return "order"
    if report_type in {"payments_report", "adjustments_report"}:
        return "transaction"
    if report_type == "combined_report":
        amount = parse_decimal(row.get("amount"))
        if row.get("transaction_type") or (
            row.get("transaction_date") and amount is not None and amount != Decimal("0") and not row.get("order_status")
        ):
            return "transaction"
        if row.get("order_status") or row.get("order_total_amount"):
            return "order"
        return "unknown"
    if row.get("transaction_type") or row.get("transaction_date"):
        return "transaction"
    if row.get("order_status") or row.get("order_total_amount"):
        return "order"
    return "unknown"


def infer_combined_report_transaction_type(row: dict[str, Any], normalized: dict[str, Any], report_type: str) -> None:
    if report_type not in {"combined_report", "adjustments_report"}:
        return
    existing_transaction_type = normalized.get("transaction_type")
    adjustment_amount = get_column_value_from_aliases(row, ORDER_ERROR_ADJUSTMENT_AMOUNT_ALIASES)
    refund_amount = get_column_value_from_aliases(row, CUSTOMER_REFUND_AMOUNT_ALIASES)
    generic_amount = get_column_value(row, "amount")
    parsed_adjustment = parse_decimal(adjustment_amount)
    parsed_refund = parse_decimal(refund_amount)
    if parsed_adjustment is not None and parsed_adjustment != Decimal("0"):
        normalized["amount"] = adjustment_amount
        if not existing_transaction_type:
            normalized["transaction_type"] = "order_error_adjustment"
    elif parsed_refund is not None and parsed_refund != Decimal("0"):
        normalized["amount"] = refund_amount
        if not existing_transaction_type or row_looks_like_order_accuracy_export(row):
            normalized["transaction_type"] = "customer_refund"
    elif row_looks_like_order_accuracy_export(row):
        parsed_generic = parse_decimal(generic_amount)
        if parsed_generic is not None and parsed_generic != Decimal("0"):
            normalized["amount"] = generic_amount
            if not existing_transaction_type:
                normalized["transaction_type"] = infer_order_accuracy_transaction_type(row)


def infer_order_accuracy_transaction_type(row: dict[str, Any]) -> str:
    text = normalize_for_match(" ".join([*(str(key) for key in row), *(str(value) for value in row.values())]))
    if any(marker in text for marker in ("adjustment", "ajustement", "order error", "erreur de commande")):
        return "order_error_adjustment"
    return "customer_refund"


def row_looks_like_order_accuracy_export(row: dict[str, Any]) -> bool:
    text = normalize_for_match(" ".join([*(str(key) for key in row), *(str(value) for value in row.values())]))
    return any(
        marker in text
        for marker in (
            "inaccurate orders",
            "top inaccurate items",
            "order accuracy",
            "refund amount",
            "customer refund amount",
            "amount charged to merchant",
            "deduction amount",
            "probleme avec la commande",
            "informations concernant le probleme lie a l article",
            "articles incorrects",
            "personnalisations incorrectes",
            "remboursement pris en charge par le commercant",
            "client rembourse",
            "article manquant",
            "missing item",
            "wrong item",
            "quality issue",
        )
    )


def normalize_order_accuracy_identifiers(row: dict[str, Any], normalized: dict[str, Any]) -> None:
    if not row_looks_like_order_accuracy_export(row):
        return
    process_uuid = get_column_value_from_aliases(row, ("uuid du processus", "process uuid", "workflow uuid", "workflow id"))
    order_number = get_column_value_from_aliases(row, ("id. de la commande", "id de la commande"))
    if process_uuid not in {None, ""}:
        normalized["uber_order_id"] = process_uuid
    if order_number not in {None, ""}:
        normalized["display_id"] = order_number


def normalize_order_values(row: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    if not row.get("uber_order_id"):
        errors.append("missing_uber_order_id")
    amount = parse_decimal(row.get("order_total_amount"))
    if amount is None:
        errors.append("missing_or_invalid_order_total_amount")
    else:
        row["order_total_amount"] = str(amount)
    for key in ("placed_at", "canceled_at"):
        parsed = parse_datetime(row.get(key))
        row[key] = parsed.isoformat() if parsed else None
    status_value = row.get("order_status")
    if status_value and is_cancelled_order_status(status_value):
        row["is_cancelled"] = True
    elif status_value:
        row["is_cancelled"] = False
        warnings.append("order_status_not_cancelled")
    else:
        warnings.append("missing_order_status")


def normalize_transaction_values(row: dict[str, Any], errors: list[str]) -> None:
    if not row.get("uber_order_id"):
        errors.append("missing_uber_order_id")
    if not row.get("transaction_type"):
        errors.append("missing_transaction_type")
    amount = parse_decimal(row.get("amount"))
    if amount is None:
        errors.append("missing_or_invalid_amount")
    else:
        if row_looks_like_order_accuracy_export(row) and row.get("transaction_type") in {
            "customer_refund",
            "order_error_adjustment",
        } and amount > 0:
            amount = -amount
        row["amount"] = str(amount)
    parsed_date = parse_date(row.get("transaction_date"))
    if parsed_date is None:
        errors.append("missing_or_invalid_transaction_date")
    else:
        row["transaction_date"] = parsed_date.isoformat()


def create_or_update_snapshot(db: Session, data: dict[str, Any]) -> tuple[UberOrderSnapshot, bool]:
    snapshot = db.scalar(
        select(UberOrderSnapshot).where(
            UberOrderSnapshot.restaurant_id == data["restaurant_id"],
            UberOrderSnapshot.uber_order_id == data["uber_order_id"],
        )
    )
    created = snapshot is None
    if snapshot is None:
        snapshot = UberOrderSnapshot(
            restaurant_id=data["restaurant_id"],
            uber_store_id=data["uber_store_id"],
            uber_order_id=data["uber_order_id"],
            raw_payload_json=data,
            imported_from="manager_export",
            current_state="unknown",
        )
        db.add(snapshot)
        db.flush()
    snapshot.uber_store_id = data["uber_store_id"]
    snapshot.display_id = data.get("display_id")
    snapshot.customer_name = clean_optional(data.get("customer_name"))
    snapshot.current_state = str(data.get("order_status") or "unknown")
    snapshot.placed_at = parse_datetime(data.get("placed_at"))
    snapshot.canceled_at = parse_datetime(data.get("canceled_at"))
    snapshot.order_total_amount = Decimal(str(data["order_total_amount"]))
    snapshot.currency = str(data.get("currency") or "EUR")
    snapshot.raw_payload_json = data
    return snapshot, created


def create_transaction_if_missing(db: Session, data: dict[str, Any]) -> tuple[UberFinancialTransaction | None, bool]:
    transaction_date = parse_date(data.get("transaction_date"))
    amount = Decimal(str(data["amount"]))
    existing = db.scalar(
        select(UberFinancialTransaction).where(
            UberFinancialTransaction.restaurant_id == data["restaurant_id"],
            UberFinancialTransaction.uber_order_id == data["uber_order_id"],
            UberFinancialTransaction.transaction_type == data["transaction_type"],
            UberFinancialTransaction.transaction_date == transaction_date,
            UberFinancialTransaction.amount == amount,
            UberFinancialTransaction.payout_reference == data.get("payout_reference"),
        )
    )
    if existing:
        return existing, False
    transaction = UberFinancialTransaction(
        restaurant_id=data["restaurant_id"],
        uber_store_id=data["uber_store_id"],
        uber_order_id=data["uber_order_id"],
        transaction_type=data["transaction_type"],
        amount=amount,
        currency=str(data.get("currency") or "EUR"),
        transaction_date=transaction_date or date.today(),
        payout_reference=data.get("payout_reference"),
        raw_payload_json=data,
        imported_from="manager_export",
    )
    db.add(transaction)
    db.flush()
    return transaction, True


def preview_metadata(db: Session, batch: UberReportingImportBatch) -> tuple[list[str], list[str]]:
    rows = db.scalars(select(UberReportingImportRow).where(UberReportingImportRow.batch_id == batch.id)).all()
    detected = sorted({key for row in rows for key in row.raw_data})
    unmapped = sorted(
        {
            str(row.normalized_data.get("uber_store_id"))
            for row in rows
            if row.normalized_data and "unmapped_store" in row.warnings and row.normalized_data.get("uber_store_id")
        }
    )
    return detected, unmapped


def unmapped_stores(db: Session, current_user: User) -> list[dict[str, Any]]:
    rows = db.scalars(select(UberReportingImportRow).where(UberReportingImportRow.status.in_(["warning", "invalid"]))).all()
    counter: Counter[str] = Counter()
    names: dict[str, str | None] = {}
    for row in rows:
        data = row.normalized_data or {}
        store_id = data.get("uber_store_id")
        if not store_id or "restaurant_id" in data:
            continue
        counter[str(store_id)] += 1
        names.setdefault(str(store_id), data.get("uber_store_name"))
    restaurants = db.scalars(select(Restaurant).order_by(Restaurant.name)).all()
    visible_restaurants = [
        restaurant for restaurant in restaurants if current_user.role == "owner" or can_access_restaurant(db, current_user, restaurant.id)
    ]
    return [
        {
            "uber_store_id": store_id,
            "uber_store_name": names.get(store_id),
            "row_count": count,
            "suggested_restaurant_matches": visible_restaurants[:5],
        }
        for store_id, count in counter.items()
    ]


def map_unmapped_store(db: Session, current_user: User, uber_store_id: str, restaurant_id: int) -> UberStoreMapping:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    mapping = db.scalar(select(UberStoreMapping).where(UberStoreMapping.uber_store_id == uber_store_id))
    if mapping is None:
        mapping = UberStoreMapping(
            restaurant_id=restaurant_id,
            uber_store_id=uber_store_id,
            uber_store_name=restaurant.name,
            active=True,
        )
        db.add(mapping)
    else:
        mapping.restaurant_id = restaurant_id
        mapping.active = True
    add_audit_log(
        db,
        entity_type="uber_store_mapping",
        entity_id=restaurant_id,
        action="map_unmapped_uber_store",
        user_id=current_user.id,
        new_value={"uber_store_id": uber_store_id, "restaurant_id": restaurant_id},
    )
    db.commit()
    db.refresh(mapping)
    return mapping


def refresh_batch_counts(db: Session, batch: UberReportingImportBatch) -> None:
    rows = db.scalars(select(UberReportingImportRow).where(UberReportingImportRow.batch_id == batch.id)).all()
    batch.total_rows = len(rows)
    batch.valid_rows = sum(1 for row in rows if row.status == "valid")
    batch.invalid_rows = sum(1 for row in rows if row.status == "invalid")
    batch.warning_rows = sum(1 for row in rows if row.status == "warning")
    batch.duplicate_rows = sum(1 for row in rows if row.status == "duplicate")


def parse_rows(content: bytes, suffix: str) -> list[dict[str, Any]]:
    rows = read_tabular_rows(content, suffix)
    parsed_rows, _header_detection = rows_to_dicts_with_detected_header(rows)
    return parsed_rows


def normalize_keys(row: dict[str, Any]) -> dict[str, Any]:
    return {normalize_for_match(key): value for key, value in row.items() if key is not None}


def get_column_value(row: dict[str, Any], field: str) -> Any:
    return get_column_value_from_aliases(row, COLUMN_ALIASES[field])


def get_column_value_from_aliases(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    normalized_aliases = tuple(normalize_for_match(alias) for alias in aliases)
    for alias in normalized_aliases:
        for key, value in row.items():
            suffix = key.removeprefix(f"{alias} ")
            duplicate_key = key.startswith(f"{alias} ") and suffix.isdigit()
            if (key == alias or duplicate_key) and value not in {None, ""}:
                return value.strip() if isinstance(value, str) else value
    return None


def resolve_mapping(db: Session, uber_store_id: object) -> UberStoreMapping | None:
    if not uber_store_id:
        return None
    return db.scalar(select(UberStoreMapping).where(UberStoreMapping.uber_store_id == str(uber_store_id).strip()))


def resolve_mapping_by_store_name(db: Session, uber_store_name: object) -> UberStoreMapping | None:
    key = normalize_restaurant_lookup_key(uber_store_name)
    if not key:
        return None
    mappings = db.scalars(select(UberStoreMapping).where(UberStoreMapping.active.is_(True))).all()
    matches = [mapping for mapping in mappings if normalize_restaurant_lookup_key(mapping.uber_store_name) == key]
    return matches[0] if len(matches) == 1 else None


def resolve_restaurant_by_store_name(db: Session, uber_store_name: object) -> Restaurant | None:
    key = normalize_restaurant_lookup_key(uber_store_name)
    if not key:
        return None
    restaurants = db.scalars(select(Restaurant).where(Restaurant.active.is_(True))).all()
    matches = [restaurant for restaurant in restaurants if normalize_restaurant_lookup_key(restaurant.name) == key]
    return matches[0] if len(matches) == 1 else None


def derived_store_id_from_restaurant(restaurant: Restaurant) -> str:
    return f"restaurant-name:{restaurant.id}"


def normalize_restaurant_lookup_key(value: object) -> str:
    return normalize_for_match(value).replace(" ", "")


def row_dedupe_key(data: dict[str, Any], report_type: str) -> tuple[Any, ...] | None:
    kind = data.get("row_kind")
    if kind == "order":
        return ("order", data.get("restaurant_id"), data.get("uber_order_id"))
    if kind == "transaction":
        return (
            "transaction",
            data.get("restaurant_id"),
            data.get("uber_order_id"),
            data.get("transaction_type"),
            data.get("transaction_date"),
            data.get("amount"),
            data.get("payout_reference"),
        )
    return None


def is_empty_row(row: dict[str, Any]) -> bool:
    return not any(value not in {None, ""} for value in row.values())


def clean_optional(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def parse_decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace(" ", "")
    for token in ("€", "EUR", "eur"):
        text = text.replace(token, "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(value: object) -> date | None:
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def safe_json(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, date):
            result[key] = value.isoformat()
        elif isinstance(value, Decimal):
            result[key] = str(value)
        else:
            result[key] = value
    return result


def normalize_text(value: object) -> str:
    return str(value or "").strip().lower()
