from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import unicodedata

from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import (
    ClaimOrder,
    EmailAccount,
    EvidenceRequestTask,
    GmailResponseAnalysis,
    GmailStarredWorkItem,
    GmailWatchedThread,
    InboundEmailMessage,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.email_provider import EmailProvider, EmailProviderError, InboundEmailPayload
from app.services.gmail_inbound_sync_service import (
    GMAIL_STARRED_URGENT_QUERIES,
    GmailInboundSyncResult,
    GmailInboundSyncService,
    starred_payload_identity_context,
)
from app.services.gmail_quota import parse_gmail_retry_after
from app.services.autopilot_identity_repair_service import find_or_create_order_from_starred_text

logger = logging.getLogger(__name__)

FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed", "manual_review", "skipped"}
SKIPPABLE_FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed"}
POSITIVE_REVIEW_TYPES = {"accepted", "payment_to_verify", "payment_confirmed"}
REFUSAL_REVIEW_TYPES = {"refused"}
EVIDENCE_REVIEW_TYPES = {"evidence_requested", "information_requested"}
FAST_POSITIVE_MARKERS = (
    "paiement accorde",
    "paiement a ete accorde",
    "remboursement accorde",
    "remboursement a ete accorde",
    "est accorde",
    "regularisation",
    "sera verse",
    "a ete credite",
    "payment approved",
    "refund approved",
    "we have credited",
    "we will credit",
)
FAST_REFUSAL_MARKERS = (
    "maintenons le refus",
    "refus",
    "refuse",
    "refused",
    "denied",
    "declined",
    "pas de remboursement",
    "aucun remboursement",
    "ne pouvons pas rembourser",
    "not eligible",
    "no refund",
)
FAST_EVIDENCE_MARKERS = (
    "preuve",
    "justificatif",
    "piece jointe",
    "document",
    "photo",
    "information supplementaire",
    "fournir",
    "provide evidence",
    "additional information",
)


@dataclass
class GmailWatchedThreadMonitorResult:
    status: str = "success"
    watched_threads_seen: int = 0
    watched_threads_created: int = 0
    new_messages_detected: int = 0
    work_items_created: int = 0
    processed_messages: int = 0
    positive_responses: int = 0
    payment_confirmed: int = 0
    refused_responses: int = 0
    actionable_refused_threads: int = 0
    evidence_requests: int = 0
    manual_reviews: int = 0
    autopilot_sent_count: int = 0
    autopilot_skipped_count: int = 0
    autopilot_failed_count: int = 0
    errors: list[str] = field(default_factory=list)


class GmailWatchedThreadMonitorService:
    """Track every Gmail thread once any message in that thread is starred.

    The star is a discovery signal. After that, the thread id is the source of
    truth, because later Uber replies are often not individually starred.
    """

    def __init__(
        self,
        provider: EmailProvider,
        *,
        settings: Settings | None = None,
        sync_service: GmailInboundSyncService | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self.sync_service = sync_service or GmailInboundSyncService(provider)

    def process_account(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        max_threads: int | None = None,
        discover_starred: bool = True,
        discover_full_history: bool = True,
        starred_discovery_max_messages: int | None = None,
        process_new_messages: bool | None = None,
    ) -> GmailWatchedThreadMonitorResult:
        result = GmailWatchedThreadMonitorResult()
        if not self.settings.gmail_watched_threads_enabled:
            result.status = "disabled"
            return result

        if process_new_messages is None:
            process_new_messages = self.settings.gmail_watched_threads_process_new_messages

        if process_new_messages:
            self.process_watched_threads(db, user, account, result=result, max_threads=max_threads)

        if discover_starred:
            self.discover_from_starred_messages(
                db,
                user,
                account,
                result=result,
                use_full_history=discover_full_history,
                max_messages=starred_discovery_max_messages,
            )
            if process_new_messages and result.watched_threads_created:
                self.process_watched_threads(
                    db,
                    user,
                    account,
                    result=result,
                    max_threads=max_threads,
                    process_local_backlog=False,
                )

        if not process_new_messages:
            return result

        return result

    def process_watched_threads(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        result: GmailWatchedThreadMonitorResult | None = None,
        max_threads: int | None = None,
        process_local_backlog: bool = True,
    ) -> GmailWatchedThreadMonitorResult:
        result = result or GmailWatchedThreadMonitorResult()

        max_per_cycle = max_threads or self.settings.gmail_watched_threads_max_per_cycle
        sync_result = GmailInboundSyncResult(status="success")
        local_processed = (
            self.process_pending_local_work_items(
                db,
                user,
                account,
                result=result,
                sync_result=sync_result,
                max_items=max_per_cycle,
            )
            if process_local_backlog
            else 0
        )
        remaining_thread_budget = max(max_per_cycle - local_processed, 0)
        if remaining_thread_budget <= 0:
            active_threads: list[GmailWatchedThread] = []
        else:
            active_threads = self.get_active_watched_threads(db, account, max_per_cycle=remaining_thread_budget)
        result.watched_threads_seen += len(active_threads)
        order_identifier_index = (
            self.sync_service.build_order_identifier_index(db, user) if active_threads else {}
        )

        for watched in active_threads:
            try:
                payloads = self.fetch_thread_payloads(db, account, watched)
            except Exception as exc:  # noqa: BLE001 - a broken thread must not stop the mailbox cycle.
                retry_after = parse_gmail_retry_after(
                    str(exc),
                    safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
                )
                if retry_after is not None:
                    result.errors.append(f"gmail_quota_retry_after:{retry_after.isoformat()}")
                    break
                logger.exception("Unable to fetch watched Gmail thread %s", watched.gmail_thread_id)
                result.errors.append(f"thread:{watched.gmail_thread_id}:{str(exc)[:160]}")
                watched.status = "manual_review"
                watched.last_processed_at = utc_now()
                continue

            processing_payloads = self.select_payloads_for_processing(payloads, account)
            if self.should_skip_already_final_payloads(db, account, processing_payloads):
                watched.last_processed_at = utc_now()
                db.flush()
                continue

            # Keep the hot Gmail worker path cheap. Thousands of starred legacy
            # threads can be unlinked; trying to repair identity for each one
            # before classification makes the queue look idle for minutes. Linked
            # threads still use the full response pipeline below, while unlinked
            # threads are classified immediately and remain actionable/visible.
            thread_order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else None
            for payload in processing_payloads:
                if not payload.provider_message_id:
                    continue
                message = self.upsert_inbound_message(
                    db,
                    user,
                    account,
                    payload,
                    order_identifier_index=order_identifier_index,
                    sync_result=sync_result,
                )
                if thread_order is not None and message.order_id is None:
                    self.sync_service.record_linked_message(
                        db,
                        user,
                        message,
                        thread_order,
                        match_reason="order_number_match",
                    )
                    message.review_status = "unreviewed"
                    message.reviewed_at = None
                    message.reviewed_by_user_id = None
                    sync_result.linked_messages += 1
                if not message.provider_thread_id:
                    continue
                work_item, created = self.ensure_work_item(db, watched, account, message)
                if created:
                    result.work_items_created += 1
                    result.new_messages_detected += 1
                if (
                    work_item.status in FINAL_WORK_ITEM_STATUSES
                    and not self.message_changed_after_processing(message, work_item)
                    and not self.should_reprocess_final_item(watched, work_item, message)
                ):
                    continue

                if thread_order is None and message.match_status != "linked":
                    self.process_unlinked_watched_message_fast(db, user, message, sync_result)
                else:
                    self.sync_service.reprocess_existing_message(
                        db,
                        user,
                        account,
                        message,
                        sync_result,
                        apply_reviews=True,
                        payload=payload,
                    )
                self.update_work_item_status(db, user, watched, work_item, message, result)
                result.processed_messages += 1

            watched.last_processed_at = utc_now()
            db.flush()

        result.actionable_refused_threads = self.count_actionable_refused_threads(db, account)

        if (
            (sync_result.negative_responses_detected or result.actionable_refused_threads)
            and self.settings.gmail_inbound_auto_sync_run_autopilot
        ):
            self.sync_service.run_autopilot_for_negative_responses(db, user, sync_result)
            result.autopilot_sent_count += sync_result.autopilot_sent_count
            result.autopilot_skipped_count += sync_result.autopilot_skipped_count
            result.autopilot_failed_count += sync_result.autopilot_failed_count
        result.errors.extend(sync_result.errors)
        return result

    def process_pending_local_work_items(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        result: GmailWatchedThreadMonitorResult,
        sync_result: GmailInboundSyncResult,
        max_items: int,
    ) -> int:
        """Process already-synced Gmail backlog before making remote Gmail calls.

        Large mailboxes can have thousands of starred work items already stored
        locally. Those must move first; otherwise each cycle spends time fetching
        Gmail threads while the visible queue still looks stuck at zero.
        """
        items = list(
            db.scalars(
                select(GmailStarredWorkItem)
                .options(
                    selectinload(GmailStarredWorkItem.watched_thread),
                    selectinload(GmailStarredWorkItem.inbound_message).selectinload(InboundEmailMessage.order),
                )
                .join(
                    GmailWatchedThread,
                    GmailWatchedThread.id == GmailStarredWorkItem.watched_thread_id,
                )
                .where(
                    GmailStarredWorkItem.email_account_id == account.id,
                    GmailStarredWorkItem.inbound_message_id.is_not(None),
                    GmailStarredWorkItem.status.in_(["pending", "processing", "failed"]),
                    GmailWatchedThread.status.in_(["active", "manual_review"]),
                    GmailWatchedThread.star_active.is_(True),
                )
                .order_by(
                    GmailStarredWorkItem.processed_at.asc().nullsfirst(),
                    GmailStarredWorkItem.id.asc(),
                )
                .limit(max_items)
            ).all()
        )
        for item in items:
            watched = item.watched_thread
            message = item.inbound_message
            if watched is None or message is None:
                item.status = "failed"
                item.reason = "missing_local_message"
                item.processed_at = utc_now()
                continue
            item.status = "processing"
            thread_order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else None
            if thread_order is None and message.match_status != "linked":
                self.process_unlinked_watched_message_fast(db, user, message, sync_result)
            else:
                self.sync_service.reprocess_existing_message(
                    db,
                    user,
                    account,
                    message,
                    sync_result,
                    apply_reviews=True,
                    payload=inbound_payload_from_message(message),
                )
            self.update_work_item_status(db, user, watched, item, message, result)
            result.processed_messages += 1
            watched.last_processed_at = utc_now()
            db.flush()
        if items:
            result.watched_threads_seen += len({item.watched_thread_id for item in items if item.watched_thread_id})
        return len(items)

    def should_skip_already_final_payloads(
        self,
        db: Session,
        account: EmailAccount,
        payloads: list[InboundEmailPayload],
    ) -> bool:
        """Avoid re-running expensive identity repair on already classified replies.

        Gmail thread polling can revisit the same latest Uber reply many times.
        Refused replies remain actionable through `count_actionable_refused_threads`
        and AutoPilot, so reprocessing the same immutable Gmail message only slows
        down the backlog.
        """
        if len(payloads) != 1:
            return False
        provider_message_id = payloads[0].provider_message_id
        if not provider_message_id:
            return False
        item = db.scalar(
            select(GmailStarredWorkItem).where(
                GmailStarredWorkItem.email_account_id == account.id,
                GmailStarredWorkItem.provider_message_id == provider_message_id,
            )
        )
        return bool(item and item.status in SKIPPABLE_FINAL_WORK_ITEM_STATUSES)

    def select_payloads_for_processing(
        self,
        payloads: list[InboundEmailPayload],
        account: EmailAccount,
    ) -> list[InboundEmailPayload]:
        """Keep watched-thread cycles focused on Uber's latest answer.

        The whole thread is fetched so identity repair can read past context.
        Processing every old sent/received message is expensive and causes the
        backlog to crawl. For the automation decision, the newest external
        message is the useful one: positive, refusal, proof request, or unknown.
        """
        deduped: dict[str, InboundEmailPayload] = {}
        for payload in payloads:
            if not payload.provider_message_id:
                continue
            deduped[payload.provider_message_id] = payload
        candidates = [
            payload
            for payload in deduped.values()
            if not self.payload_from_account(payload, account)
        ]
        if not candidates:
            return []
        _index, latest = max(
            enumerate(candidates),
            key=lambda item: (item[1].received_at or datetime.min, item[0]),
        )
        return [latest]

    def discover_from_starred_messages(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        result: GmailWatchedThreadMonitorResult | None = None,
        use_full_history: bool = True,
        max_messages: int | None = None,
    ) -> GmailWatchedThreadMonitorResult:
        result = result or GmailWatchedThreadMonitorResult()
        if not self.settings.gmail_watched_threads_enabled:
            result.status = "disabled"
            return result

        list_refs_for_account = getattr(self.provider, "list_message_refs_for_account", None)
        if callable(list_refs_for_account):
            return self.discover_from_starred_message_refs(
                db,
                account,
                result=result,
                max_messages=max_messages,
            )

        refreshed_payloads: list[InboundEmailPayload] = []
        try:
            refreshed_payloads = self.sync_service.fetch_starred_payloads_for_queries(
                db,
                user,
                account,
                queries=GMAIL_STARRED_URGENT_QUERIES,
                fallback_max_messages=max_messages or self.settings.gmail_starred_max_messages_per_sync,
                use_full_history=use_full_history,
            )
        except EmailProviderError as exc:
            retry_after = parse_gmail_retry_after(
                exc.message,
                safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
            )
            if retry_after is not None:
                result.errors.append(f"gmail_quota_retry_after:{retry_after.isoformat()}")
                return result
            result.errors.append(f"starred_discovery:{exc.message}")
        except Exception as exc:  # noqa: BLE001 - dashboard discovery must remain best-effort.
            retry_after = parse_gmail_retry_after(
                str(exc),
                safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
            )
            if retry_after is not None:
                result.errors.append(f"gmail_quota_retry_after:{retry_after.isoformat()}")
                return result
            result.errors.append(f"starred_discovery:{str(exc)[:160]}")

        order_identifier_index = self.sync_service.build_order_identifier_index(db, user)
        sync_result = GmailInboundSyncResult(status="success")
        for payload in refreshed_payloads:
            if not payload.provider_message_id or not payload.provider_thread_id:
                continue
            message = self.upsert_inbound_message(
                db,
                user,
                account,
                payload,
                order_identifier_index=order_identifier_index,
                sync_result=sync_result,
            )
            self.sync_service.reprocess_existing_message(
                db,
                user,
                account,
                message,
                sync_result,
                apply_reviews=True,
                payload=payload,
            )
            watched, created = self.ensure_watched_thread(db, account, message)
            if created:
                result.watched_threads_created += 1
            result.watched_threads_seen += 1
            _, item_created = self.ensure_work_item(db, watched, account, message)
            if item_created:
                result.work_items_created += 1
                result.new_messages_detected += 1

        labels_text = cast(InboundEmailMessage.provider_labels_json, String)
        starred_messages = list(
            db.scalars(
                select(InboundEmailMessage)
                .where(
                    InboundEmailMessage.email_account_id == account.id,
                    InboundEmailMessage.provider == "gmail",
                    InboundEmailMessage.provider_thread_id.is_not(None),
                    labels_text.ilike("%STARRED%"),
                )
                .order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
                .limit(self.settings.gmail_watched_threads_max_per_cycle)
            ).all()
        )
        for message in starred_messages:
            watched, created = self.ensure_watched_thread(db, account, message)
            if created:
                result.watched_threads_created += 1
            result.watched_threads_seen += 1
            _, item_created = self.ensure_work_item(db, watched, account, message)
            if item_created:
                result.work_items_created += 1
                result.new_messages_detected += 1

        result.errors.extend(sync_result.errors)
        db.flush()
        return result

    def discover_from_starred_message_refs(
        self,
        db: Session,
        account: EmailAccount,
        *,
        result: GmailWatchedThreadMonitorResult | None = None,
        max_messages: int | None = None,
    ) -> GmailWatchedThreadMonitorResult:
        """Discover starred Gmail threads with message references only.

        This is intentionally separate from payload processing. For large
        mailboxes, queue discovery must stay cheap so TENNET can register all
        starred threads first, then process the actual conversations in bounded
        cycles.
        """
        result = result or GmailWatchedThreadMonitorResult()
        list_refs_for_account = getattr(self.provider, "list_message_refs_for_account", None)
        if not callable(list_refs_for_account):
            return result

        max_results = max_messages or self.settings.gmail_starred_max_messages_per_sync
        seen_message_ids: set[str] = set()
        refs: list[dict[str, str]] = []
        for query in GMAIL_STARRED_URGENT_QUERIES:
            try:
                query_refs = list(
                    list_refs_for_account(
                        db,
                        account,
                        query=query,
                        max_results=max_results,
                    )
                )
            except EmailProviderError as exc:
                retry_after = parse_gmail_retry_after(
                    exc.message,
                    safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
                )
                if retry_after is not None:
                    result.errors.append(f"gmail_quota_retry_after:{retry_after.isoformat()}")
                    return result
                result.errors.append(f"starred_discovery_refs:{exc.message}")
                continue
            except Exception as exc:  # noqa: BLE001 - one query variant must not stop discovery.
                retry_after = parse_gmail_retry_after(
                    str(exc),
                    safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
                )
                if retry_after is not None:
                    result.errors.append(f"gmail_quota_retry_after:{retry_after.isoformat()}")
                    return result
                result.errors.append(f"starred_discovery_refs:{str(exc)[:160]}")
                continue
            for ref in query_refs:
                message_id = str(ref.get("id") or "")
                thread_id = str(ref.get("threadId") or "")
                if not message_id or not thread_id or message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                refs.append({"id": message_id, "threadId": thread_id})
            if refs:
                break

        for ref in refs:
            watched, created = self.ensure_watched_thread_ref(
                db,
                account,
                gmail_thread_id=ref["threadId"],
                provider_message_id=ref["id"],
            )
            if created:
                result.watched_threads_created += 1
            result.watched_threads_seen += 1
            _, item_created = self.ensure_work_item_ref(
                db,
                watched,
                account,
                provider_message_id=ref["id"],
            )
            if item_created:
                result.work_items_created += 1
                result.new_messages_detected += 1

        db.flush()
        return result

    def count_actionable_refused_threads(self, db: Session, account: EmailAccount) -> int:
        return int(
            db.scalar(
                select(func.count(func.distinct(GmailWatchedThread.id)))
                .join(
                    GmailStarredWorkItem,
                    GmailStarredWorkItem.watched_thread_id == GmailWatchedThread.id,
                )
                .where(
                    GmailWatchedThread.email_account_id == account.id,
                    GmailWatchedThread.status == "active",
                    GmailWatchedThread.star_active.is_(True),
                    GmailStarredWorkItem.status == "refused",
                )
            )
            or 0
        )

    def get_active_watched_threads(
        self,
        db: Session,
        account: EmailAccount,
        *,
        max_per_cycle: int,
    ) -> list[GmailWatchedThread]:
        return list(
            db.scalars(
                select(GmailWatchedThread)
                .options(selectinload(GmailWatchedThread.claim_order))
                .where(
                    GmailWatchedThread.email_account_id == account.id,
                    GmailWatchedThread.status.in_(["active", "manual_review"]),
                    GmailWatchedThread.star_active.is_(True),
                )
                .order_by(
                    GmailWatchedThread.last_processed_at.asc().nullsfirst(),
                    GmailWatchedThread.last_message_at.desc().nullslast(),
                    GmailWatchedThread.id.asc(),
                )
                .limit(max_per_cycle)
            ).all()
        )

    def fetch_thread_payloads(
        self,
        db: Session,
        account: EmailAccount,
        watched: GmailWatchedThread,
    ) -> list[InboundEmailPayload]:
        get_latest_external_message = getattr(self.provider, "get_latest_external_thread_message_for_account", None)
        if watched.claim_order_id is None and callable(get_latest_external_message):
            latest_payload = get_latest_external_message(db, account, watched.gmail_thread_id)
            if latest_payload is not None:
                return [latest_payload]

        get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
        if watched.claim_order_id is None and callable(get_thread_messages):
            try:
                payloads = list(get_thread_messages(db, account, watched.gmail_thread_id, include_attachments=False))
            except TypeError:
                payloads = list(get_thread_messages(db, account, watched.gmail_thread_id))
            if payloads:
                return payloads

        if callable(get_latest_external_message):
            latest_payload = get_latest_external_message(db, account, watched.gmail_thread_id)
            if latest_payload is not None:
                return [latest_payload]

        if callable(get_thread_messages):
            try:
                return list(get_thread_messages(db, account, watched.gmail_thread_id, include_attachments=False))
            except TypeError:
                return list(get_thread_messages(db, account, watched.gmail_thread_id))
        return [
            inbound_payload_from_message(message)
            for message in db.scalars(
                select(InboundEmailMessage).where(
                    InboundEmailMessage.email_account_id == account.id,
                    InboundEmailMessage.provider_thread_id == watched.gmail_thread_id,
                )
            ).all()
        ]

    def repair_watched_thread_from_payloads(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        payloads: list[InboundEmailPayload],
    ) -> ClaimOrder | None:
        if watched.claim_order_id:
            return db.get(ClaimOrder, watched.claim_order_id)
        context = watched_thread_identity_context(payloads)
        if not context:
            return None
        order = find_or_create_order_from_starred_text(db, user, context)
        if order is None:
            return None
        watched.claim_order_id = order.id
        watched.linked_case_type = "claim_order"
        watched.linked_case_id = order.id
        watched.status = "active"
        watched.star_active = True
        db.flush()
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.linked_from_thread_text",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "claim_order_id": order.id,
            },
        )
        return order

    def process_unlinked_watched_message_fast(
        self,
        db: Session,
        user: User,
        message: InboundEmailMessage,
        sync_result: GmailInboundSyncResult,
    ) -> None:
        """Classify unlinked watched replies without the expensive linking pipeline.

        Starred Gmail backlogs can contain thousands of already-sent disputes.
        If TENNET cannot link the thread immediately, it still must classify the
        newest Uber reply fast so the thread remains actionable instead of
        blocking the worker cycle for minutes.
        """
        review_type, reason, confidence = classify_unlinked_watched_message(message)
        analysis = message.response_analysis
        if analysis is None:
            analysis = GmailResponseAnalysis(
                inbound_message_id=message.id,
                order_id=message.order_id,
                recommended_review_type=review_type,
                status="manual_review" if review_type == "manual_review" else "analyzed",
                confidence_score=confidence,
                reason=reason,
            )
            db.add(analysis)
        else:
            analysis.order_id = message.order_id
            analysis.recommended_review_type = review_type
            analysis.status = "manual_review" if review_type == "manual_review" else "analyzed"
            analysis.confidence_score = confidence
            analysis.reason = reason
        analysis.analyzed_by_user_id = user.id
        analysis.notes = "Fast Gmail watched-thread classification before case linking."
        message.review_status = "reviewed"
        message.reviewed_at = utc_now()
        message.reviewed_by_user_id = user.id
        sync_result.analyzed_messages += 1
        if review_type == "refused":
            sync_result.negative_responses_detected += 1
        db.flush()

    def should_reprocess_final_item(
        self,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
    ) -> bool:
        if item.status not in {"manual_review", "skipped"}:
            return False
        return bool(
            watched.claim_order_id
            and message.match_status == "linked"
            and message.review_status == "unreviewed"
        )

    def upsert_inbound_message(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        payload: InboundEmailPayload,
        *,
        order_identifier_index,
        sync_result: GmailInboundSyncResult,
    ) -> InboundEmailMessage:
        existing_message = self.sync_service.get_existing_message(db, account, payload.provider_message_id)
        if existing_message is not None:
            self.sync_service.refresh_existing_message_from_payload(db, user, existing_message, payload)
            return existing_message
        try:
            with db.begin_nested():
                message = self.sync_service.create_inbound_message(
                    db,
                    user,
                    account,
                    payload,
                    order_identifier_index=order_identifier_index,
                )
        except IntegrityError:
            existing_message = self.sync_service.get_existing_message(db, account, payload.provider_message_id)
            if existing_message is None:
                raise
            self.sync_service.refresh_existing_message_from_payload(db, user, existing_message, payload)
            return existing_message
        sync_result.synced_messages += 1
        if message.match_status == "linked":
            sync_result.linked_messages += 1
        elif message.match_status == "ignored":
            sync_result.ignored_messages += 1
        else:
            sync_result.unlinked_messages += 1
        return message

    def ensure_watched_thread(
        self,
        db: Session,
        account: EmailAccount,
        message: InboundEmailMessage,
    ) -> tuple[GmailWatchedThread, bool]:
        thread_id = message.provider_thread_id
        if not thread_id:
            raise ValueError("Cannot watch Gmail message without provider_thread_id")
        watched = db.scalar(
            select(GmailWatchedThread).where(
                GmailWatchedThread.email_account_id == account.id,
                GmailWatchedThread.gmail_thread_id == thread_id,
            )
        )
        created = False
        if watched is None:
            watched = GmailWatchedThread(
                email_account_id=account.id,
                gmail_thread_id=thread_id,
                first_starred_message_id=message.provider_message_id,
                status="active",
                star_active=True,
            )
            db.add(watched)
            created = True
        elif watched.status in {"closed", "paused"} and self.labels_include_starred(message.provider_labels_json):
            watched.status = "active"
            watched.star_active = True
        if not watched.first_starred_message_id and self.labels_include_starred(message.provider_labels_json):
            watched.first_starred_message_id = message.provider_message_id
        self.update_watched_links_from_message(watched, message)
        db.flush()
        return watched, created

    def ensure_watched_thread_ref(
        self,
        db: Session,
        account: EmailAccount,
        *,
        gmail_thread_id: str,
        provider_message_id: str,
    ) -> tuple[GmailWatchedThread, bool]:
        watched = db.scalar(
            select(GmailWatchedThread).where(
                GmailWatchedThread.email_account_id == account.id,
                GmailWatchedThread.gmail_thread_id == gmail_thread_id,
            )
        )
        created = False
        if watched is None:
            watched = GmailWatchedThread(
                email_account_id=account.id,
                gmail_thread_id=gmail_thread_id,
                first_starred_message_id=provider_message_id,
                status="active",
                star_active=True,
            )
            nested = db.begin_nested()
            try:
                db.add(watched)
                db.flush()
                nested.commit()
                created = True
            except IntegrityError:
                nested.rollback()
                watched = db.scalar(
                    select(GmailWatchedThread).where(
                        GmailWatchedThread.email_account_id == account.id,
                        GmailWatchedThread.gmail_thread_id == gmail_thread_id,
                    )
                )
                if watched is None:
                    raise
        elif watched.status in {"closed", "paused"}:
            watched.status = "active"
            watched.star_active = True
        if not watched.first_starred_message_id:
            watched.first_starred_message_id = provider_message_id
        watched.star_active = True
        db.flush()
        return watched, created

    def ensure_work_item(
        self,
        db: Session,
        watched: GmailWatchedThread,
        account: EmailAccount,
        message: InboundEmailMessage,
    ) -> tuple[GmailStarredWorkItem, bool]:
        item = db.scalar(
            select(GmailStarredWorkItem).where(
                GmailStarredWorkItem.email_account_id == account.id,
                GmailStarredWorkItem.provider_message_id == message.provider_message_id,
            )
        )
        created = False
        if item is None:
            item = GmailStarredWorkItem(
                watched_thread_id=watched.id,
                email_account_id=account.id,
                inbound_message_id=message.id,
                gmail_thread_id=watched.gmail_thread_id,
                provider_message_id=message.provider_message_id,
                status="pending",
            )
            nested = db.begin_nested()
            try:
                db.add(item)
                db.flush()
                nested.commit()
                created = True
            except IntegrityError:
                nested.rollback()
                item = db.scalar(
                    select(GmailStarredWorkItem).where(
                        GmailStarredWorkItem.email_account_id == account.id,
                        GmailStarredWorkItem.provider_message_id == message.provider_message_id,
                    )
                )
                if item is None:
                    raise
                created = False
        else:
            if item.watched_thread_id is None or item.gmail_thread_id == watched.gmail_thread_id:
                item.watched_thread_id = watched.id
                item.gmail_thread_id = watched.gmail_thread_id
            if item.inbound_message_id is None:
                item.inbound_message_id = message.id
        return item, created

    def ensure_work_item_ref(
        self,
        db: Session,
        watched: GmailWatchedThread,
        account: EmailAccount,
        *,
        provider_message_id: str,
    ) -> tuple[GmailStarredWorkItem, bool]:
        item = db.scalar(
            select(GmailStarredWorkItem).where(
                GmailStarredWorkItem.email_account_id == account.id,
                GmailStarredWorkItem.provider_message_id == provider_message_id,
            )
        )
        created = False
        if item is None:
            item = GmailStarredWorkItem(
                watched_thread_id=watched.id,
                email_account_id=account.id,
                inbound_message_id=None,
                gmail_thread_id=watched.gmail_thread_id,
                provider_message_id=provider_message_id,
                status="pending",
            )
            nested = db.begin_nested()
            try:
                db.add(item)
                db.flush()
                nested.commit()
                created = True
            except IntegrityError:
                nested.rollback()
                item = db.scalar(
                    select(GmailStarredWorkItem).where(
                        GmailStarredWorkItem.email_account_id == account.id,
                        GmailStarredWorkItem.provider_message_id == provider_message_id,
                    )
                )
                if item is None:
                    raise
                created = False
        else:
            item.watched_thread_id = watched.id
            item.gmail_thread_id = watched.gmail_thread_id
        return item, created

    def update_watched_links_from_message(
        self,
        watched: GmailWatchedThread,
        message: InboundEmailMessage,
    ) -> None:
        if message.order_id:
            watched.claim_order_id = message.order_id
            watched.linked_case_type = "claim_order"
            watched.linked_case_id = message.order_id
            order = message.order
            if order and order.customer_refund_disputes:
                watched.customer_refund_dispute_id = order.customer_refund_disputes[0].id
            if order and order.appeal_workflows:
                watched.appeal_workflow_id = order.appeal_workflows[0].id
        if message.gmail_history_id:
            watched.last_seen_history_id = message.gmail_history_id
        if message.received_at and datetime_after(message.received_at, watched.last_message_at):
            watched.last_message_at = message.received_at
        if self.labels_include_starred(message.provider_labels_json):
            watched.star_active = True

    def update_work_item_status(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
        result: GmailWatchedThreadMonitorResult,
    ) -> None:
        self.update_watched_links_from_message(watched, message)
        analysis = message.response_analysis
        if analysis is None and message.id is not None:
            analysis = db.scalar(
                select(GmailResponseAnalysis)
                .where(GmailResponseAnalysis.inbound_message_id == message.id)
                .order_by(GmailResponseAnalysis.id.desc())
            )
        review_type = analysis.recommended_review_type if analysis else None
        item.inbound_message_id = message.id
        item.processed_at = utc_now()
        watched.last_processed_at = item.processed_at
        if review_type in POSITIVE_REVIEW_TYPES:
            item.status = "positive"
            item.reason = review_type
            watched.status = "payment_confirmed" if review_type == "payment_confirmed" else "positive"
            result.positive_responses += 1
            if review_type == "payment_confirmed":
                result.payment_confirmed += 1
            self.remove_thread_star(db, user, watched)
        elif review_type in REFUSAL_REVIEW_TYPES:
            item.status = "refused"
            item.reason = "uber_refusal"
            watched.status = "active"
            watched.star_active = True
            result.refused_responses += 1
        elif review_type in EVIDENCE_REVIEW_TYPES:
            item.status = "evidence_needed"
            item.reason = "evidence_requested"
            watched.status = "active"
            watched.star_active = True
            result.evidence_requests += 1
            self.ensure_evidence_request_task(db, user, message)
        elif message.match_status == "ignored":
            item.status = "skipped"
            item.reason = "ignored_sender"
        elif analysis is not None:
            item.status = "manual_review"
            item.reason = analysis.reason or review_type or "manual_review"
            watched.status = "manual_review"
            result.manual_reviews += 1
        else:
            item.status = "processed"
            item.reason = "no_actionable_response"
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.message_processed",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "provider_message_id": message.provider_message_id,
                "work_item_status": item.status,
                "review_type": review_type,
            },
        )

    def remove_thread_star(self, db: Session, user: User, watched: GmailWatchedThread) -> None:
        if not watched.first_starred_message_id:
            watched.star_active = False
            return
        remover = getattr(self.provider, "remove_message_label_for_account", None)
        if callable(remover):
            try:
                account = db.get(EmailAccount, watched.email_account_id)
                if account is not None:
                    remover(db, account, watched.first_starred_message_id, "STARRED")
            except Exception as exc:  # noqa: BLE001 - payment accounting must not fail on label cleanup.
                logger.warning("Unable to remove Gmail star for watched thread %s: %s", watched.id, exc)
        labels_text = cast(InboundEmailMessage.provider_labels_json, String)
        starred_messages = list(
            db.scalars(
                select(InboundEmailMessage).where(
                    InboundEmailMessage.email_account_id == watched.email_account_id,
                    InboundEmailMessage.provider_thread_id == watched.gmail_thread_id,
                    labels_text.ilike("%STARRED%"),
                )
            ).all()
        )
        for message in starred_messages:
            labels = [label for label in (message.provider_labels_json or []) if str(label).upper() != "STARRED"]
            message.provider_labels_json = labels
        watched.star_active = False
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.star_removed_after_positive",
            user_id=user.id,
            new_value={"gmail_thread_id": watched.gmail_thread_id},
        )

    def ensure_evidence_request_task(self, db: Session, user: User, message: InboundEmailMessage) -> None:
        if message.order_id is None:
            return
        order = db.get(ClaimOrder, message.order_id)
        if order is None:
            return
        existing = db.scalar(
            select(EvidenceRequestTask).where(
                EvidenceRequestTask.order_id == order.id,
                EvidenceRequestTask.task_type == "evidence_review",
                EvidenceRequestTask.status == "pending",
            )
        )
        if existing is not None:
            return
        db.add(
            EvidenceRequestTask(
                order_id=order.id,
                restaurant_id=order.restaurant_id,
                task_type="evidence_review",
                required_evidence_type="other",
                status="pending",
                priority="urgent",
                title="Preuve demandee par Uber",
                description="Uber demande une precision ou une preuve complementaire dans un fil Gmail surveille.",
                reason="gmail_watched_thread_evidence_request",
                created_by_user_id=user.id,
            )
        )

    @staticmethod
    def labels_include_starred(labels: list[str] | None) -> bool:
        return "STARRED" in {str(label).strip().upper() for label in labels or []}

    @staticmethod
    def payload_from_account(payload: InboundEmailPayload, account: EmailAccount) -> bool:
        account_email = (account.email_address or "").strip().lower()
        from_email = (payload.from_email or "").strip().lower()
        return bool(account_email and account_email in from_email)

    @staticmethod
    def message_changed_after_processing(message: InboundEmailMessage, item: GmailStarredWorkItem) -> bool:
        if item.processed_at is None:
            return True
        if message.updated_at is None:
            return False
        return datetime_after(message.updated_at, item.processed_at)


def watched_thread_identity_context(payloads: list[InboundEmailPayload]) -> str:
    parts: list[str] = []
    for payload in sorted(payloads, key=lambda item: item.received_at or datetime.min):
        parts.append(starred_payload_identity_context(payload))
    return "\n\n---\n\n".join(part for part in parts if part.strip())[:20000]


def inbound_payload_from_message(message: InboundEmailMessage) -> InboundEmailPayload:
    return InboundEmailPayload(
        provider_message_id=message.provider_message_id,
        provider_thread_id=message.provider_thread_id,
        gmail_history_id=message.gmail_history_id,
        from_email=message.from_email,
        to_email=message.to_email,
        subject=message.subject,
        snippet=message.snippet,
        body_text=message.body_text,
        received_at=message.received_at,
        raw_headers=message.raw_headers_json or {},
        provider_labels=message.provider_labels_json or [],
        attachments=[],
    )


def watched_thread_next_sync_at(last_processed_at: datetime | None, *, settings: Settings | None = None) -> datetime:
    settings = settings or get_settings()
    base = last_processed_at or utc_now()
    return base + timedelta(seconds=max(settings.gmail_watched_threads_poll_seconds, 1))


def datetime_after(left: datetime, right: datetime | None) -> bool:
    if right is None:
        return True
    if left.tzinfo is None and right.tzinfo is not None:
        left = left.replace(tzinfo=right.tzinfo)
    elif left.tzinfo is not None and right.tzinfo is None:
        right = right.replace(tzinfo=left.tzinfo)
    return left > right


def classify_unlinked_watched_message(message: InboundEmailMessage) -> tuple[str, str, Decimal]:
    text = normalize_fast_classification_text(
        "\n".join(
            part
            for part in (
                message.subject or "",
                message.snippet or "",
                message.body_text or "",
            )
            if part.strip()
        )
    )
    if any(marker in text for marker in FAST_REFUSAL_MARKERS):
        return "refused", "fast_unlinked_uber_refusal", Decimal("0.82")
    if any(marker in text for marker in FAST_POSITIVE_MARKERS):
        return "payment_confirmed", "fast_unlinked_payment_positive", Decimal("0.84")
    if any(marker in text for marker in FAST_EVIDENCE_MARKERS):
        return "evidence_requested", "fast_unlinked_evidence_requested", Decimal("0.75")
    return "manual_review", "fast_unlinked_manual_review", Decimal("0.50")


def normalize_fast_classification_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.replace("\xa0", " ").split())
