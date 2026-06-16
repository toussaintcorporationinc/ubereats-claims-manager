from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    ClaimOrder,
    EvidenceAnalysisResult,
    EvidenceImportBatch,
    EvidenceImportedFile,
    EvidenceMatchCandidate,
    EvidenceRequestTask,
    UberCustomerRefundDispute,
    UberFinancialTransaction,
    UberOrderSnapshot,
    UberReportingImportBatch,
    UberReportingImportRow,
)

UUID_LIKE_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)
UUID_SEARCH_PATTERN = re.compile(
    r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b",
    re.IGNORECASE,
)
PAYLOAD_FALLBACK_SCAN_LIMIT = 100
IMPORT_ROW_IDENTITY_SCAN_LIMIT = 100
IMPORT_ROW_DIRECT_KEYS = (
    "uber_order_id",
    "display_id",
    "order_id",
    "order_number",
    "numero_commande",
    "id_de_la_commande",
)

ORDER_ID_KEYS = {
    "uber_order_id",
    "order_id",
    "order_uuid",
    "workflow_uuid",
    "workflow_id",
    "process_uuid",
    "uuid_du_processus",
    "uuid_de_la_commande",
    "id_du_flux",
    "id_de_flux",
    "id_flux",
}
DISPLAY_ID_KEYS = {
    "display_id",
    "visible_id",
    "short_order_id",
    "order_display_id",
    "id_de_la_commande",
    "id_commande",
    "numero_commande",
    "numero_de_commande",
    "order_number",
    "order_no",
    "receipt_number",
    "ticket_number",
}
CUSTOMER_NAME_KEYS = {
    "customer_name",
    "client_name",
    "eater_name",
    "consumer_name",
    "customer",
    "client",
    "eater",
    "consumer",
    "nom_client",
    "nom_du_client",
    "nom_de_client",
    "nom_du_consommateur",
    "nom_consommateur",
    "prenom_du_client",
    "prenom_client",
}
CUSTOMER_FIRST_NAME_KEYS = {"customer_first_name", "first_name", "prenom", "prenom_client", "prenom_du_client"}
CUSTOMER_LAST_NAME_KEYS = {"customer_last_name", "last_name", "nom_client", "nom_du_client"}
DATE_KEYS = {
    "order_date",
    "placed_at",
    "created_at",
    "order_created_at",
    "date_commande",
    "date_de_commande",
    "date_de_la_commande",
    "refund_date",
    "date_remboursement",
    "date_du_remboursement",
    "transaction_date",
}
TIME_KEYS = {
    "order_time",
    "time",
    "placed_at",
    "created_at",
    "order_created_at",
    "heure_commande",
    "heure_de_commande",
    "heure_acceptation_commande",
    "heure_d_acceptation_de_la_commande",
    "heure_dacceptation_de_la_commande",
}
AMOUNT_KEYS = {
    "order_amount",
    "order_total_amount",
    "total",
    "amount",
    "montant",
    "montant_total",
    "montant_commande",
    "ventes_tva_incluse",
    "refund_amount",
    "customer_refund_amount",
    "montant_remboursement",
}


@dataclass(slots=True)
class ResolvedOrderIdentity:
    order_number: str | None = None
    display_id: str | None = None
    customer_name: str | None = None
    order_date: date | None = None
    order_time: time | None = None
    order_amount: Decimal | None = None
    currency: str | None = None
    source: str | None = None

    @property
    def best_order_label(self) -> str | None:
        if self.display_id and not is_uuid_like(self.display_id):
            return self.display_id
        return self.order_number or self.display_id


def resolve_identity_for_task(
    db: Session,
    task: EvidenceRequestTask,
    *,
    allow_import_fallback: bool = True,
) -> ResolvedOrderIdentity:
    order = task.order
    identity = ResolvedOrderIdentity(
        order_number=order.uber_order_number,
        customer_name=clean_customer_name(order.customer_name),
        order_date=order.order_date,
        order_time=order.order_time,
        order_amount=Decimal(str(order.order_amount)) if order.order_amount is not None else None,
        currency=order.currency,
        source="claim_order",
    )
    candidates = candidate_numbers_for_task(task)

    dispute = task.customer_refund_dispute
    if dispute is not None:
        merge_identity(
            identity,
            identity_from_dispute(dispute),
            prefer_display=True,
        )
        candidates.update(candidate_numbers_from_dispute(dispute))

    result = task.reconciliation_result
    if result is not None:
        merge_identity(identity, identity_from_reconciliation_result(result), prefer_display=True)
        candidates.update(value for value in (result.uber_order_id, result.display_id) if value)

    snapshot = find_snapshot(db, order.restaurant_id, candidates, dispute.uber_store_id if dispute else None)
    if snapshot is not None:
        merge_identity(identity, identity_from_snapshot(snapshot), prefer_display=True)
        candidates.update(value for value in (snapshot.uber_order_id, snapshot.display_id) if value)

    transaction = find_transaction(db, order.restaurant_id, candidates, dispute)
    if transaction is not None:
        merge_identity(identity, identity_from_transaction(transaction), prefer_display=True)
        candidates.update(candidate_numbers_from_payload(transaction.raw_payload_json))

    analysis = find_analysis(db, order.restaurant_id, task, candidates)
    if analysis is not None:
        merge_identity(identity, identity_from_analysis(analysis), prefer_display=True)
        candidates.update(value for value in (analysis.detected_uber_order_number, analysis.detected_display_id) if value)

    linked_row_identity = find_linked_import_row_identity(db, snapshot=snapshot, transaction=transaction)
    if linked_row_identity is not None:
        merge_identity(identity, linked_row_identity, prefer_display=True)

    if allow_import_fallback and identity_score(identity) < 5:
        row_identity = find_import_row_identity(db, order.restaurant_id, candidates)
        if row_identity is not None:
            merge_identity(identity, row_identity, prefer_display=True)

    return identity


def hydrate_order_identity_from_sources(
    db: Session,
    order: ClaimOrder,
    *,
    task: EvidenceRequestTask | None = None,
) -> bool:
    if task is not None:
        identity = resolve_identity_for_task(db, task)
    else:
        identity = resolve_identity_for_order(db, order)
    changed = False
    customer_name = clean_customer_name(identity.customer_name)
    if customer_name and not order.customer_name:
        order.customer_name = customer_name
        changed = True
    if identity.order_date and not order.order_date:
        order.order_date = identity.order_date
        changed = True
    if identity.order_time and not order.order_time:
        order.order_time = identity.order_time
        changed = True
    if identity.order_amount is not None and order.order_amount is None:
        order.order_amount = identity.order_amount
        changed = True
    return changed


def resolve_identity_for_order(
    db: Session,
    order: ClaimOrder,
    *,
    allow_import_fallback: bool = True,
) -> ResolvedOrderIdentity:
    task = db.scalar(
        select(EvidenceRequestTask)
        .where(EvidenceRequestTask.order_id == order.id)
        .order_by(EvidenceRequestTask.id.desc())
        .limit(1)
    )
    if task is not None:
        return resolve_identity_for_task(db, task, allow_import_fallback=allow_import_fallback)
    identity = ResolvedOrderIdentity(
        order_number=order.uber_order_number,
        customer_name=clean_customer_name(order.customer_name),
        order_date=order.order_date,
        order_time=order.order_time,
        order_amount=Decimal(str(order.order_amount)) if order.order_amount is not None else None,
        currency=order.currency,
        source="claim_order",
    )
    candidates = {order.uber_order_number}
    snapshot = find_snapshot(db, order.restaurant_id, candidates, None)
    if snapshot is not None:
        merge_identity(identity, identity_from_snapshot(snapshot), prefer_display=True)
    transaction = find_transaction(db, order.restaurant_id, candidates, None)
    if transaction is not None:
        merge_identity(identity, identity_from_transaction(transaction), prefer_display=True)
    linked_row_identity = find_linked_import_row_identity(db, snapshot=snapshot, transaction=transaction)
    if linked_row_identity is not None:
        merge_identity(identity, linked_row_identity, prefer_display=True)
    if allow_import_fallback and identity_score(identity) < 5:
        row_identity = find_import_row_identity(db, order.restaurant_id, candidates)
        if row_identity is not None:
            merge_identity(identity, row_identity, prefer_display=True)
    return identity


def candidate_numbers_for_task(task: EvidenceRequestTask) -> set[str]:
    values = {task.order.uber_order_number}
    values.update(candidate_numbers_from_payload(task.order.notes))
    values.update(candidate_numbers_from_payload(task.order.internal_reference))
    if task.customer_refund_dispute is not None:
        values.update(candidate_numbers_from_dispute(task.customer_refund_dispute))
    if task.reconciliation_result is not None:
        values.update(value for value in (task.reconciliation_result.uber_order_id, task.reconciliation_result.display_id) if value)
    return clean_candidates(values)


def candidate_numbers_from_dispute(dispute: UberCustomerRefundDispute) -> set[str]:
    values = {
        dispute.uber_order_id,
        dispute.display_id,
        dispute.customer_refund_reference,
    }
    values.update(candidate_numbers_from_payload(dispute.raw_payload_json))
    if dispute.financial_transaction is not None:
        values.add(dispute.financial_transaction.uber_order_id)
        values.update(candidate_numbers_from_payload(dispute.financial_transaction.raw_payload_json))
    return clean_candidates(values)


def find_snapshot(
    db: Session,
    restaurant_id: int,
    candidate_numbers: set[str],
    uber_store_id: str | None,
) -> UberOrderSnapshot | None:
    candidates = clean_candidates(candidate_numbers)
    if not candidates:
        return None
    statement = select(UberOrderSnapshot).where(
        UberOrderSnapshot.restaurant_id == restaurant_id,
        or_(UberOrderSnapshot.uber_order_id.in_(candidates), UberOrderSnapshot.display_id.in_(candidates)),
    )
    if uber_store_id:
        statement = statement.where(UberOrderSnapshot.uber_store_id == uber_store_id)
    snapshot = db.scalar(statement.order_by(UberOrderSnapshot.id.desc()).limit(1))
    if snapshot is not None:
        return snapshot
    rows = db.scalars(
        select(UberOrderSnapshot)
        .where(UberOrderSnapshot.restaurant_id == restaurant_id)
        .order_by(UberOrderSnapshot.id.desc())
        .limit(PAYLOAD_FALLBACK_SCAN_LIMIT)
    ).all()
    return first_payload_match(rows, candidates)


def find_transaction(
    db: Session,
    restaurant_id: int,
    candidate_numbers: set[str],
    dispute: UberCustomerRefundDispute | None,
) -> UberFinancialTransaction | None:
    candidates = clean_candidates(candidate_numbers)
    conditions = []
    if candidates:
        conditions.append(UberFinancialTransaction.uber_order_id.in_(candidates))
    if dispute is not None and dispute.financial_transaction_id is not None:
        conditions.append(UberFinancialTransaction.id == dispute.financial_transaction_id)
    if not conditions:
        return None
    transaction = db.scalar(
        select(UberFinancialTransaction)
        .where(UberFinancialTransaction.restaurant_id == restaurant_id, or_(*conditions))
        .order_by(UberFinancialTransaction.id.desc())
        .limit(1)
    )
    if transaction is not None:
        return transaction
    rows = db.scalars(
        select(UberFinancialTransaction)
        .where(UberFinancialTransaction.restaurant_id == restaurant_id)
        .order_by(UberFinancialTransaction.id.desc())
        .limit(PAYLOAD_FALLBACK_SCAN_LIMIT)
    ).all()
    return first_payload_match(rows, candidates)


def find_analysis(
    db: Session,
    restaurant_id: int,
    task: EvidenceRequestTask,
    candidate_numbers: set[str],
) -> EvidenceAnalysisResult | None:
    candidates = clean_candidates(candidate_numbers)
    conditions = []
    if candidates:
        conditions.extend(
            [
                EvidenceAnalysisResult.detected_uber_order_number.in_(candidates),
                EvidenceAnalysisResult.detected_display_id.in_(candidates),
            ]
        )
    candidate_pairs = [("claim_order", task.order_id), ("evidence_task", task.id)]
    if task.customer_refund_dispute_id:
        candidate_pairs.append(("customer_refund_dispute", task.customer_refund_dispute_id))
    if task.reconciliation_result_id:
        candidate_pairs.append(("reconciliation_result", task.reconciliation_result_id))
    linked_ids = select(EvidenceMatchCandidate.analysis_result_id).where(
        or_(
            *[
                (EvidenceMatchCandidate.candidate_type == candidate_type)
                & (EvidenceMatchCandidate.candidate_id == candidate_id)
                for candidate_type, candidate_id in candidate_pairs
                if candidate_id
            ]
        )
    )
    conditions.append(EvidenceAnalysisResult.id.in_(linked_ids))
    return db.scalar(
        select(EvidenceAnalysisResult)
        .join(EvidenceImportedFile)
        .join(EvidenceImportBatch)
        .where(
            or_(*conditions),
            or_(EvidenceImportBatch.restaurant_id == restaurant_id, EvidenceImportBatch.restaurant_id.is_(None)),
        )
        .order_by(
            EvidenceAnalysisResult.extraction_confidence.desc(),
            EvidenceAnalysisResult.matching_confidence.desc(),
            EvidenceAnalysisResult.id.desc(),
        )
        .limit(1)
    )


def find_import_row_identity(
    db: Session,
    restaurant_id: int,
    candidate_numbers: set[str],
) -> ResolvedOrderIdentity | None:
    candidates = clean_candidates(candidate_numbers)
    if not candidates:
        return None
    bind = db.get_bind()
    best: ResolvedOrderIdentity | None = None
    if bind is not None and bind.dialect.name != "sqlite":
        direct_conditions = [
            UberReportingImportRow.normalized_data[key].as_string().in_(candidates)
            for key in IMPORT_ROW_DIRECT_KEYS
        ]
        direct_rows = db.execute(
            select(UberReportingImportRow, UberReportingImportBatch)
            .join(UberReportingImportBatch, UberReportingImportRow.batch_id == UberReportingImportBatch.id)
            .where(
                UberReportingImportRow.status.in_(("created", "valid", "warning", "duplicate", "skipped", "invalid")),
                or_(*direct_conditions),
            )
            .order_by(UberReportingImportRow.id.desc())
            .limit(25)
        ).all()
        best = best_import_row_identity(direct_rows, candidates, restaurant_id)
        if best is not None and identity_score(best) >= 3:
            return best

    rows = db.execute(
        select(UberReportingImportRow, UberReportingImportBatch)
        .join(UberReportingImportBatch, UberReportingImportRow.batch_id == UberReportingImportBatch.id)
        .where(UberReportingImportRow.status.in_(("created", "valid", "warning", "duplicate", "skipped", "invalid")))
        .order_by(UberReportingImportRow.id.desc())
        .limit(IMPORT_ROW_IDENTITY_SCAN_LIMIT)
    ).all()
    return best_import_row_identity(rows, candidates, restaurant_id) or best


def find_linked_import_row_identity(
    db: Session,
    *,
    snapshot: UberOrderSnapshot | None,
    transaction: UberFinancialTransaction | None,
) -> ResolvedOrderIdentity | None:
    conditions = []
    if snapshot is not None:
        conditions.append(UberReportingImportRow.created_snapshot_id == snapshot.id)
    if transaction is not None:
        conditions.append(UberReportingImportRow.created_transaction_id == transaction.id)
    if not conditions:
        return None
    row = db.execute(
        select(UberReportingImportRow, UberReportingImportBatch)
        .join(UberReportingImportBatch, UberReportingImportRow.batch_id == UberReportingImportBatch.id)
        .where(
            UberReportingImportRow.status.in_(("created", "valid", "warning", "duplicate", "skipped", "invalid")),
            or_(*conditions),
        )
        .order_by(UberReportingImportRow.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    import_row, _batch = row
    return identity_from_import_row(import_row)


def best_import_row_identity(rows, candidates: set[str], restaurant_id: int) -> ResolvedOrderIdentity | None:
    best: ResolvedOrderIdentity | None = None
    best_score = -1
    for row, _batch in rows:
        payloads = [row.normalized_data or {}, row.raw_data or {}]
        if not any(payload_contains_candidate(payload, candidates) for payload in payloads):
            continue
        normalized_restaurant_id = (row.normalized_data or {}).get("restaurant_id")
        if str(normalized_restaurant_id or "").isdigit() and int(normalized_restaurant_id) != restaurant_id:
            continue
        identity = ResolvedOrderIdentity(source=f"uber_reporting_import_row:{row.id}")
        for payload in payloads:
            merge_identity(identity, identity_from_payload(payload, source=f"uber_reporting_import_row:{row.id}"), prefer_display=True)
        score = identity_score(identity)
        if score > best_score:
            best = identity
            best_score = score
        if score >= 5:
            return best
    return best


def identity_from_import_row(row: UberReportingImportRow) -> ResolvedOrderIdentity:
    identity = ResolvedOrderIdentity(source=f"uber_reporting_import_row:{row.id}")
    for payload in (row.normalized_data or {}, row.raw_data or {}):
        merge_identity(identity, identity_from_payload(payload, source=identity.source), prefer_display=True)
    return identity


def identity_from_snapshot(snapshot: UberOrderSnapshot) -> ResolvedOrderIdentity:
    identity = ResolvedOrderIdentity(
        order_number=snapshot.uber_order_id,
        display_id=snapshot.display_id,
        customer_name=clean_customer_name(snapshot.customer_name),
        order_date=snapshot.placed_at.date() if snapshot.placed_at else None,
        order_time=snapshot.placed_at.time().replace(microsecond=0) if snapshot.placed_at else None,
        order_amount=Decimal(str(snapshot.order_total_amount)) if snapshot.order_total_amount is not None else None,
        currency=snapshot.currency,
        source=f"uber_order_snapshot:{snapshot.id}",
    )
    merge_identity(identity, identity_from_payload(snapshot.raw_payload_json, source=identity.source), prefer_display=False)
    return identity


def identity_from_transaction(transaction: UberFinancialTransaction) -> ResolvedOrderIdentity:
    identity = identity_from_payload(transaction.raw_payload_json, source=f"uber_financial_transaction:{transaction.id}")
    if not identity.order_number:
        identity.order_number = transaction.uber_order_id
    if identity.order_date is None:
        identity.order_date = transaction.transaction_date
    if identity.order_amount is None:
        identity.order_amount = abs(Decimal(str(transaction.amount)))
    if identity.currency is None:
        identity.currency = transaction.currency
    return identity


def identity_from_dispute(dispute: UberCustomerRefundDispute) -> ResolvedOrderIdentity:
    identity = identity_from_payload(dispute.raw_payload_json, source=f"customer_refund_dispute:{dispute.id}")
    if not identity.order_number:
        identity.order_number = dispute.uber_order_id
    if not identity.display_id:
        identity.display_id = dispute.display_id
    if identity.order_date is None:
        identity.order_date = dispute.order_date
    if identity.order_amount is None:
        identity.order_amount = dispute.order_amount or dispute.customer_refund_amount
    if identity.currency is None:
        identity.currency = dispute.currency
    return identity


def identity_from_reconciliation_result(result) -> ResolvedOrderIdentity:
    identity = ResolvedOrderIdentity(
        order_number=result.uber_order_id,
        display_id=result.display_id,
        order_amount=result.order_amount or result.missing_amount,
        currency=result.currency,
        source=f"reconciliation_result:{result.id}",
    )
    if result.matched_snapshot is not None:
        merge_identity(identity, identity_from_snapshot(result.matched_snapshot), prefer_display=True)
    return identity


def identity_from_analysis(analysis: EvidenceAnalysisResult) -> ResolvedOrderIdentity:
    identity = ResolvedOrderIdentity(
        order_number=analysis.detected_uber_order_number,
        display_id=analysis.detected_display_id,
        order_date=analysis.detected_order_date,
        order_amount=Decimal(str(analysis.detected_order_amount)) if analysis.detected_order_amount is not None else None,
        currency=analysis.detected_currency,
        source=f"evidence_analysis:{analysis.id}",
    )
    merge_identity(identity, identity_from_payload(analysis.raw_result_json, source=identity.source), prefer_display=True)
    return identity


def identity_from_payload(payload: Any, *, source: str | None = None) -> ResolvedOrderIdentity:
    identity = ResolvedOrderIdentity(source=source)
    if not isinstance(payload, (dict, list)):
        return identity
    identity.order_number = payload_string_value(payload, ORDER_ID_KEYS)
    identity.display_id = payload_string_value(payload, DISPLAY_ID_KEYS)
    identity.customer_name = clean_customer_name(payload_string_value(payload, CUSTOMER_NAME_KEYS) or combined_customer_name(payload))
    identity.order_date = payload_date_value(payload, DATE_KEYS)
    identity.order_time = payload_time_value(payload, TIME_KEYS)
    amount = payload_decimal_value(payload, AMOUNT_KEYS)
    identity.order_amount = abs(amount) if amount is not None else None
    currency = payload_string_value(payload, {"currency", "devise", "code_de_devise"})
    identity.currency = currency[:3].upper() if currency else None
    return identity


def merge_identity(target: ResolvedOrderIdentity, source: ResolvedOrderIdentity | None, *, prefer_display: bool) -> None:
    if source is None:
        return
    if not target.customer_name and source.customer_name:
        target.customer_name = clean_customer_name(source.customer_name)
    if not target.order_date and source.order_date:
        target.order_date = source.order_date
    if not target.order_time and source.order_time:
        target.order_time = source.order_time
    if target.order_amount is None and source.order_amount is not None:
        target.order_amount = source.order_amount
    if not target.currency and source.currency:
        target.currency = source.currency
    if not target.order_number and source.order_number:
        target.order_number = source.order_number
    if prefer_display:
        if source.display_id and not is_uuid_like(source.display_id):
            target.display_id = source.display_id
        elif not target.display_id and source.display_id:
            target.display_id = source.display_id
    elif not target.display_id and source.display_id:
        target.display_id = source.display_id
    if source.source and (not target.source or identity_score(source) > identity_score(target)):
        target.source = source.source


def candidate_numbers_from_payload(payload: Any) -> set[str]:
    if not isinstance(payload, (dict, list, str)):
        return set()
    if isinstance(payload, str):
        return set(UUID_SEARCH_PATTERN.findall(payload)) | set(re.findall(r"\b[A-Z0-9][A-Z0-9-]{3,32}\b", payload.upper()))
    identity = identity_from_payload(payload)
    values = {identity.order_number, identity.display_id}
    for _key, value in iter_payload_items(payload):
        if isinstance(value, str):
            cleaned = value.strip()
            if UUID_LIKE_PATTERN.match(cleaned) or valid_identifier_candidate(cleaned):
                values.add(cleaned)
    return clean_candidates(values)


def payload_contains_candidate(payload: Any, candidates: set[str]) -> bool:
    normalized_candidates = {normalize_identifier(candidate) for candidate in candidates if candidate}
    for _key, value in iter_payload_items(payload):
        if value is None:
            continue
        normalized = normalize_identifier(str(value))
        if normalized in normalized_candidates:
            return True
    return False


def first_payload_match(rows, candidates: set[str]):
    for row in rows:
        if payload_contains_candidate(getattr(row, "raw_payload_json", None), candidates):
            return row
    return None


def payload_string_value(payload: Any, accepted_keys: set[str]) -> str | None:
    value = payload_value(payload, accepted_keys)
    if isinstance(value, str):
        return value.strip() or None
    if value is not None:
        return str(value).strip() or None
    return None


def payload_date_value(payload: Any, accepted_keys: set[str]) -> date | None:
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
            if "/" in parser_value and parser_value[:2].isdigit():
                day, month, year = re.split(r"[/-]", parser_value)
                return date(int(year), int(month), int(day))
            return date.fromisoformat(parser_value.replace("/", "-"))
        except (ValueError, IndexError):
            pass
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def payload_time_value(payload: Any, accepted_keys: set[str]) -> time | None:
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
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).time().replace(microsecond=0)
    except ValueError:
        pass
    for token in (cleaned[:8], cleaned[:5]):
        try:
            return time.fromisoformat(token).replace(microsecond=0)
        except ValueError:
            continue
    return None


def payload_decimal_value(payload: Any, accepted_keys: set[str]) -> Decimal | None:
    value = payload_value(payload, accepted_keys)
    if value is None:
        return None
    text = str(value).strip().replace(" ", "")
    for token in ("EUR", "eur", "€"):
        text = text.replace(token, "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def payload_value(payload: Any, accepted_keys: set[str]) -> Any | None:
    normalized_keys = {normalize_payload_key(key) for key in accepted_keys}
    for key, value in iter_payload_items(payload):
        if normalize_payload_key(key) in normalized_keys and value not in (None, ""):
            return value
    return None


def combined_customer_name(payload: Any) -> str | None:
    first = payload_string_value(payload, CUSTOMER_FIRST_NAME_KEYS)
    last = payload_string_value(payload, CUSTOMER_LAST_NAME_KEYS)
    if first and last and normalize_payload_key(first) != normalize_payload_key(last):
        return f"{first} {last}"
    return first or last


def iter_payload_items(value: Any):
    if isinstance(value, dict):
        for key, nested_value in value.items():
            yield str(key), nested_value
            yield from iter_payload_items(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from iter_payload_items(nested_value)


def normalize_payload_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return "_".join("".join(char if char.isalnum() else " " for char in ascii_value.lower()).split())


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def clean_candidates(values) -> set[str]:
    return {str(value).strip() for value in values if value and str(value).strip()}


def valid_identifier_candidate(value: str) -> bool:
    cleaned = normalize_identifier(value)
    if len(cleaned) < 5 or len(cleaned) > 40:
        return False
    return any(char.isdigit() for char in cleaned)


def clean_customer_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip(" -_:;,.")
    if len(cleaned) < 2:
        return None
    normalized = normalize_payload_key(cleaned)
    blocked = {"client", "customer", "eater", "nom_client", "commande", "order", "restaurant", "total", "eur"}
    if normalized in blocked:
        return None
    if re.fullmatch(r"\d+(?:[.,]\d+)?(?:_?(eur|euro|euros|percent|pourcent))?", normalized):
        return None
    if len([char for char in cleaned if char.isalpha()]) < 2:
        return None
    return cleaned[:80]


def is_uuid_like(value: str | None) -> bool:
    return bool(value and UUID_LIKE_PATTERN.match(value.strip()))


def identity_score(identity: ResolvedOrderIdentity) -> int:
    return sum(
        1
        for value in (
            identity.customer_name,
            identity.order_date,
            identity.order_time,
            identity.order_amount,
            identity.best_order_label,
        )
        if value
    )
