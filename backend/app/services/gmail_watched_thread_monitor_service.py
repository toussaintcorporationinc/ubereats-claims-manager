from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import String, cast, select
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
    GMAIL_STARRED_URGENT_QUERY,
    GmailInboundSyncResult,
    GmailInboundSyncService,
)

logger = logging.getLogger(__name__)

FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed", "manual_review", "skipped"}
POSITIVE_REVIEW_TYPES = {"accepted", "payment_to_verify", "payment_confirmed"}
REFUSAL_REVIEW_TYPES = {"refused"}
EVIDENCE_REVIEW_TYPES = {"evidence_requested", "information_requested"}


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
        process_new_messages: bool | None = None,
    ) -> GmailWatchedThreadMonitorResult:
        result = GmailWatchedThreadMonitorResult()
        if not self.settings.gmail_watched_threads_enabled:
            result.status = "disabled"
            return result

        if discover_starred:
            self.discover_from_starred_messages(db, user, account, result=result)

        if process_new_messages is None:
            process_new_messages = self.settings.gmail_watched_threads_process_new_messages
        if not process_new_messages:
            return result

        max_per_cycle = max_threads or self.settings.gmail_watched_threads_max_per_cycle
        active_threads = self.get_active_watched_threads(db, account, max_per_cycle=max_per_cycle)
        result.watched_threads_seen += len(active_threads)
        order_identifier_index = self.sync_service.build_order_identifier_index(db, user)
        sync_result = GmailInboundSyncResult(status="success")

        for watched in active_threads:
            try:
                payloads = self.fetch_thread_payloads(db, account, watched)
            except Exception as exc:  # noqa: BLE001 - a broken thread must not stop the mailbox cycle.
                logger.exception("Unable to fetch watched Gmail thread %s", watched.gmail_thread_id)
                result.errors.append(f"thread:{watched.gmail_thread_id}:{str(exc)[:160]}")
                watched.status = "manual_review"
                watched.last_processed_at = utc_now()
                continue

            for payload in sorted(payloads, key=lambda item: item.received_at or datetime.min):
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
                if not message.provider_thread_id:
                    continue
                work_item, created = self.ensure_work_item(db, watched, account, message)
                if created:
                    result.work_items_created += 1
                    result.new_messages_detected += 1
                if work_item.status in FINAL_WORK_ITEM_STATUSES and not self.message_changed_after_processing(
                    message,
                    work_item,
                ):
                    continue

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

        if sync_result.negative_responses_detected and self.settings.gmail_inbound_auto_sync_run_autopilot:
            self.sync_service.run_autopilot_for_negative_responses(db, user, sync_result)
            result.autopilot_sent_count += sync_result.autopilot_sent_count
            result.autopilot_skipped_count += sync_result.autopilot_skipped_count
            result.autopilot_failed_count += sync_result.autopilot_failed_count
        result.errors.extend(sync_result.errors)
        return result

    def discover_from_starred_messages(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        result: GmailWatchedThreadMonitorResult | None = None,
    ) -> GmailWatchedThreadMonitorResult:
        result = result or GmailWatchedThreadMonitorResult()
        if not self.settings.gmail_watched_threads_enabled:
            result.status = "disabled"
            return result

        refreshed_payloads: list[InboundEmailPayload] = []
        try:
            refreshed_payloads = self.sync_service.fetch_payloads(
                db,
                user,
                account,
                query=GMAIL_STARRED_URGENT_QUERY,
                max_messages=min(
                    self.settings.gmail_starred_max_messages_per_sync,
                    self.settings.gmail_watched_threads_max_per_cycle,
                ),
            )
        except EmailProviderError as exc:
            result.errors.append(f"starred_discovery:{exc.message}")
        except Exception as exc:  # noqa: BLE001 - dashboard discovery must remain best-effort.
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
        get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
        if callable(get_thread_messages):
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
        message = self.sync_service.create_inbound_message(
            db,
            user,
            account,
            payload,
            order_identifier_index=order_identifier_index,
        )
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
            db.add(item)
            created = True
        else:
            if item.watched_thread_id is None:
                item.watched_thread_id = watched.id
            if item.inbound_message_id is None:
                item.inbound_message_id = message.id
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
    def message_changed_after_processing(message: InboundEmailMessage, item: GmailStarredWorkItem) -> bool:
        if item.processed_at is None:
            return True
        if message.updated_at is None:
            return False
        return datetime_after(message.updated_at, item.processed_at)


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
