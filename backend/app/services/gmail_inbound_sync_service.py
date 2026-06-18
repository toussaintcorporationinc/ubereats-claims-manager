import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import can_access_restaurant, get_accessible_restaurant_ids
from app.core.config import get_settings
from app.models import (
    ClaimOrder,
    EmailAccount,
    EmailProviderDraft,
    EmailThread,
    GmailSyncState,
    InboundEmailMessage,
    User,
)
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.autopilot_service import AutopilotError, run_autopilot
from app.services.email_provider import EmailProvider, EmailProviderError, InboundEmailPayload
from app.services.gmail_response_intelligence_service import GmailResponseIntelligenceService

FINAL_ORDER_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}
RESPONSE_UPDATABLE_ORDER_STATUSES = {"sent", "waiting_uber_response"}
MAX_BODY_TEXT_LENGTH = 20000
MAX_DB_STRING_LENGTH = 255
ACTIONABLE_NEGATIVE_REVIEW_TYPES = {"refused"}
MAX_EXISTING_REPROCESS_MESSAGES = 1000
GMAIL_STARRED_URGENT_QUERY = "is:starred"
OrderIdentifierIndex = list[tuple[ClaimOrder, list[str]]]


@dataclass
class GmailInboundSyncResult:
    status: str
    synced_messages: int = 0
    linked_messages: int = 0
    unlinked_messages: int = 0
    ignored_messages: int = 0
    analyzed_messages: int = 0
    applied_reviews: int = 0
    manual_review_messages: int = 0
    negative_responses_detected: int = 0
    autopilot_run_id: int | None = None
    autopilot_sent_count: int = 0
    autopilot_skipped_count: int = 0
    autopilot_failed_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchResult:
    order: ClaimOrder | None
    match_status: str
    match_reason: str


class GmailInboundSyncService:
    def __init__(self, provider: EmailProvider) -> None:
        self.provider = provider

    def get_active_account(self, db: Session, user: User) -> EmailAccount | None:
        return db.scalar(
            select(EmailAccount)
            .where(
                EmailAccount.user_id == user.id,
                EmailAccount.provider == "gmail",
                EmailAccount.disconnected_at.is_(None),
            )
            .order_by(EmailAccount.id.desc())
        )

    def get_active_accounts(self, db: Session, user: User) -> list[EmailAccount]:
        return list(
            db.scalars(
                select(EmailAccount)
                .where(
                    EmailAccount.user_id == user.id,
                    EmailAccount.provider == "gmail",
                    EmailAccount.disconnected_at.is_(None),
                )
                .order_by(EmailAccount.connected_at.desc(), EmailAccount.id.desc())
            ).all()
        )

    def get_or_create_sync_state(self, db: Session, account: EmailAccount) -> GmailSyncState:
        sync_state = db.scalar(select(GmailSyncState).where(GmailSyncState.email_account_id == account.id))
        if sync_state is not None:
            return sync_state
        sync_state = GmailSyncState(email_account_id=account.id, status="idle")
        db.add(sync_state)
        db.flush()
        return sync_state

    def sync(
        self,
        db: Session,
        user: User,
        *,
        lookback_days: int,
        max_messages: int,
        analyze_responses: bool = True,
        apply_reviews: bool = True,
        run_autopilot_after_sync: bool = True,
    ) -> GmailInboundSyncResult:
        accounts = self.get_active_accounts(db, user)
        if not accounts:
            raise EmailProviderError("Gmail account is not connected", 409)

        result = GmailInboundSyncResult(status="success")
        for account in accounts:
            account_result = self.sync_account(
                db,
                user,
                account,
                lookback_days=lookback_days,
                max_messages=max_messages,
                analyze_responses=analyze_responses,
                apply_reviews=apply_reviews,
            )
            result.synced_messages += account_result.synced_messages
            result.linked_messages += account_result.linked_messages
            result.unlinked_messages += account_result.unlinked_messages
            result.ignored_messages += account_result.ignored_messages
            result.analyzed_messages += account_result.analyzed_messages
            result.applied_reviews += account_result.applied_reviews
            result.manual_review_messages += account_result.manual_review_messages
            result.negative_responses_detected += account_result.negative_responses_detected
            result.errors.extend(account_result.errors)
            if account_result.status == "failed":
                result.status = "failed"
        if run_autopilot_after_sync and apply_reviews and result.negative_responses_detected > 0:
            self.run_autopilot_for_negative_responses(db, user, result)
        return result

    def sync_account(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        lookback_days: int,
        max_messages: int,
        analyze_responses: bool = True,
        apply_reviews: bool = True,
        reprocess_existing_limit: int | None = None,
    ) -> GmailInboundSyncResult:
        sync_state = self.get_or_create_sync_state(db, account)
        sync_state.status = "running"
        sync_state.last_sync_at = utc_now()
        sync_state.last_error = None
        add_audit_log(
            db,
            entity_type="gmail_sync_state",
            entity_id=sync_state.id,
            action="gmail_inbound_sync.started",
            user_id=user.id,
            new_value={"lookback_days": lookback_days, "max_messages": max_messages},
        )
        db.flush()
        # Do not hold the sync-state row lock while Gmail/OpenAI network calls run.
        # Background cycles must stay short and recoverable instead of blocking
        # every following sync attempt behind one long external request.
        db.commit()

        query = f"newer_than:{lookback_days}d"
        result = GmailInboundSyncResult(status="success")
        created_message_ids: set[int] = set()
        try:
            starred_max_messages = max(0, min(max_messages, get_settings().gmail_starred_max_messages_per_sync))
            payloads = merge_unique_payloads(
                self.fetch_payloads(db, user, account, query=query, max_messages=max_messages),
                self.fetch_payloads(
                    db,
                    user,
                    account,
                    query=GMAIL_STARRED_URGENT_QUERY,
                    max_messages=starred_max_messages,
                ),
            )
            for payload in payloads:
                if not payload.provider_message_id:
                    result.errors.append("Skipped Gmail message without provider_message_id")
                    continue
                existing_message = self.get_existing_message(db, account, payload.provider_message_id)
                if existing_message is not None:
                    if self.refresh_existing_message_from_payload(db, user, existing_message, payload):
                        created_message_ids.add(existing_message.id)
                        result.synced_messages += 1
                        self.reprocess_existing_message(db, user, account, existing_message, result, apply_reviews=apply_reviews)
                    continue
                inbound_message = self.create_inbound_message(db, user, account, payload)
                created_message_ids.add(inbound_message.id)
                result.synced_messages += 1
                if inbound_message.match_status == "linked":
                    result.linked_messages += 1
                    if analyze_responses and should_analyze_message(inbound_message, account):
                        self.analyze_linked_message(db, user, inbound_message, result, apply_reviews=apply_reviews)
                elif inbound_message.match_status == "ignored":
                    result.ignored_messages += 1
                else:
                    result.unlinked_messages += 1
                    if analyze_responses and sender_matches_filter(
                        inbound_message.from_email,
                        get_settings().gmail_support_sender_filter,
                    ):
                        self.analyze_unlinked_message(db, user, inbound_message, result)

            if analyze_responses:
                self.reprocess_unreviewed_messages(
                    db,
                    user,
                    account,
                    result,
                    apply_reviews=apply_reviews,
                    max_messages=max_messages if reprocess_existing_limit is None else reprocess_existing_limit,
                    exclude_message_ids=created_message_ids,
                )

            sync_state.status = "success"
            sync_state.last_success_at = utc_now()
            sync_state.last_error = None
            add_audit_log(
                db,
                entity_type="gmail_sync_state",
                entity_id=sync_state.id,
                action="gmail_inbound_sync.success",
                user_id=user.id,
                new_value=result.__dict__,
            )
        except EmailProviderError as exc:
            sync_state.status = "failed"
            sync_state.last_error = exc.message
            add_audit_log(
                db,
                entity_type="gmail_sync_state",
                entity_id=sync_state.id,
                action="gmail_inbound_sync.failed",
                user_id=user.id,
                new_value={"error": exc.message},
            )
            raise

        return result

    def fetch_payloads(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        *,
        query: str,
        max_messages: int,
    ) -> list[InboundEmailPayload]:
        sync_for_account = getattr(self.provider, "sync_inbound_replies_for_account", None)
        if callable(sync_for_account):
            return sync_for_account(db, account, query=query, max_results=max_messages)
        return self.provider.sync_inbound_replies(db, user, query=query, max_results=max_messages)

    def analyze_linked_message(
        self,
        db: Session,
        user: User,
        inbound_message: InboundEmailMessage,
        result: GmailInboundSyncResult,
        *,
        apply_reviews: bool,
    ) -> None:
        analysis = GmailResponseIntelligenceService().analyze_message(
            db,
            user,
            inbound_message,
            apply_review=apply_reviews,
        )
        if analysis.status == "applied":
            result.applied_reviews += 1
            if analysis.recommended_review_type in ACTIONABLE_NEGATIVE_REVIEW_TYPES:
                result.negative_responses_detected += 1
        elif analysis.status == "manual_review":
            result.manual_review_messages += 1
        elif analysis.status == "failed":
            result.errors.append(analysis.error_message or "Gmail response analysis failed")
        else:
            result.analyzed_messages += 1

    def analyze_unlinked_message(
        self,
        db: Session,
        user: User,
        inbound_message: InboundEmailMessage,
        result: GmailInboundSyncResult,
    ) -> None:
        analysis = GmailResponseIntelligenceService().analyze_message(
            db,
            user,
            inbound_message,
            apply_review=False,
        )
        if analysis.status == "manual_review":
            result.manual_review_messages += 1
        elif analysis.status == "failed":
            result.errors.append(analysis.error_message or "Gmail response analysis failed")
        else:
            result.analyzed_messages += 1

    def reprocess_unreviewed_messages(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        result: GmailInboundSyncResult,
        *,
        apply_reviews: bool,
        max_messages: int,
        exclude_message_ids: set[int],
    ) -> None:
        order_identifier_index = self.build_order_identifier_index(db, user)
        messages = db.scalars(
            select(InboundEmailMessage)
            .where(
                InboundEmailMessage.email_account_id == account.id,
                InboundEmailMessage.review_status == "unreviewed",
                InboundEmailMessage.match_status.in_(["linked", "unlinked"]),
            )
            .order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
            .limit(max(0, min(max_messages, MAX_EXISTING_REPROCESS_MESSAGES)))
        ).all()
        for message in messages:
            if message.id in exclude_message_ids:
                continue
            if message.match_status == "unlinked":
                match = self.match_message(
                    db,
                    user,
                    account,
                    inbound_payload_from_message(message),
                    order_identifier_index=order_identifier_index,
                )
                if match.order is not None and match.match_status == "linked":
                    self.record_linked_message(db, user, message, match.order, match_reason=match.match_reason)
                    result.linked_messages += 1
                    self.analyze_linked_message(db, user, message, result, apply_reviews=apply_reviews)
                elif sender_matches_filter(message.from_email, get_settings().gmail_support_sender_filter):
                    self.analyze_unlinked_message(db, user, message, result)
                continue
            if message.match_status == "linked" and message.order_id is not None:
                if should_analyze_message(message, account):
                    self.analyze_linked_message(db, user, message, result, apply_reviews=apply_reviews)

    def run_autopilot_for_negative_responses(
        self,
        db: Session,
        user: User,
        result: GmailInboundSyncResult,
    ) -> None:
        settings = get_settings()
        if not settings.autopilot_enabled or not settings.autopilot_appeals_enabled:
            return
        try:
            autopilot_result = run_autopilot(
                db,
                user,
                mode="appeals",
                restaurant_id=None,
                dry_run=False,
                provider=self.provider,
            )
        except AutopilotError as exc:
            result.errors.append(f"autopilot:{exc.message}")
            return

        result.autopilot_run_id = autopilot_result.run.id
        result.autopilot_sent_count = autopilot_result.run.sent_count
        result.autopilot_skipped_count = autopilot_result.run.skipped_count
        result.autopilot_failed_count = autopilot_result.run.failed_count

    def get_existing_message(
        self,
        db: Session,
        account: EmailAccount,
        provider_message_id: str,
    ) -> InboundEmailMessage | None:
        return db.scalar(
            select(InboundEmailMessage).where(
                InboundEmailMessage.email_account_id == account.id,
                InboundEmailMessage.provider_message_id == provider_message_id,
            )
        )

    def refresh_existing_message_from_payload(
        self,
        db: Session,
        user: User,
        message: InboundEmailMessage,
        payload: InboundEmailPayload,
    ) -> bool:
        old_labels = normalize_gmail_labels(message.provider_labels_json)
        new_labels = normalize_gmail_labels(payload.provider_labels)
        newly_starred = "STARRED" in new_labels and "STARRED" not in old_labels
        content_changed = any(
            (
                truncate_db_string(payload.provider_thread_id) != message.provider_thread_id,
                truncate_db_string(payload.gmail_history_id) != message.gmail_history_id,
                truncate_db_string(payload.subject) != message.subject,
                payload.snippet != message.snippet,
                (payload.body_text or "")[:MAX_BODY_TEXT_LENGTH] != (message.body_text or ""),
                old_labels != new_labels,
            )
        )
        if not content_changed:
            return False

        message.provider_thread_id = truncate_db_string(payload.provider_thread_id)
        message.gmail_history_id = truncate_db_string(payload.gmail_history_id)
        message.from_email = truncate_db_string(payload.from_email)
        message.to_email = truncate_db_string(payload.to_email)
        message.subject = truncate_db_string(payload.subject)
        message.snippet = payload.snippet
        message.body_text = (payload.body_text or "")[:MAX_BODY_TEXT_LENGTH] if payload.body_text else None
        message.received_at = payload.received_at or message.received_at
        message.raw_headers_json = payload.raw_headers
        message.provider_labels_json = list(new_labels)
        if newly_starred:
            message.review_status = "unreviewed"
            message.reviewed_at = None
            message.reviewed_by_user_id = None
        db.flush()
        add_audit_log(
            db,
            entity_type="inbound_email_message",
            entity_id=message.id,
            action="gmail_inbound_message.updated_from_provider",
            user_id=user.id,
            new_value={
                "provider_message_id": message.provider_message_id,
                "newly_starred": newly_starred,
                "labels": list(new_labels),
            },
        )
        return newly_starred

    def reprocess_existing_message(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        message: InboundEmailMessage,
        result: GmailInboundSyncResult,
        *,
        apply_reviews: bool,
    ) -> None:
        if message.match_status == "unlinked":
            match = self.match_message(db, user, account, inbound_payload_from_message(message))
            if match.order is not None and match.match_status == "linked":
                self.record_linked_message(db, user, message, match.order, match_reason=match.match_reason)
                result.linked_messages += 1
                self.analyze_linked_message(db, user, message, result, apply_reviews=apply_reviews)
            elif sender_matches_filter(message.from_email, get_settings().gmail_support_sender_filter):
                self.analyze_unlinked_message(db, user, message, result)
            return
        if message.match_status == "linked" and message.order_id is not None:
            if should_analyze_message(message, account):
                self.analyze_linked_message(db, user, message, result, apply_reviews=apply_reviews)

    def create_inbound_message(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        payload: InboundEmailPayload,
    ) -> InboundEmailMessage:
        match = self.match_message(db, user, account, payload)
        inbound_message = InboundEmailMessage(
            email_account_id=account.id,
            order_id=match.order.id if match.order else None,
            provider="gmail",
            provider_message_id=truncate_db_string(payload.provider_message_id),
            provider_thread_id=truncate_db_string(payload.provider_thread_id),
            gmail_history_id=truncate_db_string(payload.gmail_history_id),
            from_email=truncate_db_string(payload.from_email),
            to_email=truncate_db_string(payload.to_email),
            subject=truncate_db_string(payload.subject),
            snippet=payload.snippet,
            body_text=(payload.body_text or "")[:MAX_BODY_TEXT_LENGTH] if payload.body_text else None,
            received_at=payload.received_at,
            raw_headers_json=payload.raw_headers,
            provider_labels_json=payload.provider_labels,
            match_status=match.match_status,
            match_reason=match.match_reason,
        )
        db.add(inbound_message)
        db.flush()

        if match.order is not None and match.match_status == "linked":
            self.record_linked_message(db, user, inbound_message, match.order, match_reason=match.match_reason)
        elif match.match_status == "unlinked":
            add_audit_log(
                db,
                entity_type="inbound_email_message",
                entity_id=inbound_message.id,
                action="gmail_inbound_message.unlinked",
                user_id=user.id,
                new_value={
                    "provider_message_id": inbound_message.provider_message_id,
                    "match_reason": inbound_message.match_reason,
                },
            )

        return inbound_message

    def match_message(
        self,
        db: Session,
        user: User,
        account: EmailAccount,
        payload: InboundEmailPayload,
        *,
        order_identifier_index: OrderIdentifierIndex | None = None,
    ) -> MatchResult:
        own_sender = same_email(payload.from_email, account.email_address)
        labels = normalize_gmail_labels(payload.provider_labels)

        if own_sender and "STARRED" in labels:
            thread_order = self.match_by_thread(db, user, payload.provider_thread_id)
            if thread_order is not None:
                return MatchResult(thread_order, "linked", "thread_id_match")

        if own_sender:
            return MatchResult(None, "ignored", "ignored_sender")

        thread_order = self.match_by_thread(db, user, payload.provider_thread_id)
        if thread_order is not None:
            return MatchResult(thread_order, "linked", "thread_id_match")

        if not sender_matches_filter(payload.from_email, get_settings().gmail_support_sender_filter):
            return MatchResult(None, "ignored", "ignored_sender")

        order_from_subject = self.match_by_order_number(
            db,
            user,
            payload.subject or "",
            order_identifier_index=order_identifier_index,
        )
        if order_from_subject is not None:
            return MatchResult(order_from_subject, "linked", "subject_match")

        order_from_body = self.match_by_order_number(
            db,
            user,
            payload.body_text or "",
            order_identifier_index=order_identifier_index,
        )
        if order_from_body is not None:
            return MatchResult(order_from_body, "linked", "order_number_match")

        return MatchResult(None, "unlinked", "no_match")

    def match_by_thread(self, db: Session, user: User, provider_thread_id: str | None) -> ClaimOrder | None:
        if not provider_thread_id:
            return None

        email_thread = db.scalar(
            select(EmailThread)
            .where(
                EmailThread.provider == "gmail",
                EmailThread.thread_id == provider_thread_id,
            )
            .order_by(EmailThread.id.desc())
        )
        if email_thread and can_access_restaurant(db, user, email_thread.order.restaurant_id):
            return email_thread.order

        provider_draft = db.scalar(
            select(EmailProviderDraft)
            .where(EmailProviderDraft.provider_thread_id == provider_thread_id)
            .order_by(EmailProviderDraft.id.desc())
        )
        if provider_draft and can_access_restaurant(db, user, provider_draft.email_draft.order.restaurant_id):
            return provider_draft.email_draft.order
        return None

    def build_order_identifier_index(self, db: Session, user: User) -> OrderIdentifierIndex:
        query = select(ClaimOrder).options(selectinload(ClaimOrder.customer_refund_disputes))
        accessible_restaurant_ids = get_accessible_restaurant_ids(db, user)
        if accessible_restaurant_ids is not None:
            if not accessible_restaurant_ids:
                return []
            query = query.where(ClaimOrder.restaurant_id.in_(accessible_restaurant_ids))
        return [
            (order, candidates)
            for order in db.scalars(query).all()
            if (candidates := order_identifier_candidates(order))
        ]

    def match_by_order_number(
        self,
        db: Session,
        user: User,
        text: str,
        *,
        order_identifier_index: OrderIdentifierIndex | None = None,
    ) -> ClaimOrder | None:
        if not text:
            return None
        index = order_identifier_index
        if index is None:
            index = self.build_order_identifier_index(db, user)
        normalized_text = normalize_identifier(text)
        compact_text = normalize_identifier_with_boundaries(text)
        identifier_tokens = {normalize_identifier(token) for token in compact_text.split() if token}
        for order, candidates in index:
            for candidate in candidates:
                if text_contains_identifier(
                    text,
                    candidate,
                    normalized_text=normalized_text,
                    compact_text=compact_text,
                    identifier_tokens=identifier_tokens,
                ):
                    return order
        return None

    def record_linked_message(
        self,
        db: Session,
        user: User,
        inbound_message: InboundEmailMessage,
        order: ClaimOrder,
        *,
        match_reason: str,
    ) -> None:
        if inbound_message.order_id != order.id:
            inbound_message.order_id = order.id
        inbound_message.match_status = "linked"
        inbound_message.match_reason = match_reason
        existing_thread = db.scalar(
            select(EmailThread).where(
                EmailThread.provider == "gmail",
                EmailThread.direction == "inbound",
                EmailThread.message_id == inbound_message.provider_message_id,
            )
        )
        if existing_thread is None:
            db.add(
                EmailThread(
                    order_id=order.id,
                    provider="gmail",
                    thread_id=inbound_message.provider_thread_id,
                    message_id=inbound_message.provider_message_id,
                    direction="inbound",
                    subject=inbound_message.subject,
                    body=inbound_message.body_text,
                    ai_classification="not_classified",
                    received_at=inbound_message.received_at,
                )
            )
        if order.status in RESPONSE_UPDATABLE_ORDER_STATUSES:
            order.status = "response_received"
            order.updated_at = utc_now()

        add_audit_log(
            db,
            entity_type="inbound_email_message",
            entity_id=inbound_message.id,
            action="gmail_inbound_message.linked",
            user_id=user.id,
            new_value={
                "order_id": order.id,
                "provider_message_id": inbound_message.provider_message_id,
                "match_reason": match_reason,
            },
        )


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
    )


def normalize_gmail_labels(labels: list[str] | None) -> tuple[str, ...]:
    return tuple(sorted({str(label).strip().upper() for label in labels or [] if str(label).strip()}))


def merge_unique_payloads(*payload_groups: list[InboundEmailPayload]) -> list[InboundEmailPayload]:
    merged: list[InboundEmailPayload] = []
    seen: set[str] = set()
    for payloads in payload_groups:
        for payload in payloads:
            message_id = payload.provider_message_id
            if message_id and message_id in seen:
                continue
            if message_id:
                seen.add(message_id)
            merged.append(payload)
    return merged


def order_identifier_candidates(order: ClaimOrder) -> list[str]:
    values = [order.uber_order_number, order.internal_reference]
    if order.internal_reference and order.internal_reference.startswith("PROOF-"):
        values.append(order.internal_reference.removeprefix("PROOF-"))
    for dispute in order.customer_refund_disputes:
        values.extend([dispute.uber_order_id, dispute.display_id, dispute.customer_refund_reference])
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def text_contains_identifier(
    text: str,
    candidate: str,
    *,
    normalized_text: str | None = None,
    compact_text: str | None = None,
    identifier_tokens: set[str] | None = None,
) -> bool:
    cleaned = candidate.strip()
    if not cleaned:
        return False
    normalized_candidate = normalize_identifier(cleaned)
    if len(normalized_candidate) < 4:
        return False
    if len(normalized_candidate) >= 12:
        return normalized_candidate in (normalized_text if normalized_text is not None else normalize_identifier(text))
    if identifier_tokens is not None:
        return normalized_candidate in identifier_tokens
    escaped = re.escape(cleaned.lstrip("#"))
    if not escaped:
        return False
    pattern = re.compile(rf"(?<![A-Z0-9])#?{escaped}(?![A-Z0-9])", re.IGNORECASE)
    if pattern.search(text):
        return True
    compact_text = compact_text if compact_text is not None else normalize_identifier_with_boundaries(text)
    compact_candidate = re.escape(normalized_candidate)
    return re.search(rf"(?<![A-Z0-9]){compact_candidate}(?![A-Z0-9])", compact_text) is not None


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def normalize_identifier_with_boundaries(value: str) -> str:
    return re.sub(r"[^A-Z0-9#]+", " ", value.upper())


def truncate_db_string(value: str | None, max_length: int = MAX_DB_STRING_LENGTH) -> str | None:
    if value is None:
        return None
    return value[:max_length]


def same_email(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.strip().casefold() == right.strip().casefold())


def should_analyze_message(message: InboundEmailMessage, account: EmailAccount) -> bool:
    return not same_email(message.from_email, account.email_address)


def sender_matches_filter(from_email: str | None, sender_filter: str) -> bool:
    if not sender_filter:
        return True
    if not from_email:
        return False
    return sender_filter.strip().casefold() in from_email.casefold()
