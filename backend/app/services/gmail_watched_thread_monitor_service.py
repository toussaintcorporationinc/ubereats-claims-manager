from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import unicodedata

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AppealAttempt,
    ClaimOrder,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
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
from app.services.email_draft_service import EmailDraftBusinessError, create_email_draft
from app.services.gmail_inbound_sync_service import (
    GMAIL_STARRED_URGENT_QUERIES,
    GmailInboundSyncResult,
    GmailInboundSyncService,
    sender_matches_filter,
    starred_payload_identity_context,
)
from app.services.gmail_quota import parse_gmail_retry_after
from app.services.gmail_scope_service import gmail_scopes_allow_modify
from app.services.autopilot_identity_repair_service import find_or_create_order_from_starred_text
from app.services.appeal_workflow_service import AppealWorkflowError, ensure_workflow_for_claim_order, mark_appeal_sent
from app.services.autopilot_service import (
    AutopilotError,
    create_starred_thread_reply_attempt,
    safe_autopilot_recipient,
    send_provider_draft,
)
from app.services.restaurant_identity_service import text_contains_legacy_restaurant_name

logger = logging.getLogger(__name__)

FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed", "manual_review", "skipped"}
SKIPPABLE_FINAL_WORK_ITEM_STATUSES = {"processed", "positive", "refused", "evidence_needed"}
POSITIVE_REVIEW_TYPES = {"accepted", "payment_to_verify", "payment_confirmed"}
POSITIVE_WATCHED_STATUSES = {"positive", "payment_confirmed"}
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
    "sera credite",
    "sera ajoute a votre prochain versement",
    "sera ajoutee a votre prochain versement",
    "apparaitra dans votre prochain versement",
    "apparaitra sur votre prochain versement",
    "ajoute a votre prochain versement",
    "ajoutee a votre prochain versement",
    "nous avons applique un ajustement",
    "ajustement a ete applique",
    "nous avons procede au paiement",
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
            can_modify_stars = gmail_scopes_allow_modify(account.scopes)
            active_threads = self.get_active_watched_threads(
                db,
                account,
                max_per_cycle=remaining_thread_budget,
                include_positive_star_cleanup=can_modify_stars,
            )
            if not can_modify_stars and self.count_pending_positive_star_cleanup(db, account):
                result.errors.append("gmail_unstar:reconnect_required:gmail.modify")
        result.watched_threads_seen += len(active_threads)
        order_identifier_index = (
            self.sync_service.build_order_identifier_index(db, user) if active_threads else {}
        )

        for watched in active_threads:
            if watched.status in POSITIVE_WATCHED_STATUSES:
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
                payloads = self.fetch_thread_payloads(db, account, watched)
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
                max_items=max(1, min(max_per_cycle, self.settings.gmail_watched_threads_batch_per_cycle)),
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
    ) -> int:
        """Send same-thread Gmail relances for actionable watched work items.

        This intentionally avoids the historical global AutoPilot scan. The Gmail
        worker must keep moving through thousands of starred threads, so it only
        handles items that are already in the watched-thread queue.
        """
        if max_items <= 0:
            return 0
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
                            GmailResponseAnalysis.recommended_review_type == "followup_needed",
                        ),
                    ),
                    GmailWatchedThread.status.in_(["active", "manual_review"]),
                    GmailWatchedThread.star_active.is_(True),
                )
                .order_by(
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
                .limit(max_items)
            ).all()
        )
        sent_count = 0
        sent_threads: set[str] = set()
        for item in items:
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
            if self.send_actionable_reply_for_work_item(db, user, account, watched, item, message, result):
                sent_threads.add(watched.gmail_thread_id)
                sent_count += 1
        return sent_count

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

        order = message.order or (db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else None)
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
            if exc.message == "gmail_account_daily_limit_reached":
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

        order = message.order or (db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else None)
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
            if exc.message == "gmail_account_daily_limit_reached":
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

        order = message.order or (db.get(ClaimOrder, watched.claim_order_id) if watched.claim_order_id else None)
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

        try:
            if provider_draft is None or provider_draft.status != "provider_draft_created":
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
            if exc.message == "gmail_account_daily_limit_reached":
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
            and sender_matches_filter(payload.from_email, self.settings.gmail_support_sender_filter)
            and not payload_is_uber_support_survey(payload)
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

        def fetch_full_thread() -> list[InboundEmailPayload]:
            if not callable(get_thread_messages):
                return []
            try:
                return list(get_thread_messages(db, account, watched.gmail_thread_id, include_attachments=False))
            except TypeError:
                return list(get_thread_messages(db, account, watched.gmail_thread_id))

        if prefer_full_thread and watched.claim_order_id is None and callable(get_thread_messages):
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
        *,
        allow_remote_star_lookup: bool = False,
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
            self.remove_thread_star(
                db,
                user,
                watched,
                allow_remote_lookup=allow_remote_star_lookup,
                result=result,
            )
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

    def remove_thread_star(
        self,
        db: Session,
        user: User,
        watched: GmailWatchedThread,
        *,
        allow_remote_lookup: bool = False,
        result: GmailWatchedThreadMonitorResult | None = None,
    ) -> bool:
        starred_message_ids = self.starred_message_ids_for_thread(db, watched, allow_remote_lookup=allow_remote_lookup)
        remover = getattr(self.provider, "remove_message_label_for_account", None)
        account = db.get(EmailAccount, watched.email_account_id)
        failure_reason: str | None = None
        if not callable(remover):
            failure_reason = "provider_unsupported"
        elif account is None:
            failure_reason = "email_account_missing"
        elif not starred_message_ids:
            failure_reason = "starred_message_id_missing"
        else:
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
    ) -> set[str]:
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

        if allow_remote_lookup:
            get_thread_messages = getattr(self.provider, "get_thread_messages_for_account", None)
            if callable(get_thread_messages):
                account = db.get(EmailAccount, watched.email_account_id)
                if account is not None:
                    try:
                        payloads = list(get_thread_messages(db, account, watched.gmail_thread_id, include_attachments=False))
                    except TypeError:
                        payloads = list(get_thread_messages(db, account, watched.gmail_thread_id))
                    except Exception as exc:  # noqa: BLE001 - local payment accounting must still succeed.
                        logger.warning("Unable to fetch Gmail thread stars for watched thread %s: %s", watched.id, exc)
                        payloads = []
                    for payload in payloads:
                        labels = {str(label).strip().upper() for label in payload.provider_labels}
                        if "STARRED" in labels and payload.provider_message_id:
                            message_ids.add(payload.provider_message_id)
        return {message_id for message_id in message_ids if message_id}

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
    text = normalize_fast_classification_text(
        "\n".join(
            part
            for part in (
                message.subject or "",
                message.snippet or "",
                bounded_fast_classification_body(message.body_text),
            )
            if part.strip()
        )
    )
    if any(marker in text for marker in FAST_POSITIVE_MARKERS):
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
    subject = normalize_fast_classification_text(payload.subject or "")
    body_head = normalize_fast_classification_text((payload.body_text or "")[:1200])
    lead = f"{subject} {body_head[:500]}".strip()
    survey_positions = [lead.find(marker) for marker in UBER_SUPPORT_SURVEY_MARKERS if marker in lead]
    if not survey_positions:
        return False
    text_before_survey = lead[: min(survey_positions)]
    actionable_markers = (
        *FAST_POSITIVE_MARKERS,
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
