from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import unicodedata

from sqlalchemy import String, and_, case, cast, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.auth import can_access_restaurant
from app.core.config import Settings, get_settings
from app.models import (
    AppealAttempt,
    ClaimOrder,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    EvidenceFile,
    EvidenceRequestTask,
    GmailResponseAnalysis,
    GmailStarredWorkItem,
    GmailWatchedThread,
    InboundEmailMessage,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.claim_validation_service import get_claim_validation_gaps
from app.services.email_provider import EmailProvider, EmailProviderError, InboundEmailAttachment, InboundEmailPayload
from app.services.email_draft_service import EmailDraftBusinessError, create_email_draft
from app.services.file_storage_service import FileStorageError, store_evidence_bytes
from app.services.gmail_inbound_sync_service import (
    GMAIL_STARRED_URGENT_QUERIES,
    GmailInboundSyncResult,
    GmailInboundSyncService,
    sender_matches_filter,
    starred_payload_identity_context,
)
from app.services.gmail_payment_signal_service import (
    EXPLICIT_PAYMENT_PROMISE_MARKERS,
    current_response_order_number,
    message_has_explicit_payment_confirmation,
    payload_has_explicit_payment_confirmation,
    text_has_explicit_payment_confirmation,
    visible_email_text,
)
from app.services.gmail_quota import parse_gmail_retry_after
from app.services.gmail_scope_service import gmail_scopes_allow_modify
from app.services.autopilot_identity_repair_service import (
    find_or_create_order_from_starred_text,
    repair_order_identity_from_inbound_attachments,
)
from app.services.appeal_workflow_service import AppealWorkflowError, ensure_workflow_for_claim_order, mark_appeal_sent
from app.services.autopilot_service import (
    AutopilotError,
    autopilot_is_emergency_stopped,
    create_starred_thread_reply_attempt,
    gmail_account_send_pacing_active,
    gmail_account_sent_last_24_hours_count,
    safe_autopilot_recipient,
    send_provider_draft,
)
from app.services.restaurant_identity_service import text_contains_legacy_restaurant_name

logger = logging.getLogger(__name__)

FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed", "manual_review", "skipped"}
SKIPPABLE_FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed"}
MAX_AUTOPILOT_REPLY_CANDIDATES_PER_CYCLE = 1
MAX_LOCAL_REPLY_CANDIDATES_PER_CYCLE = 250
RECOVERABLE_PROOF_REPLY_REASONS = {
    "proof_reply_blocked:missing_order_amount",
    "proof_reply_blocked:missing_currency",
}
POSITIVE_REVIEW_TYPES = {"accepted", "payment_to_verify", "payment_confirmed"}
POSITIVE_WATCHED_STATUSES = {"positive", "payment_confirmed"}
REFUSAL_REVIEW_TYPES = {"refused"}
EVIDENCE_REVIEW_TYPES = {"evidence_requested", "information_requested"}
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
    "decision maintenue",
    "maintenons notre decision",
    "nous maintenons",
    "ne sommes pas en mesure",
    "nous ne pourrons pas",
    "not eligible",
    "no refund",
)
FAST_EVIDENCE_MARKERS = (
    "waiting for your reply",
    "preuve",
    "justificatif",
    "piece jointe",
    "document",
    "photo",
    "information supplementaire",
    "attendons votre reponse",
    "en attente de votre reponse",
    "merci de fournir",
    "merci de nous fournir",
    "merci de transmettre",
    "merci de nous transmettre",
    "fournir",
    "provide evidence",
    "additional information",
)
FAST_FOLLOWUP_MARKERS = (
    "support submitted",
    "case submitted",
    "demande soumise",
    "dossier soumis",
    "demande envoyee",
    "requete envoyee",
    "restaurant support help center envoye",
    "en cours de traitement",
    "en cours d examen",
    "under review",
    "we are reviewing",
)
UBER_SUPPORT_SURVEY_MARKERS = (
    "partagez votre experience avec le service d assistance uber",
    "partagez votre experience avec le service d'assistance uber",
    "partagez votre experience avec l assistance uber",
    "partagez votre experience avec l'assistance uber",
    "comment evalueriez vous votre experience",
    "donnez votre avis sur l assistance uber",
    "share your experience with uber support",
    "rate your support experience",
    "how would you rate your support experience",
    "how did we do",
)
FAST_CLASSIFICATION_BODY_HEAD_CHARS = 12000
FAST_CLASSIFICATION_BODY_TAIL_CHARS = 6000


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
        self._latest_external_message_cache: dict[tuple[int, str], InboundEmailPayload | None] = {}
        self._latest_external_message_errors: dict[tuple[int, str], str] = {}
        self._remote_thread_has_draft_cache: dict[tuple[int, str], bool] = {}
        self._thread_payload_cache: dict[tuple[int, str], list[InboundEmailPayload]] = {}
        self._thread_payloads_with_attachments: set[tuple[int, str]] = set()

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

        if any(
            parse_gmail_retry_after(
                error,
                safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
            )
            is not None
            for error in result.errors
        ):
            return result

        if discover_starred:
            work_items_before_discovery = result.work_items_created
            self.discover_from_starred_messages(
                db,
                user,
                account,
                result=result,
                use_full_history=discover_full_history,
                max_messages=starred_discovery_max_messages,
            )
            if process_new_messages and result.work_items_created > work_items_before_discovery:
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
        self._latest_external_message_cache.clear()
        self._latest_external_message_errors.clear()
        self._remote_thread_has_draft_cache.clear()
        self._thread_payload_cache.clear()
        self._thread_payloads_with_attachments.clear()

        max_per_cycle = max_threads or self.settings.gmail_watched_threads_max_per_cycle
        sync_result = GmailInboundSyncResult(status="success")
        if process_local_backlog:
            self.process_pending_local_work_items(
                db,
                user,
                account,
                result=result,
                sync_result=sync_result,
                max_items=max_per_cycle,
            )
        # Local classification does not call Gmail. Give remote thread polling
        # its own budget so a large local backlog cannot hide fresh Uber replies.
        remote_thread_budget = max(max_per_cycle, 0)
        if remote_thread_budget <= 0:
            active_threads: list[GmailWatchedThread] = []
        else:
            can_modify_stars = gmail_scopes_allow_modify(account.scopes)
            star_mutations_allowed = can_modify_stars and not autopilot_is_emergency_stopped(db)
            active_threads = self.get_active_watched_threads(
                db,
                account,
                max_per_cycle=remote_thread_budget,
                include_positive_star_cleanup=star_mutations_allowed,
            )
            if not can_modify_stars and self.count_pending_positive_star_cleanup(db, account):
                result.errors.append("gmail_unstar:reconnect_required:gmail.modify")
        result.watched_threads_seen += len(active_threads)
        order_identifier_index = (
            self.sync_service.build_order_identifier_index(db, user) if active_threads else {}
        )

        for watched in active_threads:
            if watched.status in POSITIVE_WATCHED_STATUSES:
                if self.block_unverified_positive_star_cleanup(db, user, watched, result):
                    continue
                self.remove_thread_star(
                    db,
                    user,
                    watched,
                    allow_remote_lookup=True,
                    result=result,
                )
                watched.last_processed_at = utc_now()
                db.flush()
                continue
            try:
                payloads = self.fetch_thread_payloads(
                    db,
                    account,
                    watched,
                    prefer_full_thread=self.watched_thread_has_actionable_reply(db, watched.id),
                )
            except Exception as exc:  # noqa: BLE001 - a broken thread must not stop the mailbox cycle.
                retry_after = parse_gmail_retry_after(
                    str(exc),
                    safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
                )
                if retry_after is not None:
                    result.errors.append(f"gmail_quota_retry_after:{retry_after.isoformat()}")
                    break
                if gmail_resource_not_found(exc):
                    self.close_missing_watched_thread(db, user, watched)
                    continue
                logger.exception("Unable to fetch watched Gmail thread %s", watched.gmail_thread_id)
                result.errors.append(f"thread:{watched.gmail_thread_id}:{str(exc)[:160]}")
                watched.status = "manual_review"
                watched.last_processed_at = utc_now()
                continue

            allow_remote_star_lookup = len(payloads) > 1
            cache_key = (account.id, watched.gmail_thread_id)
            if payloads:
                self._thread_payload_cache[cache_key] = payloads
                self._latest_external_message_cache[cache_key] = self.select_latest_external_payload(
                    payloads,
                    account,
                    include_support_surveys=True,
                )
                self._remote_thread_has_draft_cache[cache_key] = any(
                    self.payload_from_account(payload, account)
                    and "DRAFT" in {str(label).strip().upper() for label in payload.provider_labels}
                    for payload in payloads
                )
            else:
                # The thread was part of this cycle's bounded Gmail polling
                # budget, but Gmail returned no usable message. Cache the
                # absence so AutoPilot fails closed without issuing a second
                # remote read for an unrelated backlog item.
                self._thread_payload_cache[cache_key] = []
                self._latest_external_message_cache[cache_key] = None
                self._remote_thread_has_draft_cache[cache_key] = False
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
                needs_positive_reclassification = self.final_item_needs_positive_reclassification(
                    work_item,
                    message,
                )
                if (
                    work_item.status in FINAL_WORK_ITEM_STATUSES
                    and not self.message_changed_after_processing(message, work_item)
                    and not self.should_reprocess_final_item(watched, work_item, message)
                ):
                    continue
                if needs_positive_reclassification:
                    message.review_status = "unreviewed"
                    message.reviewed_at = None
                    message.reviewed_by_user_id = None

                positive_link_block_reason: str | None = None
                explicit_payment_confirmation = message_has_explicit_payment_confirmation(message)
                if explicit_payment_confirmation:
                    resolved_order, positive_link_block_reason = self.resolve_positive_response_order(
                        db,
                        user,
                        message,
                        thread_order,
                    )
                    if resolved_order is not None and (
                        thread_order is None or resolved_order.id != thread_order.id
                    ):
                        self.relink_positive_message_order(
                            db,
                            user,
                            watched,
                            message,
                            resolved_order,
                        )
                        thread_order = resolved_order

                    needs_full_identity_repair = bool(
                        positive_link_block_reason is not None
                        or thread_order is None
                        or message.match_status != "linked"
                    )
                    if needs_full_identity_repair:
                        try:
                            identity_payloads = self.fetch_thread_payloads(
                                db,
                                account,
                                watched,
                                prefer_full_thread=True,
                            )
                            repaired_order = self.repair_positive_watched_thread_from_payloads(
                                db,
                                user,
                                watched,
                                identity_payloads,
                                ignore_existing_link=positive_link_block_reason is not None,
                            )
                        except Exception as exc:  # noqa: BLE001 - one identity failure must not stop Gmail sync.
                            repaired_order = None
                            result.errors.append(
                                f"positive_identity_repair:{watched.gmail_thread_id}:{str(exc)[:120]}"
                            )
                        response_order_number = current_response_order_number(message)
                        if repaired_order is not None and (
                            not response_order_number
                            or order_identifiers_equivalent(
                                response_order_number,
                                repaired_order.uber_order_number,
                                repaired_order.internal_reference,
                            )
                        ):
                            self.relink_positive_message_order(
                                db,
                                user,
                                watched,
                                message,
                                repaired_order,
                            )
                            thread_order = repaired_order
                            positive_link_block_reason = None

                if positive_link_block_reason is not None:
                    self.process_unlinked_watched_message_fast(db, user, message, sync_result)
                elif thread_order is None and message.match_status != "linked":
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
                self.update_work_item_status(
                    db,
                    user,
                    watched,
                    work_item,
                    message,
                    result,
                    allow_remote_star_lookup=allow_remote_star_lookup,
                )
                result.processed_messages += 1

            watched.last_processed_at = utc_now()
            db.flush()

        result.actionable_refused_threads = self.count_actionable_refused_threads(db, account)

        if self.settings.gmail_inbound_auto_sync_run_autopilot:
            self.send_pending_actionable_replies(
                db,
                user,
                account,
                result=result,
                max_items=max(
                    1,
                    min(
                        max_per_cycle,
                        self.settings.gmail_watched_threads_batch_per_cycle,
                        MAX_AUTOPILOT_REPLY_CANDIDATES_PER_CYCLE,
                    ),
                ),
                reset_remote_cache=False,
            )
        result.errors.extend(sync_result.errors)
        return result

    def send_pending_actionable_replies(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        result: GmailWatchedThreadMonitorResult,
        max_items: int,
        reset_remote_cache: bool = True,
    ) -> int:
        """Send same-thread Gmail relances for actionable watched work items.

        This intentionally avoids the historical global AutoPilot scan. The Gmail
        worker must keep moving through thousands of starred threads, so it only
        handles items that are already in the watched-thread queue.
        """
        if max_items <= 0:
            return 0
        if reset_remote_cache:
            self._latest_external_message_cache.clear()
            self._latest_external_message_errors.clear()
            self._remote_thread_has_draft_cache.clear()
            self._thread_payload_cache.clear()
            self._thread_payloads_with_attachments.clear()
        block_reason = self.automatic_reply_block_reason(db, account)
        if block_reason is not None:
            result.autopilot_skipped_count += 1
            return 0
        if not self.settings.autopilot_enabled or not self.settings.autopilot_appeals_enabled:
            result.autopilot_skipped_count += 1
            return 0
        cached_thread_ids = {
            thread_id
            for account_id, thread_id in self._latest_external_message_cache
            if account_id == account.id
        }
        cached_thread_priority = case(
            (GmailWatchedThread.gmail_thread_id.in_(cached_thread_ids or {"__none__"}), 0),
            else_=1,
        )
        cached_thread_filter = (
            GmailWatchedThread.gmail_thread_id.in_(cached_thread_ids)
            if not reset_remote_cache and cached_thread_ids
            else false()
            if not reset_remote_cache
            else True
        )
        items = list(
            db.scalars(
                select(GmailStarredWorkItem)
                .options(
                    selectinload(GmailStarredWorkItem.watched_thread),
                    selectinload(GmailStarredWorkItem.inbound_message).selectinload(InboundEmailMessage.order),
                )
                .join(GmailWatchedThread, GmailWatchedThread.id == GmailStarredWorkItem.watched_thread_id)
                .join(
                    InboundEmailMessage,
                    InboundEmailMessage.id == GmailStarredWorkItem.inbound_message_id,
                )
                .outerjoin(ClaimOrder, ClaimOrder.id == InboundEmailMessage.order_id)
                .outerjoin(
                    GmailResponseAnalysis,
                    GmailResponseAnalysis.inbound_message_id == InboundEmailMessage.id,
                )
                .where(
                    GmailStarredWorkItem.email_account_id == account.id,
                    GmailStarredWorkItem.inbound_message_id.is_not(None),
                    or_(
                        GmailStarredWorkItem.status.in_(["refused", "evidence_needed"]),
                        and_(
                            GmailStarredWorkItem.status == "manual_review",
                            or_(
                                GmailResponseAnalysis.recommended_review_type == "followup_needed",
                                and_(
                                    GmailResponseAnalysis.recommended_review_type.in_(
                                        sorted(EVIDENCE_REVIEW_TYPES)
                                    ),
                                    GmailStarredWorkItem.reason.in_(sorted(RECOVERABLE_PROOF_REPLY_REASONS)),
                                ),
                            ),
                        ),
                    ),
                    GmailWatchedThread.status.in_(["active", "manual_review"]),
                    GmailWatchedThread.star_active.is_(True),
                    cached_thread_filter,
                )
                .order_by(
                    cached_thread_priority,
                    case(
                        (GmailStarredWorkItem.status == "refused", 0),
                        (GmailStarredWorkItem.status == "evidence_needed", 1),
                        (GmailStarredWorkItem.status == "manual_review", 2),
                        else_=3,
                    ),
                    case((ClaimOrder.order_amount.is_(None), 1), else_=0),
                    ClaimOrder.order_amount.desc(),
                    GmailStarredWorkItem.processed_at.asc().nullsfirst(),
                    GmailStarredWorkItem.id.asc(),
                )
                .limit(max(max_items, MAX_LOCAL_REPLY_CANDIDATES_PER_CYCLE))
            ).all()
        )
        remote_candidates: list[GmailStarredWorkItem] = []
        for item in items:
            watched = item.watched_thread
            message = item.inbound_message
            if watched is None or message is None:
                result.autopilot_skipped_count += 1
                continue
            if item.status == "manual_review" and item.reason in RECOVERABLE_PROOF_REPLY_REASONS:
                item.status = "evidence_needed"
            if item.gmail_thread_id != watched.gmail_thread_id or message.provider_thread_id != watched.gmail_thread_id:
                self.mark_unsafe_reply_for_review(
                    db,
                    watched,
                    item,
                    reason="gmail_reply_thread_mismatch",
                )
                result.autopilot_skipped_count += 1
                continue
            latest_local_payload = self.latest_local_uber_message(db, account, watched.gmail_thread_id)
            if (
                latest_local_payload is not None
                and latest_local_payload.provider_message_id != message.provider_message_id
            ):
                self.mark_unsafe_reply_for_review(
                    db,
                    watched,
                    item,
                    reason="superseded_by_newer_uber_message",
                )
                result.autopilot_skipped_count += 1
                continue
            remote_candidates.append(item)

        sent_count = 0
        sent_threads: set[str] = set()
        remote_preflight_count = 0
        for item in remote_candidates:
            current_block_reason = self.automatic_reply_block_reason(db, account)
            if current_block_reason is not None:
                result.autopilot_skipped_count += 1
                break
            watched = item.watched_thread
            message = item.inbound_message
            if watched is None or message is None:
                result.autopilot_skipped_count += 1
                continue
            if watched.gmail_thread_id in sent_threads:
                item.reason = "thread_already_replied_this_cycle"
                item.processed_at = utc_now()
                result.autopilot_skipped_count += 1
                continue
            local_block_reason = self.local_actionable_reply_block_reason(db, watched, item, message)
            if local_block_reason is not None:
                item.reason = f"proof_reply_blocked:{local_block_reason}"
                self.mark_work_item_manual_review(db, item)
                result.autopilot_skipped_count += 1
                continue
            if remote_preflight_count >= max_items:
                break
            remote_preflight_count += 1
            latest_reply_block_reason = self.latest_reply_block_reason(db, account, watched, message)
            if latest_reply_block_reason is not None:
                if latest_reply_block_reason in {
                    "gmail_latest_reply_check_failed",
                    "gmail_latest_reply_not_found",
                }:
                    item.reason = latest_reply_block_reason
                    item.processed_at = utc_now()
                    item.updated_at = item.processed_at
                    result.autopilot_skipped_count += 1
                    error = f"{latest_reply_block_reason}:{watched.gmail_thread_id}"
                    if latest_reply_block_reason == "gmail_latest_reply_check_failed":
                        detail = self._latest_external_message_errors.get((account.id, watched.gmail_thread_id))
                        if detail:
                            error = f"{error}:{detail}"
                    result.errors.append(error)
                    if latest_reply_block_reason == "gmail_latest_reply_check_failed":
                        break
                    continue
                self.mark_unsafe_reply_for_review(
                    db,
                    watched,
                    item,
                    reason=latest_reply_block_reason,
                )
                if latest_reply_block_reason == "superseded_by_newer_uber_message":
                    self.queue_latest_external_message_for_processing(
                        db,
                        user,
                        account,
                        watched,
                        result,
                    )
                result.autopilot_skipped_count += 1
                continue
            if self.send_actionable_reply_for_work_item(db, user, account, watched, item, message, result):
                sent_threads.add(watched.gmail_thread_id)
                sent_count += 1
        return sent_count

    @staticmethod
    def local_actionable_reply_block_reason(
        db: Session,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
    ) -> str | None:
        """Skip proof replies with unsafe identity before using Gmail quota."""
        if item.status != "evidence_needed":
            return None
        order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else message.order
        if order is None:
            return None
        _missing_items, blocking_reasons = get_claim_validation_gaps(db, order)
        for reason in blocking_reasons:
            if reason in {
                "missing_restaurant",
                "missing_uber_order_number",
            }:
                return reason
        return None

    def automatic_reply_block_reason(self, db: Session, account: EmailAccount) -> str | None:
        if autopilot_is_emergency_stopped(db):
            return "autopilot_emergency_stopped"
        limit = self.settings.autopilot_per_gmail_account_daily_limit
        if limit > 0 and gmail_account_sent_last_24_hours_count(db, account.id) >= limit:
            return "gmail_account_daily_limit_reached"
        if gmail_account_send_pacing_active(db, account.id, limit):
            return "gmail_account_send_pacing_active"
        return None

    def reply_thread_integrity_error(
        self,
        db: Session,
        account: EmailAccount,
        watched: GmailWatchedThread,
        message: InboundEmailMessage,
        order: ClaimOrder,
    ) -> str | None:
        if message.provider_thread_id != watched.gmail_thread_id:
            return "gmail_reply_thread_mismatch"
        if watched.claim_order_id is not None and watched.claim_order_id != order.id:
            return "gmail_thread_order_mismatch"
        if message.order_id is not None and message.order_id != order.id:
            return "gmail_thread_order_mismatch"

        linked_order_ids = set(
            db.scalars(
                select(InboundEmailMessage.order_id)
                .where(
                    InboundEmailMessage.email_account_id == account.id,
                    InboundEmailMessage.provider_thread_id == watched.gmail_thread_id,
                    InboundEmailMessage.order_id.is_not(None),
                )
                .distinct()
            ).all()
        )
        if watched.claim_order_id is not None:
            linked_order_ids.add(watched.claim_order_id)
        linked_order_ids.add(order.id)
        if len(linked_order_ids) > 1:
            return "gmail_thread_contains_multiple_orders"

        drafted_order_ids = set(
            db.scalars(
                select(EmailDraft.order_id)
                .join(EmailProviderDraft, EmailProviderDraft.email_draft_id == EmailDraft.id)
                .where(
                    EmailProviderDraft.email_account_id == account.id,
                    EmailProviderDraft.provider == "gmail",
                    EmailProviderDraft.provider_thread_id == watched.gmail_thread_id,
                )
                .distinct()
            ).all()
        )
        if any(drafted_order_id != order.id for drafted_order_id in drafted_order_ids):
            return "gmail_thread_contains_multiple_orders"
        return None

    def remote_thread_has_account_draft(
        self,
        db: Session,
        account: EmailAccount,
        watched: GmailWatchedThread,
    ) -> bool:
        cache_key = (account.id, watched.gmail_thread_id)
        if cache_key in self._remote_thread_has_draft_cache:
            return self._remote_thread_has_draft_cache[cache_key]
        get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
        if not callable(get_thread_messages):
            return False
        try:
            payloads = list(
                get_thread_messages(
                    db,
                    account,
                    watched.gmail_thread_id,
                    include_attachments=False,
                )
            )
        except TypeError:
            payloads = list(get_thread_messages(db, account, watched.gmail_thread_id))
        return any(
            self.payload_from_account(payload, account)
            and "DRAFT" in {str(label).strip().upper() for label in payload.provider_labels}
            for payload in payloads
        )

    def watched_thread_has_actionable_reply(self, db: Session, watched_thread_id: int) -> bool:
        return (
            db.scalar(
                select(GmailStarredWorkItem.id)
                .join(
                    InboundEmailMessage,
                    InboundEmailMessage.id == GmailStarredWorkItem.inbound_message_id,
                )
                .outerjoin(
                    GmailResponseAnalysis,
                    GmailResponseAnalysis.inbound_message_id == InboundEmailMessage.id,
                )
                .where(
                    GmailStarredWorkItem.watched_thread_id == watched_thread_id,
                    GmailStarredWorkItem.inbound_message_id.is_not(None),
                    or_(
                        GmailStarredWorkItem.status.in_(["refused", "evidence_needed"]),
                        and_(
                            GmailStarredWorkItem.status == "manual_review",
                            GmailResponseAnalysis.recommended_review_type == "followup_needed",
                        ),
                    ),
                )
                .limit(1)
            )
            is not None
        )

    def latest_reply_block_reason(
        self,
        db: Session,
        account: EmailAccount,
        watched: GmailWatchedThread,
        message: InboundEmailMessage,
    ) -> str | None:
        """Fail closed when a queued item is not Uber's latest message in the thread."""
        cache_key = (account.id, watched.gmail_thread_id)
        if cache_key in self._latest_external_message_errors:
            return "gmail_latest_reply_check_failed"
        if cache_key not in self._latest_external_message_cache:
            latest_payload: InboundEmailPayload | None = None
            get_latest = getattr(self.provider, "get_latest_external_thread_message_for_account", None)
            if callable(get_latest):
                try:
                    latest_payload = get_latest(db, account, watched.gmail_thread_id)
                except Exception as exc:  # noqa: BLE001 - a failed safety lookup must block sending.
                    logger.warning(
                        "Unable to verify latest Gmail reply for watched thread %s: %s",
                        watched.gmail_thread_id,
                        exc,
                    )
                    self._latest_external_message_errors[cache_key] = str(exc)[:500]
                    return "gmail_latest_reply_check_failed"
            if latest_payload is None:
                latest_payload = self.latest_local_uber_message(db, account, watched.gmail_thread_id)
            self._latest_external_message_cache[cache_key] = latest_payload

        latest_payload = self._latest_external_message_cache[cache_key]
        if latest_payload is None:
            return "gmail_latest_reply_not_found"
        if payload_is_uber_support_survey(latest_payload):
            return "latest_uber_reply_is_support_survey"
        if latest_payload.provider_message_id != message.provider_message_id:
            return "superseded_by_newer_uber_message"
        return None

    def queue_latest_external_message_for_processing(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        watched: GmailWatchedThread,
        result: GmailWatchedThreadMonitorResult,
    ) -> bool:
        """Persist the newer Uber reply discovered by the send safety check.

        The reply is deliberately left pending. The next local-backlog pass runs
        the normal classification, payment accounting, star, and reply rules.
        """
        payload = self._latest_external_message_cache.get((account.id, watched.gmail_thread_id))
        if (
            payload is None
            or not payload.provider_message_id
            or payload.provider_thread_id != watched.gmail_thread_id
            or self.payload_from_account(payload, account)
            or not sender_matches_filter(payload.from_email, self.settings.gmail_support_sender_filter)
            or payload_is_uber_support_survey(payload)
        ):
            return False

        sync_result = GmailInboundSyncResult(status="success")
        message = self.upsert_inbound_message(
            db,
            user,
            account,
            payload,
            order_identifier_index=self.sync_service.build_order_identifier_index(db, user),
            sync_result=sync_result,
        )
        thread_order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else None
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

        self.update_watched_links_from_message(watched, message)
        _work_item, created = self.ensure_work_item(db, watched, account, message)
        if created:
            result.work_items_created += 1
            result.new_messages_detected += 1
        result.errors.extend(sync_result.errors)
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.newer_reply_queued",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "provider_message_id": message.provider_message_id,
                "work_item_created": created,
            },
        )
        db.flush()
        return created

    def latest_local_uber_message(
        self,
        db: Session,
        account: EmailAccount,
        thread_id: str,
    ) -> InboundEmailPayload | None:
        messages = list(
            db.scalars(
                select(InboundEmailMessage)
                .where(
                    InboundEmailMessage.email_account_id == account.id,
                    InboundEmailMessage.provider_thread_id == thread_id,
                )
                .order_by(
                    InboundEmailMessage.received_at.desc().nullslast(),
                    InboundEmailMessage.id.desc(),
                )
            ).all()
        )
        latest = next(
            (
                candidate
                for candidate in messages
                if sender_matches_filter(candidate.from_email, self.settings.gmail_support_sender_filter)
            ),
            None,
        )
        return inbound_payload_from_message(latest) if latest is not None else None

    @staticmethod
    def thread_reply_sent_after_message(
        db: Session,
        account: EmailAccount,
        watched: GmailWatchedThread,
        message: InboundEmailMessage,
    ) -> bool:
        statement = select(func.count(EmailProviderDraft.id)).where(
            EmailProviderDraft.email_account_id == account.id,
            EmailProviderDraft.provider == "gmail",
            EmailProviderDraft.provider_thread_id == watched.gmail_thread_id,
            EmailProviderDraft.status == "sent",
            EmailProviderDraft.sent_at.is_not(None),
        )
        if message.received_at is not None:
            statement = statement.where(EmailProviderDraft.sent_at >= message.received_at)
        return int(db.scalar(statement) or 0) > 0

    @staticmethod
    def mark_unsafe_reply_for_review(
        db: Session,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        *,
        reason: str,
    ) -> None:
        watched.status = "manual_review"
        item.status = "skipped"
        item.reason = reason
        item.processed_at = utc_now()
        item.updated_at = item.processed_at
        db.flush()

    def send_actionable_reply_for_work_item(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
        result: GmailWatchedThreadMonitorResult,
    ) -> bool:
        if item.status == "evidence_needed":
            return self.send_evidence_reply_for_work_item(db, user, account, watched, item, message, result)
        if item.status == "manual_review":
            return self.send_followup_reply_for_work_item(db, user, account, watched, item, message, result)
        return self.send_refused_reply_for_work_item(db, user, account, watched, item, message, result)

    def send_refused_reply_for_work_item(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
        result: GmailWatchedThreadMonitorResult,
    ) -> bool:
        if not self.settings.autopilot_enabled or not self.settings.autopilot_appeals_enabled:
            item.reason = "autopilot_disabled"
            result.autopilot_skipped_count += 1
            return False

        order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else message.order
        if order is None:
            try:
                order = self.repair_watched_thread_from_payloads(
                    db,
                    user,
                    watched,
                    self.fetch_thread_payloads(db, account, watched, prefer_full_thread=True),
                )
            except Exception as exc:  # noqa: BLE001 - one missing Gmail thread must not stop the queue.
                item.reason = f"identity_repair_failed:{str(exc)[:120]}"
                self.mark_work_item_manual_review(db, item)
                result.autopilot_skipped_count += 1
                result.errors.append(f"identity_repair:{str(exc)[:160]}")
                return False
        if order is None:
            item.reason = "missing_linked_order_for_starred_reply"
            self.mark_work_item_manual_review(db, item)
            result.autopilot_skipped_count += 1
            return False
        integrity_error = self.reply_thread_integrity_error(db, account, watched, message, order)
        if integrity_error is not None:
            self.mark_unsafe_reply_for_review(db, watched, item, reason=integrity_error)
            result.autopilot_skipped_count += 1
            return False
        if message.order_id is None:
            message.order_id = order.id
        if watched.claim_order_id is None:
            watched.claim_order_id = order.id
            watched.linked_case_type = "claim_order"
            watched.linked_case_id = order.id

        existing_attempt = self.latest_attempt_for_refusal_message(db, message)
        refresh_restaurant_identity = self.attempt_uses_legacy_restaurant_name(existing_attempt)
        if (
            existing_attempt
            and existing_attempt.provider_draft
            and existing_attempt.provider_draft.status == "sent"
            and not refresh_restaurant_identity
        ):
            item.reason = "already_replied_to_refusal"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False
        if existing_attempt and existing_attempt.provider_draft and existing_attempt.provider_draft.status == "send_requested":
            item.reason = "reply_send_already_requested"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False
        if not refresh_restaurant_identity and self.thread_reply_sent_after_message(
            db,
            account,
            watched,
            message,
        ):
            item.reason = "reply_already_sent_after_message"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False

        try:
            workflow = ensure_workflow_for_claim_order(db, order, user)
            watched.appeal_workflow_id = workflow.id
            attempt = (
                existing_attempt
                if existing_attempt and existing_attempt.email_draft and not refresh_restaurant_identity
                else None
            )
            if attempt is None:
                if (
                    refresh_restaurant_identity
                    and existing_attempt is not None
                    and existing_attempt.provider_draft is not None
                    and existing_attempt.provider_draft.status == "provider_draft_created"
                ):
                    existing_attempt.provider_draft.status = "failed"
                    existing_attempt.provider_draft.last_error = "superseded_restaurant_identity"
                    existing_attempt.provider_draft.updated_at = utc_now()
                attempt = create_starred_thread_reply_attempt(db, workflow=workflow, starred_message=message, user=user)

            provider_draft = attempt.provider_draft
            if provider_draft is not None and provider_draft.status != "provider_draft_created":
                attempt = create_starred_thread_reply_attempt(db, workflow=workflow, starred_message=message, user=user)
                provider_draft = None

            if provider_draft is None:
                if self.remote_thread_has_account_draft(db, account, watched):
                    self.mark_unsafe_reply_for_review(
                        db,
                        watched,
                        item,
                        reason="gmail_draft_already_exists_in_thread",
                    )
                    result.autopilot_skipped_count += 1
                    return False
                provider_draft = self.create_draft_for_watched_account(
                    db,
                    user,
                    account,
                    attempt.email_draft,
                    to_email=safe_autopilot_recipient(),
                    include_evidence=True,
                    watched=watched,
                    reply_message=message,
                )
                attempt.provider_draft_id = provider_draft.id
                attempt.status = "gmail_draft_created"
                db.flush()

            send_provider_draft(
                db,
                user,
                provider_draft,
                self.provider,
                order_status_after_send=None,
                require_reply_thread=True,
            )
            if attempt.status != "sent":
                try:
                    mark_appeal_sent(db, workflow=workflow, user=user)
                except AppealWorkflowError as exc:
                    if exc.message != "Appeal attempt is already marked as sent":
                        raise
        except AutopilotError as exc:
            if exc.message in {"gmail_account_daily_limit_reached", "gmail_account_send_pacing_active"}:
                item.reason = exc.message
                result.autopilot_skipped_count += 1
                return False
            item.reason = f"autopilot_send_blocked:{exc.message}"
            result.autopilot_failed_count += 1
            result.errors.append(f"autopilot_send:{exc.message}")
            return False
        except Exception as exc:  # noqa: BLE001 - one Gmail thread must not stop the queue.
            logger.exception("Unable to send Gmail relance for watched thread %s", watched.gmail_thread_id)
            item.reason = f"autopilot_send_failed:{str(exc)[:120]}"
            result.autopilot_failed_count += 1
            result.errors.append(f"autopilot_send:{str(exc)[:160]}")
            return False

        item.reason = "gmail_reply_sent"
        self.mark_work_item_processed(item)
        result.autopilot_sent_count += 1
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.refusal_reply_sent",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "provider_message_id": message.provider_message_id,
                "order_id": order.id,
            },
        )
        db.flush()
        return True

    def send_followup_reply_for_work_item(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
        result: GmailWatchedThreadMonitorResult,
    ) -> bool:
        """Relance an old Uber acknowledgement that still has no decision."""
        if not self.settings.autopilot_enabled or not self.settings.autopilot_appeals_enabled:
            item.reason = "autopilot_disabled"
            result.autopilot_skipped_count += 1
            return False

        order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else message.order
        if order is None:
            try:
                order = self.repair_watched_thread_from_payloads(
                    db,
                    user,
                    watched,
                    self.fetch_thread_payloads(db, account, watched, prefer_full_thread=True),
                )
            except Exception as exc:  # noqa: BLE001 - one missing Gmail thread must not stop the queue.
                item.reason = f"followup_identity_repair_failed:{str(exc)[:120]}"
                self.mark_work_item_manual_review(db, item)
                result.autopilot_skipped_count += 1
                result.errors.append(f"followup_identity_repair:{str(exc)[:160]}")
                return False
        if order is None:
            item.reason = "missing_linked_order_for_followup"
            self.mark_work_item_manual_review(db, item)
            result.autopilot_skipped_count += 1
            return False
        integrity_error = self.reply_thread_integrity_error(db, account, watched, message, order)
        if integrity_error is not None:
            self.mark_unsafe_reply_for_review(db, watched, item, reason=integrity_error)
            result.autopilot_skipped_count += 1
            return False
        if message.order_id is None:
            message.order_id = order.id
        if watched.claim_order_id is None:
            watched.claim_order_id = order.id
            watched.linked_case_type = "claim_order"
            watched.linked_case_id = order.id

        workflow = ensure_workflow_for_claim_order(db, order, user)
        watched.appeal_workflow_id = workflow.id
        if workflow.appeal_attempt_count >= self.settings.autopilot_max_appeal_attempts:
            item.reason = "max_appeal_attempts_reached"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False

        cooldown_reference = latest_datetime(
            message.received_at or item.created_at,
            workflow.last_appeal_sent_at,
            order.last_followup_sent_at,
        )
        if datetime_within_cooldown(cooldown_reference, self.settings.autopilot_cooldown_hours):
            item.reason = "followup_cooldown_active"
            item.processed_at = utc_now()
            item.updated_at = item.processed_at
            result.autopilot_skipped_count += 1
            db.flush()
            return False

        existing_attempt = self.latest_attempt_for_refusal_message(db, message)
        refresh_restaurant_identity = self.attempt_uses_legacy_restaurant_name(existing_attempt)
        if existing_attempt and existing_attempt.provider_draft and existing_attempt.provider_draft.status == "send_requested":
            item.reason = "followup_send_already_requested"
            result.autopilot_skipped_count += 1
            return False

        try:
            attempt = (
                existing_attempt
                if existing_attempt
                and existing_attempt.email_draft
                and existing_attempt.provider_draft
                and existing_attempt.provider_draft.status == "provider_draft_created"
                and not refresh_restaurant_identity
                else None
            )
            if (
                refresh_restaurant_identity
                and existing_attempt is not None
                and existing_attempt.provider_draft is not None
                and existing_attempt.provider_draft.status == "provider_draft_created"
            ):
                existing_attempt.provider_draft.status = "failed"
                existing_attempt.provider_draft.last_error = "superseded_restaurant_identity"
                existing_attempt.provider_draft.updated_at = utc_now()
            if attempt is None:
                attempt = create_starred_thread_reply_attempt(
                    db,
                    workflow=workflow,
                    starred_message=message,
                    user=user,
                    reply_kind="followup",
                )

            provider_draft = attempt.provider_draft
            if provider_draft is None:
                if self.remote_thread_has_account_draft(db, account, watched):
                    self.mark_unsafe_reply_for_review(
                        db,
                        watched,
                        item,
                        reason="gmail_draft_already_exists_in_thread",
                    )
                    result.autopilot_skipped_count += 1
                    return False
                provider_draft = self.create_draft_for_watched_account(
                    db,
                    user,
                    account,
                    attempt.email_draft,
                    to_email=safe_autopilot_recipient(),
                    include_evidence=True,
                    watched=watched,
                    reply_message=message,
                )
                attempt.provider_draft_id = provider_draft.id
                attempt.status = "gmail_draft_created"
                db.flush()

            send_provider_draft(
                db,
                user,
                provider_draft,
                self.provider,
                order_status_after_send=None,
                require_reply_thread=True,
            )
            try:
                mark_appeal_sent(db, workflow=workflow, user=user)
            except AppealWorkflowError as exc:
                if exc.message != "Appeal attempt is already marked as sent":
                    raise
        except AutopilotError as exc:
            if exc.message in {"gmail_account_daily_limit_reached", "gmail_account_send_pacing_active"}:
                item.reason = exc.message
                result.autopilot_skipped_count += 1
                return False
            item.reason = f"followup_send_blocked:{exc.message}"
            result.autopilot_failed_count += 1
            result.errors.append(f"followup_send:{exc.message}")
            return False
        except Exception as exc:  # noqa: BLE001 - one Gmail thread must not stop the queue.
            logger.exception("Unable to send Gmail followup for watched thread %s", watched.gmail_thread_id)
            item.reason = f"followup_send_failed:{str(exc)[:120]}"
            result.autopilot_failed_count += 1
            result.errors.append(f"followup_send:{str(exc)[:160]}")
            return False

        item.status = "manual_review"
        item.reason = "gmail_followup_reply_sent"
        item.processed_at = utc_now()
        item.updated_at = item.processed_at
        result.autopilot_sent_count += 1
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.pending_reply_followup_sent",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "provider_message_id": message.provider_message_id,
                "order_id": order.id,
            },
        )
        db.flush()
        return True

    def send_evidence_reply_for_work_item(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
        result: GmailWatchedThreadMonitorResult,
    ) -> bool:
        if not self.settings.autopilot_enabled or not self.settings.autopilot_appeals_enabled:
            item.reason = "autopilot_disabled"
            result.autopilot_skipped_count += 1
            return False

        order = db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else message.order
        if order is None:
            try:
                order = self.repair_watched_thread_from_payloads(
                    db,
                    user,
                    watched,
                    self.fetch_thread_payloads(db, account, watched, prefer_full_thread=True),
                )
            except Exception as exc:  # noqa: BLE001 - one missing Gmail thread must not stop the queue.
                item.reason = f"proof_reply_identity_repair_failed:{str(exc)[:120]}"
                self.mark_work_item_manual_review(db, item)
                result.autopilot_skipped_count += 1
                result.errors.append(f"proof_reply_identity_repair:{str(exc)[:160]}")
                return False
        if order is None:
            item.reason = "missing_linked_order_for_proof_reply"
            self.mark_work_item_manual_review(db, item)
            result.autopilot_skipped_count += 1
            return False
        integrity_error = self.reply_thread_integrity_error(db, account, watched, message, order)
        if integrity_error is not None:
            self.mark_unsafe_reply_for_review(db, watched, item, reason=integrity_error)
            result.autopilot_skipped_count += 1
            return False
        if message.order_id is None:
            message.order_id = order.id
        if watched.claim_order_id is None:
            watched.claim_order_id = order.id
            watched.linked_case_type = "claim_order"
            watched.linked_case_id = order.id

        provider_draft = self.latest_proof_reply_provider_draft(db, order.id, watched.gmail_thread_id)
        if provider_draft and provider_draft.status == "sent":
            item.reason = "already_replied_to_evidence_request"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False
        if provider_draft and provider_draft.status == "send_requested":
            item.reason = "proof_reply_send_already_requested"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False
        if self.thread_reply_sent_after_message(db, account, watched, message):
            item.reason = "reply_already_sent_after_message"
            self.mark_work_item_skipped(db, item)
            result.autopilot_skipped_count += 1
            return False
        if not any(evidence.deleted_at is None for evidence in order.evidence_files):
            try:
                recovery_reason = self.recover_proof_evidence_from_thread(
                    db,
                    user,
                    account,
                    watched,
                    message,
                    order,
                    result,
                )
            except Exception as exc:  # noqa: BLE001 - one attachment failure must not stop the mailbox.
                logger.exception(
                    "Unable to recover Gmail evidence for watched thread %s",
                    watched.gmail_thread_id,
                )
                item.reason = f"proof_reply_evidence_recovery_failed:{str(exc)[:120]}"
                self.mark_work_item_manual_review(db, item)
                result.autopilot_failed_count += 1
                result.errors.append(f"proof_reply_evidence_recovery:{str(exc)[:160]}")
                return False
            if recovery_reason is not None:
                if recovery_reason in {
                    "latest_uber_reply_is_support_survey",
                    "superseded_by_newer_uber_message",
                }:
                    self.mark_unsafe_reply_for_review(db, watched, item, reason=recovery_reason)
                    if recovery_reason == "superseded_by_newer_uber_message":
                        self.queue_latest_external_message_for_processing(
                            db,
                            user,
                            account,
                            watched,
                            result,
                        )
                else:
                    item.reason = f"proof_reply_blocked:{recovery_reason}"
                    self.mark_work_item_manual_review(db, item)
                result.autopilot_skipped_count += 1
                return False

        try:
            if provider_draft is None or provider_draft.status != "provider_draft_created":
                if self.remote_thread_has_account_draft(db, account, watched):
                    self.mark_unsafe_reply_for_review(
                        db,
                        watched,
                        item,
                        reason="gmail_draft_already_exists_in_thread",
                    )
                    result.autopilot_skipped_count += 1
                    return False
                draft = create_email_draft(db, order.id, "proof_reply", user_id=user.id)
                provider_draft = self.create_draft_for_watched_account(
                    db,
                    user,
                    account,
                    draft,
                    to_email=safe_autopilot_recipient(),
                    include_evidence=True,
                    watched=watched,
                    reply_message=message,
                )
                db.flush()

            send_provider_draft(
                db,
                user,
                provider_draft,
                self.provider,
                order_status_after_send=order.status,
                require_reply_thread=True,
            )
        except EmailDraftBusinessError as exc:
            reason = exc.blocking_reasons[0] if exc.blocking_reasons else exc.message
            item.reason = f"proof_reply_blocked:{reason}"
            self.mark_work_item_manual_review(db, item)
            result.autopilot_skipped_count += 1
            return False
        except AutopilotError as exc:
            if exc.message in {"gmail_account_daily_limit_reached", "gmail_account_send_pacing_active"}:
                item.reason = exc.message
                result.autopilot_skipped_count += 1
                return False
            item.reason = f"proof_reply_send_blocked:{exc.message}"
            result.autopilot_failed_count += 1
            result.errors.append(f"proof_reply_send:{exc.message}")
            return False
        except Exception as exc:  # noqa: BLE001 - one Gmail thread must not stop the queue.
            logger.exception("Unable to send Gmail proof reply for watched thread %s", watched.gmail_thread_id)
            item.reason = f"proof_reply_send_failed:{str(exc)[:120]}"
            result.autopilot_failed_count += 1
            result.errors.append(f"proof_reply_send:{str(exc)[:160]}")
            return False

        item.reason = "gmail_proof_reply_sent"
        self.mark_work_item_processed(item)
        self.complete_evidence_request_tasks_after_reply(db, user, order)
        result.autopilot_sent_count += 1
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.evidence_reply_sent",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "provider_message_id": message.provider_message_id,
                "order_id": order.id,
            },
        )
        db.flush()
        return True

    def recover_proof_evidence_from_thread(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        watched: GmailWatchedThread,
        message: InboundEmailMessage,
        order: ClaimOrder,
        result: GmailWatchedThreadMonitorResult,
    ) -> str | None:
        """Persist proof files previously sent in the same verified Gmail thread."""
        cache_key = (account.id, watched.gmail_thread_id)
        payloads = self._thread_payload_cache.get(cache_key, [])
        if cache_key not in self._thread_payloads_with_attachments:
            get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
            if not callable(get_thread_messages):
                return "missing_evidence"
            try:
                payloads = list(
                    get_thread_messages(
                        db,
                        account,
                        watched.gmail_thread_id,
                        include_attachments=True,
                    )
                )
            except TypeError:
                payloads = list(get_thread_messages(db, account, watched.gmail_thread_id))
            self._thread_payload_cache[cache_key] = payloads
            self._thread_payloads_with_attachments.add(cache_key)

        latest_payload = self.select_latest_external_payload(
            payloads,
            account,
            include_support_surveys=True,
        )
        if latest_payload is None:
            latest_payload = self._latest_external_message_cache.get(cache_key)
        if latest_payload is None:
            return "gmail_latest_reply_not_found"
        self._latest_external_message_cache[cache_key] = latest_payload
        if payload_is_uber_support_survey(latest_payload):
            return "latest_uber_reply_is_support_survey"
        if latest_payload.provider_message_id != message.provider_message_id:
            return "superseded_by_newer_uber_message"

        attachments = [
            attachment
            for payload in payloads
            if payload.provider_thread_id == watched.gmail_thread_id
            and self.payload_from_account(payload, account)
            for attachment in payload.attachments
        ]
        if not attachments:
            return "missing_evidence"

        try:
            repair_order_identity_from_inbound_attachments(db, user, order, attachments)
        except Exception as exc:  # noqa: BLE001 - extraction is useful but must not block a real attachment.
            logger.warning(
                "Unable to extract order identity from Gmail evidence for thread %s: %s",
                watched.gmail_thread_id,
                exc,
            )

        existing_checksums = {
            evidence.checksum_sha256
            for evidence in order.evidence_files
            if evidence.deleted_at is None and evidence.checksum_sha256
        }
        stored_count = 0
        seen_checksums: set[str] = set()
        storage_errors: list[str] = []
        for attachment in attachments:
            checksum = sha256(attachment.content).hexdigest()
            if checksum in existing_checksums or checksum in seen_checksums:
                continue
            seen_checksums.add(checksum)
            try:
                stored = store_evidence_bytes(
                    order,
                    original_filename=attachment.filename,
                    mime_type=attachment.mime_type or None,
                    content=attachment.content,
                )
            except FileStorageError as exc:
                storage_errors.append(exc.message)
                continue
            evidence = EvidenceFile(
                order=order,
                evidence_type="other",
                original_filename=stored.original_filename,
                storage_path=stored.storage_path,
                storage_backend=stored.storage_backend,
                mime_type=stored.mime_type,
                file_size=stored.file_size,
                checksum_sha256=stored.checksum_sha256,
                uploaded_by_user_id=user.id,
            )
            db.add(evidence)
            existing_checksums.add(stored.checksum_sha256)
            stored_count += 1

        if stored_count == 0 and not any(
            evidence.deleted_at is None for evidence in order.evidence_files
        ):
            if storage_errors:
                result.errors.append(f"proof_reply_evidence_store:{storage_errors[0][:160]}")
            return "missing_evidence"

        db.flush()
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.evidence_recovered_from_sent_message",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "order_id": order.id,
                "stored_evidence_count": stored_count,
            },
        )
        return None

    def create_draft_for_watched_account(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        email_draft: EmailDraft,
        *,
        to_email: str,
        include_evidence: bool,
        watched: GmailWatchedThread,
        reply_message: InboundEmailMessage,
    ) -> EmailProviderDraft:
        create_in_thread = getattr(self.provider, "create_draft_for_account_in_thread", None)
        if callable(create_in_thread):
            return create_in_thread(
                db,
                user,
                email_draft,
                to_email=to_email,
                include_evidence=include_evidence,
                account=account,
                thread_id=watched.gmail_thread_id,
                reply_message=reply_message,
            )
        create_for_account = getattr(self.provider, "create_draft_for_account", None)
        if callable(create_for_account):
            return create_for_account(
                db,
                user,
                email_draft,
                to_email=to_email,
                include_evidence=include_evidence,
                account=account,
            )
        return self.provider.create_draft(
            db,
            user,
            email_draft,
            to_email=to_email,
            include_evidence=include_evidence,
        )

    @staticmethod
    def mark_work_item_skipped(db: Session, item: GmailStarredWorkItem) -> None:
        item.status = "skipped"
        item.processed_at = utc_now()
        item.updated_at = item.processed_at
        db.flush()

    @staticmethod
    def mark_work_item_manual_review(db: Session, item: GmailStarredWorkItem) -> None:
        item.status = "manual_review"
        item.processed_at = utc_now()
        item.updated_at = item.processed_at
        db.flush()

    @staticmethod
    def mark_work_item_processed(item: GmailStarredWorkItem) -> None:
        item.status = "processed"
        item.processed_at = utc_now()
        item.updated_at = item.processed_at

    def complete_evidence_request_tasks_after_reply(
        self,
        db: Session,
        user: User,
        order: ClaimOrder,
    ) -> None:
        tasks = list(
            db.scalars(
                select(EvidenceRequestTask).where(
                    EvidenceRequestTask.order_id == order.id,
                    EvidenceRequestTask.task_type == "evidence_review",
                    EvidenceRequestTask.status.in_(["pending", "uploaded"]),
                )
            ).all()
        )
        completed_at = utc_now()
        for task in tasks:
            previous_status = task.status
            task.status = "completed"
            task.completed_by_user_id = user.id
            task.completed_at = completed_at
            add_audit_log(
                db,
                entity_type="evidence_request_task",
                entity_id=task.id,
                action="evidence_task.completed_by_gmail_proof_reply",
                user_id=user.id,
                old_value={"status": previous_status},
                new_value={"status": task.status, "order_id": order.id},
            )

    def latest_proof_reply_provider_draft(
        self,
        db: Session,
        order_id: int,
        gmail_thread_id: str,
    ) -> EmailProviderDraft | None:
        return db.scalar(
            select(EmailProviderDraft)
            .join(EmailDraft, EmailDraft.id == EmailProviderDraft.email_draft_id)
            .where(
                EmailDraft.order_id == order_id,
                EmailDraft.draft_type == "proof_reply",
                EmailProviderDraft.provider == "gmail",
                EmailProviderDraft.provider_thread_id == gmail_thread_id,
            )
            .order_by(EmailProviderDraft.id.desc())
            .limit(1)
        )

    def latest_attempt_for_refusal_message(
        self,
        db: Session,
        message: InboundEmailMessage,
    ) -> AppealAttempt | None:
        if message.id is None:
            return None
        return db.scalar(
            select(AppealAttempt)
            .options(
                selectinload(AppealAttempt.provider_draft),
                selectinload(AppealAttempt.email_draft),
            )
            .where(AppealAttempt.based_on_refusal_message_id == message.id)
            .order_by(AppealAttempt.id.desc())
            .limit(1)
        )

    @staticmethod
    def attempt_uses_legacy_restaurant_name(attempt: AppealAttempt | None) -> bool:
        if attempt is None or attempt.email_draft is None:
            return False
        return text_contains_legacy_restaurant_name(
            f"{attempt.email_draft.subject or ''}\n{attempt.email_draft.body or ''}"
        )

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
                .join(
                    InboundEmailMessage,
                    InboundEmailMessage.id == GmailStarredWorkItem.inbound_message_id,
                )
                .where(
                    GmailStarredWorkItem.email_account_id == account.id,
                    GmailStarredWorkItem.inbound_message_id.is_not(None),
                    GmailStarredWorkItem.status.in_(["pending", "processing", "failed"]),
                    GmailWatchedThread.status.in_(["active", "manual_review"]),
                    GmailWatchedThread.star_active.is_(True),
                )
                .order_by(
                    InboundEmailMessage.received_at.desc().nullslast(),
                    GmailStarredWorkItem.id.desc(),
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
            self.update_work_item_status(db, user, watched, item, message, result, allow_remote_star_lookup=False)
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
        message = (
            db.get(InboundEmailMessage, item.inbound_message_id)
            if item is not None and item.inbound_message_id is not None
            else None
        )
        if message is not None and self.final_item_needs_positive_reclassification(item, message):
            return False
        return bool(item and item.status in SKIPPABLE_FINAL_WORK_ITEM_STATUSES)

    def select_payloads_for_processing(
        self,
        payloads: list[InboundEmailPayload],
        account: EmailAccount,
    ) -> list[InboundEmailPayload]:
        """Keep watched-thread cycles focused on Uber's latest answer.

        The whole thread is fetched so identity repair can read past context.
        Processing every old sent/received message is expensive and causes the
        backlog to crawl. An explicit payment promise remains terminal even when
        Uber later adds a survey or administrative message, so prefer the newest
        such promise from the thread before falling back to the latest answer.
        """
        positive_candidates = [
            payload
            for payload in payloads
            if payload.provider_message_id
            and not self.payload_from_account(payload, account)
            and sender_matches_filter(payload.from_email, self.settings.gmail_support_sender_filter)
            and not payload_is_uber_support_survey(payload)
            and payload_has_explicit_payment_confirmation(payload)
        ]
        if positive_candidates:
            _index, latest_positive = max(
                enumerate(positive_candidates),
                key=lambda item: (item[1].received_at or datetime.min, item[0]),
            )
            return [latest_positive]

        latest = self.select_latest_external_payload(
            payloads,
            account,
            include_support_surveys=False,
        )
        return [latest] if latest is not None else []

    def select_latest_external_payload(
        self,
        payloads: list[InboundEmailPayload],
        account: EmailAccount,
        *,
        include_support_surveys: bool,
    ) -> InboundEmailPayload | None:
        deduped: dict[str, InboundEmailPayload] = {}
        for payload in payloads:
            if not payload.provider_message_id:
                continue
            deduped[payload.provider_message_id] = payload
        candidates = [
            payload
            for payload in deduped.values()
            if not self.payload_from_account(payload, account)
            and sender_matches_filter(payload.from_email, self.settings.gmail_support_sender_filter)
            and (include_support_surveys or not payload_is_uber_support_survey(payload))
        ]
        if not candidates:
            return None
        _index, latest = max(
            enumerate(candidates),
            key=lambda item: (item[1].received_at or datetime.min, item[0]),
        )
        return latest

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
            if not sender_matches_filter(payload.from_email, self.settings.gmail_support_sender_filter):
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
        starred_query = select(InboundEmailMessage).where(
            InboundEmailMessage.email_account_id == account.id,
            InboundEmailMessage.provider == "gmail",
            InboundEmailMessage.provider_thread_id.is_not(None),
            labels_text.ilike("%STARRED%"),
        )
        sender_filter = (self.settings.gmail_support_sender_filter or "").strip()
        if sender_filter:
            starred_query = starred_query.where(InboundEmailMessage.from_email.ilike(f"%{sender_filter}%"))
        starred_messages = list(
            db.scalars(
                starred_query.order_by(
                    InboundEmailMessage.received_at.desc().nullslast(),
                    InboundEmailMessage.id.desc(),
                ).limit(self.settings.gmail_watched_threads_max_per_cycle)
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
        for query in sender_filtered_starred_queries(
            GMAIL_STARRED_URGENT_QUERIES,
            self.settings.gmail_support_sender_filter,
        ):
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
        include_positive_star_cleanup: bool = False,
    ) -> list[GmailWatchedThread]:
        statuses = ["active", "manual_review"]
        if include_positive_star_cleanup:
            statuses.extend(sorted(POSITIVE_WATCHED_STATUSES))
        pending_remote_ref = (
            select(GmailStarredWorkItem.id)
            .where(
                GmailStarredWorkItem.watched_thread_id == GmailWatchedThread.id,
                GmailStarredWorkItem.inbound_message_id.is_(None),
                GmailStarredWorkItem.status.in_(["pending", "processing", "failed"]),
            )
            .exists()
        )
        actionable_refusal = (
            select(GmailStarredWorkItem.id)
            .where(
                GmailStarredWorkItem.watched_thread_id == GmailWatchedThread.id,
                GmailStarredWorkItem.inbound_message_id.is_not(None),
                GmailStarredWorkItem.status == "refused",
            )
            .exists()
        )
        return list(
            db.scalars(
                select(GmailWatchedThread)
                .options(selectinload(GmailWatchedThread.claim_order))
                .where(
                    GmailWatchedThread.email_account_id == account.id,
                    GmailWatchedThread.status.in_(statuses),
                    GmailWatchedThread.star_active.is_(True),
                )
                .order_by(
                    case(
                        (GmailWatchedThread.status.in_(sorted(POSITIVE_WATCHED_STATUSES)), 0),
                        else_=1,
                    ),
                    case((actionable_refusal, 0), else_=1),
                    case((pending_remote_ref, 0), else_=1),
                    GmailWatchedThread.last_processed_at.asc().nullsfirst(),
                    GmailWatchedThread.last_message_at.desc().nullslast(),
                    GmailWatchedThread.id.asc(),
                )
                .limit(max_per_cycle)
            ).all()
        )

    def count_pending_positive_star_cleanup(self, db: Session, account: EmailAccount) -> int:
        return int(
            db.scalar(
                select(func.count(GmailWatchedThread.id)).where(
                    GmailWatchedThread.email_account_id == account.id,
                    GmailWatchedThread.status.in_(sorted(POSITIVE_WATCHED_STATUSES)),
                    GmailWatchedThread.star_active.is_(True),
                )
            )
            or 0
        )

    def close_missing_watched_thread(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
    ) -> None:
        """Retire a permanently missing Gmail thread from the hot worker queue."""
        now = utc_now()
        watched.status = "closed"
        watched.star_active = False
        watched.last_processed_at = now

        work_items = list(
            db.scalars(
                select(GmailStarredWorkItem).where(
                    GmailStarredWorkItem.watched_thread_id == watched.id,
                    GmailStarredWorkItem.status.in_(["pending", "processing", "failed"]),
                )
            ).all()
        )
        for item in work_items:
            item.status = "skipped"
            item.reason = "gmail_thread_not_found"
            item.processed_at = now

        messages = list(
            db.scalars(
                select(InboundEmailMessage).where(
                    InboundEmailMessage.email_account_id == watched.email_account_id,
                    InboundEmailMessage.provider_thread_id == watched.gmail_thread_id,
                )
            ).all()
        )
        for message in messages:
            message.provider_labels_json = [
                label
                for label in (message.provider_labels_json or [])
                if str(label).upper() != "STARRED"
            ]

        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.closed_missing_remote_thread",
            user_id=user.id,
            new_value={
                "gmail_thread_id": watched.gmail_thread_id,
                "skipped_work_items": len(work_items),
            },
        )
        db.flush()

    def fetch_thread_payloads(
        self,
        db: Session,
        account: EmailAccount,
        watched: GmailWatchedThread,
        *,
        prefer_full_thread: bool = False,
    ) -> list[InboundEmailPayload]:
        get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
        include_attachments = prefer_full_thread and self.watched_thread_needs_evidence_recovery(
            db,
            watched,
        )

        def fetch_full_thread() -> list[InboundEmailPayload]:
            if not callable(get_thread_messages):
                return []
            try:
                payloads = list(
                    get_thread_messages(
                        db,
                        account,
                        watched.gmail_thread_id,
                        include_attachments=include_attachments,
                    )
                )
            except TypeError:
                payloads = list(get_thread_messages(db, account, watched.gmail_thread_id))
            if include_attachments:
                self._thread_payloads_with_attachments.add((account.id, watched.gmail_thread_id))
            return payloads

        if prefer_full_thread and callable(get_thread_messages):
            payloads = fetch_full_thread()
            if payloads:
                return payloads

        get_latest_external_message = getattr(self.provider, "get_latest_external_thread_message_for_account", None)
        if watched.claim_order_id is None and callable(get_latest_external_message):
            latest_payload = get_latest_external_message(db, account, watched.gmail_thread_id)
            if latest_payload is not None:
                if payload_is_uber_support_survey(latest_payload):
                    payloads = fetch_full_thread()
                    if payloads:
                        return payloads
                return [latest_payload]

        if watched.claim_order_id is None and callable(get_thread_messages):
            payloads = fetch_full_thread()
            if payloads:
                return payloads

        if callable(get_latest_external_message):
            latest_payload = get_latest_external_message(db, account, watched.gmail_thread_id)
            if latest_payload is not None:
                if payload_is_uber_support_survey(latest_payload):
                    payloads = fetch_full_thread()
                    if payloads:
                        return payloads
                return [latest_payload]

        if callable(get_thread_messages):
            return fetch_full_thread()
        return [
            inbound_payload_from_message(message)
            for message in db.scalars(
                select(InboundEmailMessage).where(
                    InboundEmailMessage.email_account_id == account.id,
                    InboundEmailMessage.provider_thread_id == watched.gmail_thread_id,
                )
            ).all()
        ]

    @staticmethod
    def watched_thread_needs_evidence_recovery(
        db: Session,
        watched: GmailWatchedThread,
    ) -> bool:
        if watched.claim_order_id is not None:
            has_evidence = db.scalar(
                select(EvidenceFile.id)
                .where(
                    EvidenceFile.order_id == watched.claim_order_id,
                    EvidenceFile.deleted_at.is_(None),
                )
                .limit(1)
            )
            if has_evidence is not None:
                return False
        return (
            db.scalar(
                select(GmailStarredWorkItem.id)
                .where(
                    GmailStarredWorkItem.watched_thread_id == watched.id,
                    or_(
                        GmailStarredWorkItem.status == "evidence_needed",
                        and_(
                            GmailStarredWorkItem.status == "manual_review",
                            GmailStarredWorkItem.reason.in_(
                                sorted(RECOVERABLE_PROOF_REPLY_REASONS)
                            ),
                        ),
                    ),
                )
                .limit(1)
            )
            is not None
        )

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

    def repair_positive_watched_thread_from_payloads(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        payloads: list[InboundEmailPayload],
        *,
        ignore_existing_link: bool,
    ) -> ClaimOrder | None:
        if not ignore_existing_link:
            return self.repair_watched_thread_from_payloads(db, user, watched, payloads)
        context = watched_thread_identity_context(payloads)
        if not context:
            return None
        return find_or_create_order_from_starred_text(db, user, context)

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
        if self.final_item_needs_positive_reclassification(item, message):
            return True
        if item.status not in {"manual_review", "skipped"}:
            return False
        return bool(
            watched.claim_order_id
            and message.match_status == "linked"
            and message.review_status == "unreviewed"
        )

    @staticmethod
    def final_item_needs_positive_reclassification(
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
    ) -> bool:
        if item.status == "positive" or not message_has_explicit_payment_confirmation(message):
            return False
        analysis = message.response_analysis
        return analysis is None or analysis.recommended_review_type not in POSITIVE_REVIEW_TYPES

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
        missing_remote_ref = None
        if watched.status == "closed":
            missing_remote_ref = db.scalar(
                select(GmailStarredWorkItem.id).where(
                    GmailStarredWorkItem.watched_thread_id == watched.id,
                    GmailStarredWorkItem.provider_message_id == provider_message_id,
                    GmailStarredWorkItem.reason == "gmail_thread_not_found",
                )
            )
        if watched.status == "paused" or (watched.status == "closed" and missing_remote_ref is None):
            watched.status = "active"
            watched.star_active = True
        if not watched.first_starred_message_id:
            watched.first_starred_message_id = provider_message_id
        if watched.status != "closed":
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
            if watched.claim_order_id is None:
                watched.claim_order_id = message.order_id
                watched.linked_case_type = "claim_order"
                watched.linked_case_id = message.order_id
            if watched.claim_order_id == message.order_id:
                order = message.order
                if order and order.customer_refund_disputes:
                    watched.customer_refund_dispute_id = order.customer_refund_disputes[0].id
                if order and order.appeal_workflows:
                    watched.appeal_workflow_id = order.appeal_workflows[0].id
            else:
                watched.status = "manual_review"
        if message.gmail_history_id:
            watched.last_seen_history_id = message.gmail_history_id
        if message.received_at and datetime_after(message.received_at, watched.last_message_at):
            watched.last_message_at = message.received_at
        if self.labels_include_starred(message.provider_labels_json):
            watched.star_active = True

    def block_unverified_positive_star_cleanup(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        result: GmailWatchedThreadMonitorResult,
    ) -> bool:
        item = db.scalar(
            select(GmailStarredWorkItem)
            .where(
                GmailStarredWorkItem.watched_thread_id == watched.id,
                GmailStarredWorkItem.status == "positive",
            )
            .order_by(
                GmailStarredWorkItem.processed_at.desc().nullslast(),
                GmailStarredWorkItem.id.desc(),
            )
            .limit(1)
        )
        message = db.get(InboundEmailMessage, item.inbound_message_id) if item and item.inbound_message_id else None
        if item is None or message is None:
            block_reason = "positive_payment_message_missing"
        elif not message_has_explicit_payment_confirmation(message):
            block_reason = "positive_without_explicit_payment_confirmation"
        elif watched.claim_order_id and message.order_id and watched.claim_order_id != message.order_id:
            block_reason = "gmail_thread_order_mismatch"
        else:
            analysis = message.response_analysis
            if analysis is None:
                analysis = db.scalar(
                    select(GmailResponseAnalysis)
                    .where(GmailResponseAnalysis.inbound_message_id == message.id)
                    .order_by(GmailResponseAnalysis.id.desc())
                )
            block_reason = self.positive_accounting_block_reason(db, message, analysis)

        if block_reason is None:
            return False

        now = utc_now()
        if item is not None:
            item.status = "manual_review"
            item.reason = block_reason
            item.processed_at = now
        previous_status = watched.status
        watched.status = "manual_review"
        watched.star_active = True
        watched.last_processed_at = now
        result.manual_reviews += 1
        add_audit_log(
            db,
            entity_type="gmail_watched_thread",
            entity_id=watched.id,
            action="gmail_watched_thread.legacy_positive_cleanup_blocked",
            user_id=user.id,
            old_value={"status": previous_status},
            new_value={
                "status": watched.status,
                "reason": block_reason,
                "gmail_thread_id": watched.gmail_thread_id,
            },
        )
        db.flush()
        return True

    def update_work_item_status(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        item: GmailStarredWorkItem,
        message: InboundEmailMessage,
        result: GmailWatchedThreadMonitorResult,
        *,
        allow_remote_star_lookup: bool = False,
    ) -> None:
        thread_order_conflict = bool(
            watched.claim_order_id
            and message.order_id
            and watched.claim_order_id != message.order_id
        )
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
        explicit_payment_confirmation = message_has_explicit_payment_confirmation(message)
        positive_accounting_block_reason = (
            self.positive_accounting_block_reason(db, message, analysis)
            if explicit_payment_confirmation
            else None
        )
        if thread_order_conflict:
            item.status = "manual_review"
            item.reason = "gmail_thread_order_mismatch"
            watched.status = "manual_review"
            watched.star_active = True
            result.manual_reviews += 1
        elif explicit_payment_confirmation and positive_accounting_block_reason is None:
            item.status = "positive"
            item.reason = "payment_confirmed"
            watched.status = "payment_confirmed"
            result.positive_responses += 1
            result.payment_confirmed += 1
            self.remove_thread_star(
                db,
                user,
                watched,
                allow_remote_lookup=allow_remote_star_lookup,
                result=result,
            )
        elif explicit_payment_confirmation:
            item.status = "manual_review"
            item.reason = positive_accounting_block_reason
            watched.status = "manual_review"
            watched.star_active = True
            result.manual_reviews += 1
        elif review_type in POSITIVE_REVIEW_TYPES:
            item.status = "manual_review"
            item.reason = "positive_without_explicit_payment_confirmation"
            watched.status = "manual_review"
            watched.star_active = True
            result.manual_reviews += 1
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

    @staticmethod
    def positive_accounting_block_reason(
        db: Session,
        message: InboundEmailMessage,
        analysis: GmailResponseAnalysis | None,
    ) -> str | None:
        if message.order_id is None:
            return "positive_payment_unlinked"
        order = db.get(ClaimOrder, message.order_id)
        if order is None:
            return "positive_payment_unlinked"
        response_order_number = current_response_order_number(message)
        if response_order_number and not order_identifiers_equivalent(
            response_order_number,
            order.uber_order_number,
            order.internal_reference,
        ):
            return "positive_payment_order_mismatch"
        if analysis is None or analysis.recommended_review_type not in POSITIVE_REVIEW_TYPES:
            return "positive_payment_not_accounted"
        if analysis.status == "applied":
            return None
        if order.status != "payment_confirmed":
            return "positive_payment_not_accounted"
        if analysis.detected_amount is None:
            return None if order.recovered_amount is not None else "positive_payment_amount_not_recorded"
        if order.recovered_amount is None:
            return "positive_payment_amount_not_recorded"
        if order.recovered_amount != analysis.detected_amount:
            return "positive_payment_amount_conflict"
        return None

    @staticmethod
    def resolve_positive_response_order(
        db: Session,
        user: User,
        message: InboundEmailMessage,
        current_order: ClaimOrder | None,
    ) -> tuple[ClaimOrder | None, str | None]:
        response_order_number = current_response_order_number(message)
        if not response_order_number:
            return current_order, None
        if current_order is not None and order_identifiers_equivalent(
            response_order_number,
            current_order.uber_order_number,
            current_order.internal_reference,
        ):
            return current_order, None
        candidates = list(
            db.scalars(
                select(ClaimOrder).where(
                    or_(
                        func.upper(ClaimOrder.uber_order_number) == response_order_number.upper(),
                        func.upper(ClaimOrder.internal_reference) == response_order_number.upper(),
                    )
                )
            ).all()
        )
        accessible_candidates = [
            order for order in candidates if can_access_restaurant(db, user, order.restaurant_id)
        ]
        if len(accessible_candidates) == 1:
            return accessible_candidates[0], None
        if current_order is not None:
            return current_order, "positive_payment_order_mismatch"
        return None, None

    def relink_positive_message_order(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        message: InboundEmailMessage,
        order: ClaimOrder,
    ) -> None:
        previous_order_id = message.order_id or watched.claim_order_id
        self.sync_service.record_linked_message(
            db,
            user,
            message,
            order,
            match_reason="order_number_match",
        )
        message.order = order
        message.review_status = "unreviewed"
        message.reviewed_at = None
        message.reviewed_by_user_id = None
        watched.claim_order_id = order.id
        watched.linked_case_type = "claim_order"
        watched.linked_case_id = order.id
        watched.customer_refund_dispute_id = (
            order.customer_refund_disputes[0].id if order.customer_refund_disputes else None
        )
        watched.appeal_workflow_id = order.appeal_workflows[0].id if order.appeal_workflows else None
        email_thread = db.scalar(
            select(EmailThread).where(
                EmailThread.provider == "gmail",
                EmailThread.direction == "inbound",
                EmailThread.message_id == message.provider_message_id,
            )
        )
        if email_thread is not None:
            email_thread.order_id = order.id
        if previous_order_id != order.id:
            add_audit_log(
                db,
                entity_type="gmail_watched_thread",
                entity_id=watched.id,
                action="gmail_watched_thread.positive_order_relinked",
                user_id=user.id,
                old_value={"claim_order_id": previous_order_id},
                new_value={
                    "claim_order_id": order.id,
                    "uber_order_number": order.uber_order_number,
                    "provider_message_id": message.provider_message_id,
                },
            )
        db.flush()

    def remove_thread_star(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        *,
        allow_remote_lookup: bool = False,
        result: GmailWatchedThreadMonitorResult | None = None,
    ) -> bool:
        if autopilot_is_emergency_stopped(db):
            return False
        starred_message_ids, remote_lookup_complete = self.starred_message_ids_for_thread(
            db,
            watched,
            allow_remote_lookup=allow_remote_lookup,
        )
        remover = getattr(self.provider, "remove_message_label_for_account", None)
        account = db.get(EmailAccount, watched.email_account_id)
        failure_reason: str | None = None
        if not callable(remover):
            failure_reason = "provider_unsupported"
        elif account is None:
            failure_reason = "email_account_missing"
        elif not starred_message_ids and not remote_lookup_complete:
            failure_reason = "starred_message_id_missing"
        elif starred_message_ids:
            try:
                for message_id in sorted(starred_message_ids):
                    remover(db, account, message_id, "STARRED")
            except Exception as exc:  # noqa: BLE001 - payment accounting must not fail on label cleanup.
                failure_reason = str(exc)[:240]

        if failure_reason is not None:
            error = f"gmail_unstar:{failure_reason}"
            logger.warning("Unable to remove Gmail star for watched thread %s: %s", watched.id, failure_reason)
            if result is not None and error not in result.errors:
                result.errors.append(error)
            add_audit_log(
                db,
                entity_type="gmail_watched_thread",
                entity_id=watched.id,
                action="gmail_watched_thread.star_removal_failed",
                user_id=user.id,
                new_value={
                    "gmail_thread_id": watched.gmail_thread_id,
                    "reason": failure_reason,
                },
            )
            db.flush()
            return False

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
        db.flush()
        return True

    def starred_message_ids_for_thread(
        self,
        db: Session,
        watched: GmailWatchedThread,
        *,
        allow_remote_lookup: bool = False,
    ) -> tuple[set[str], bool]:
        message_ids = {watched.first_starred_message_id} if watched.first_starred_message_id else set()
        labels_text = cast(InboundEmailMessage.provider_labels_json, String)
        message_ids.update(
            str(message.provider_message_id)
            for message in db.scalars(
                select(InboundEmailMessage).where(
                    InboundEmailMessage.email_account_id == watched.email_account_id,
                    InboundEmailMessage.provider_thread_id == watched.gmail_thread_id,
                    InboundEmailMessage.provider_message_id.is_not(None),
                    labels_text.ilike("%STARRED%"),
                )
            ).all()
            if message.provider_message_id
        )

        remote_lookup_complete = False
        if allow_remote_lookup:
            get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
            if callable(get_thread_messages):
                account = db.get(EmailAccount, watched.email_account_id)
                if account is not None:
                    try:
                        try:
                            payloads = list(
                                get_thread_messages(
                                    db,
                                    account,
                                    watched.gmail_thread_id,
                                    include_attachments=False,
                                )
                            )
                        except TypeError:
                            payloads = list(get_thread_messages(db, account, watched.gmail_thread_id))
                    except Exception as exc:  # noqa: BLE001 - local payment accounting must still succeed.
                        logger.warning("Unable to fetch Gmail thread stars for watched thread %s: %s", watched.id, exc)
                        payloads = []
                    else:
                        remote_lookup_complete = True
                    if remote_lookup_complete:
                        message_ids = set()
                    for payload in payloads:
                        labels = {str(label).strip().upper() for label in payload.provider_labels}
                        if "STARRED" in labels and payload.provider_message_id:
                            message_ids.add(payload.provider_message_id)
        return {message_id for message_id in message_ids if message_id}, remote_lookup_complete

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


def order_identifiers_equivalent(response_identifier: str, *order_identifiers: str | None) -> bool:
    response = "".join(character for character in response_identifier.upper() if character.isalnum())
    if not response:
        return False
    response_confusion_key = response.replace("O", "0")
    for value in order_identifiers:
        candidate = "".join(character for character in str(value or "").upper() if character.isalnum())
        if candidate and (
            candidate == response or candidate.replace("O", "0") == response_confusion_key
        ):
            return True
    return False


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


def latest_datetime(*values: datetime | None) -> datetime | None:
    available = [value for value in values if value is not None]
    if not available:
        return None
    reference_tz = next((value.tzinfo for value in available if value.tzinfo is not None), None)
    comparable = [value.replace(tzinfo=reference_tz) if value.tzinfo is None and reference_tz else value for value in available]
    return max(comparable)


def datetime_within_cooldown(value: datetime | None, cooldown_hours: int) -> bool:
    if value is None or cooldown_hours <= 0:
        return False
    now = utc_now()
    if value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)
    elif value.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=value.tzinfo)
    return value + timedelta(hours=cooldown_hours) > now


def gmail_resource_not_found(exc: Exception) -> bool:
    if isinstance(exc, EmailProviderError) and exc.status_code == 404:
        return True
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "not_found",
            "requested entity was not found",
            "http 404",
            "status 404",
        )
    )


def classify_unlinked_watched_message(message: InboundEmailMessage) -> tuple[str, str, Decimal]:
    raw_text = "\n".join(
        part
        for part in (
            message.subject or "",
            message.snippet or "",
            bounded_fast_classification_body(message.body_text),
        )
        if part.strip()
    )
    text = normalize_fast_classification_text(raw_text)
    if text_has_explicit_payment_confirmation(raw_text):
        return "payment_confirmed", "fast_unlinked_payment_positive", Decimal("0.84")
    if any(marker in text for marker in FAST_REFUSAL_MARKERS):
        return "refused", "fast_unlinked_uber_refusal", Decimal("0.82")
    if any(marker in text for marker in FAST_EVIDENCE_MARKERS):
        return "evidence_requested", "fast_unlinked_evidence_requested", Decimal("0.75")
    if any(marker in text for marker in FAST_FOLLOWUP_MARKERS):
        return "followup_needed", "fast_unlinked_followup_needed", Decimal("0.66")
    return "manual_review", "fast_unlinked_manual_review", Decimal("0.50")


def normalize_fast_classification_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.replace("\xa0", " ").split())


def payload_is_uber_support_survey(payload: InboundEmailPayload) -> bool:
    """Identify standalone satisfaction surveys without hiding real decisions."""
    visible_text = " ".join(
        visible_email_text(part)
        for part in (payload.subject or "", payload.snippet or "", payload.body_text or "")
        if part
    )
    lead = normalize_fast_classification_text(visible_text[:12000])
    survey_positions = [lead.find(marker) for marker in UBER_SUPPORT_SURVEY_MARKERS if marker in lead]
    if not survey_positions:
        return False
    text_before_survey = lead[: min(survey_positions)]
    if text_has_explicit_payment_confirmation(text_before_survey):
        return False
    actionable_markers = (
        *FAST_REFUSAL_MARKERS,
        *FAST_EVIDENCE_MARKERS,
        *FAST_FOLLOWUP_MARKERS,
    )
    return not any(marker in text_before_survey for marker in actionable_markers)


def bounded_fast_classification_body(body_text: str | None) -> str:
    """Keep Gmail backlog classification cheap on very long quoted threads."""
    if not body_text:
        return ""
    limit = FAST_CLASSIFICATION_BODY_HEAD_CHARS + FAST_CLASSIFICATION_BODY_TAIL_CHARS
    if len(body_text) <= limit:
        return body_text
    return "\n".join(
        (
            body_text[:FAST_CLASSIFICATION_BODY_HEAD_CHARS],
            body_text[-FAST_CLASSIFICATION_BODY_TAIL_CHARS:],
        )
    )


def sender_filtered_starred_queries(queries: tuple[str, ...], sender_filter: str) -> tuple[str, ...]:
    cleaned = (sender_filter or "").strip()
    if not cleaned:
        return queries
    return tuple(f"{query} from:{cleaned}" for query in queries)
