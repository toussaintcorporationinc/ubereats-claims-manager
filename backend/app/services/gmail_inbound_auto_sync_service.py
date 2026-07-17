from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models import EmailAccount, GmailSyncState, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.email_provider import EmailProvider, EmailProviderError
from app.services.gmail_email_provider import GmailEmailProvider
from app.services.gmail_inbound_sync_service import GmailInboundSyncResult, GmailInboundSyncService
from app.services.gmail_quota import parse_gmail_retry_after, parse_gmail_retry_after_from_errors
from app.services.gmail_watched_thread_monitor_service import (
    GmailWatchedThreadMonitorResult,
    GmailWatchedThreadMonitorService,
)

logger = logging.getLogger(__name__)

MIN_AUTO_SYNC_INTERVAL_SECONDS = 15
MIN_CONTINUOUS_IDLE_SLEEP_SECONDS = 1
CONTINUOUS_RUNNING_STALE_AFTER_SECONDS = 60


@dataclass
class GmailInboundAutoSyncResult:
    status: str
    accounts_checked: int = 0
    accounts_synced: int = 0
    accounts_skipped: int = 0
    synced_messages: int = 0
    linked_messages: int = 0
    ignored_messages: int = 0
    unlinked_messages: int = 0
    applied_reviews: int = 0
    negative_responses_detected: int = 0
    identity_repaired_messages: int = 0
    starred_messages_seen: int = 0
    watched_threads_seen: int = 0
    watched_threads_created: int = 0
    watched_thread_new_messages: int = 0
    watched_thread_processed_messages: int = 0
    watched_thread_positive_responses: int = 0
    watched_thread_refused_responses: int = 0
    watched_thread_actionable_refused_threads: int = 0
    watched_thread_evidence_requests: int = 0
    watched_thread_manual_reviews: int = 0
    autopilot_sent_count: int = 0
    autopilot_skipped_count: int = 0
    autopilot_failed_count: int = 0
    workspace_machine_runs: int = 0
    workspace_machine_warnings: int = 0
    workspace_machine_failures: int = 0
    errors: list[str] = field(default_factory=list)


class GmailInboundAutoSyncService:
    def __init__(self, provider: EmailProvider | None = None, settings: Settings | None = None) -> None:
        self.provider = provider or GmailEmailProvider()
        self.settings = settings or get_settings()

    def enabled(self) -> bool:
        return (
            self.settings.email_provider_enabled
            and self.settings.gmail_inbound_sync_enabled
            and self.settings.gmail_inbound_auto_sync_enabled
        )

    def sync_due_accounts(self, db: Session) -> GmailInboundAutoSyncResult:
        if not self.enabled():
            return GmailInboundAutoSyncResult(status="disabled")

        sync_service = GmailInboundSyncService(self.provider)
        watched_thread_monitor = GmailWatchedThreadMonitorService(
            self.provider,
            settings=self.settings,
            sync_service=sync_service,
        )
        result = GmailInboundAutoSyncResult(status="success")
        now = utc_now()
        accounts = list(db.scalars(self.active_accounts_statement()).all())
        users_needing_workspace_machine: dict[int, User] = {}
        for account in accounts:
            account_id = account.id
            user = db.get(User, account.user_id)
            if user is None or not user.active or user.role == "staff":
                result.accounts_skipped += 1
                continue

            sync_state = sync_service.get_or_create_sync_state(db, account)
            if not self.account_is_due(sync_state, now):
                result.accounts_skipped += 1
                continue

            result.accounts_checked += 1
            try:
                if self.settings.gmail_watched_threads_enabled:
                    watched_result = watched_thread_monitor.process_account(
                        db,
                        user,
                        account,
                        max_threads=self.watched_threads_batch_size(),
                        discover_starred=True,
                        discover_full_history=False,
                        starred_discovery_max_messages=self.watched_threads_batch_size(),
                        process_new_messages=self.settings.gmail_watched_threads_process_new_messages,
                    )
                    self.add_watched_thread_result(result, watched_result)
                    retry_after = parse_gmail_retry_after_from_errors(
                        watched_result.errors,
                        safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
                        now=now,
                    )
                    if retry_after is not None:
                        self.mark_sync_failure(
                            db,
                            sync_service,
                            account_id,
                            user.id,
                            f"Gmail quota reached. Retry after {retry_after.isoformat()}",
                        )
                    else:
                        self.mark_sync_success(db, sync_service, account_id, user.id, watched_result)
                    db.commit()
                    result.accounts_synced += 1
                    continue

                account_result = sync_service.sync_account(
                    db,
                    user,
                    account,
                    lookback_days=self.settings.gmail_inbound_sync_lookback_days,
                    max_messages=self.settings.gmail_inbound_max_messages_per_sync,
                    analyze_responses=True,
                    apply_reviews=True,
                    reprocess_existing_limit=self.settings.gmail_inbound_auto_sync_existing_reprocess_limit,
                )
                if self.settings.gmail_inbound_auto_sync_run_autopilot and sync_service.should_run_autopilot_for_result(
                    db,
                    user,
                    account_result,
                ):
                    sync_service.run_autopilot_for_negative_responses(db, user, account_result)
                self.add_account_result(result, account_result)
                result.accounts_synced += 1
                users_needing_workspace_machine[user.id] = user
                db.commit()
            except EmailProviderError as exc:
                db.rollback()
                self.mark_sync_failure(db, sync_service, account_id, user.id, exc.message)
                result.errors.append(f"email_account:{account_id}:{exc.message}")
            except Exception as exc:  # noqa: BLE001 - background sync must not kill the scheduler loop.
                db.rollback()
                logger.exception("Gmail auto-sync failed for account %s", account_id)
                error_message = str(exc)[:2000]
                self.mark_sync_failure(db, sync_service, account_id, user.id, error_message)
                result.errors.append(f"email_account:{account_id}:{error_message[:200]}")

        if self.settings.gmail_inbound_auto_sync_run_workspace_machine:
            for user in users_needing_workspace_machine.values():
                self.run_workspace_machine(db, user, result)

        if result.accounts_checked or result.errors:
            add_audit_log(
                db,
                entity_type="gmail_auto_sync",
                entity_id=0,
                action="gmail_auto_sync.cycle",
                user_id=None,
                new_value={
                    "accounts_checked": result.accounts_checked,
                    "accounts_synced": result.accounts_synced,
                    "accounts_skipped": result.accounts_skipped,
                    "synced_messages": result.synced_messages,
                    "applied_reviews": result.applied_reviews,
                    "negative_responses_detected": result.negative_responses_detected,
                    "identity_repaired_messages": result.identity_repaired_messages,
                    "starred_messages_seen": result.starred_messages_seen,
                    "watched_threads_seen": result.watched_threads_seen,
                    "watched_threads_created": result.watched_threads_created,
                    "watched_thread_new_messages": result.watched_thread_new_messages,
                    "watched_thread_processed_messages": result.watched_thread_processed_messages,
                    "watched_thread_positive_responses": result.watched_thread_positive_responses,
                    "watched_thread_refused_responses": result.watched_thread_refused_responses,
                    "watched_thread_actionable_refused_threads": (
                        result.watched_thread_actionable_refused_threads
                    ),
                    "watched_thread_evidence_requests": result.watched_thread_evidence_requests,
                    "watched_thread_manual_reviews": result.watched_thread_manual_reviews,
                    "autopilot_sent_count": result.autopilot_sent_count,
                    "autopilot_skipped_count": result.autopilot_skipped_count,
                    "autopilot_failed_count": result.autopilot_failed_count,
                    "workspace_machine_runs": result.workspace_machine_runs,
                    "workspace_machine_warnings": result.workspace_machine_warnings,
                    "workspace_machine_failures": result.workspace_machine_failures,
                    "errors": result.errors,
                },
            )
        if result.errors and result.accounts_synced == 0:
            result.status = "failed"
        return result

    def active_accounts_statement(self):
        return (
            select(EmailAccount)
            .join(User, EmailAccount.user_id == User.id)
            .where(
                EmailAccount.provider == "gmail",
                EmailAccount.disconnected_at.is_(None),
                User.active.is_(True),
                User.role.in_(("owner", "manager")),
            )
            .order_by(EmailAccount.id)
        )

    def account_is_due(self, sync_state: GmailSyncState, now: datetime) -> bool:
        last_sync_at = normalize_datetime(sync_state.last_sync_at) if sync_state.last_sync_at is not None else None
        interval_seconds = self.effective_interval_seconds()
        retry_after = parse_gmail_retry_after(
            sync_state.last_error,
            safety_seconds=self.settings.gmail_quota_retry_safety_seconds,
            now=now,
        )
        if retry_after is not None:
            return False
        if sync_state.status == "running":
            if last_sync_at is None:
                return True
            stale_after_seconds = (
                max(CONTINUOUS_RUNNING_STALE_AFTER_SECONDS, interval_seconds * 4)
                if self.settings.gmail_inbound_auto_sync_continuous_enabled
                else max(interval_seconds * 4, 300)
            )
            return now >= last_sync_at + timedelta(seconds=stale_after_seconds)
        if self.settings.gmail_inbound_auto_sync_continuous_enabled:
            return True
        if last_sync_at is None:
            return True
        return now >= last_sync_at + timedelta(seconds=interval_seconds)

    def watched_threads_batch_size(self) -> int:
        configured_batch = max(1, self.settings.gmail_watched_threads_batch_per_cycle)
        configured_max = max(1, self.settings.gmail_watched_threads_max_per_cycle)
        return min(configured_batch, configured_max)

    def effective_interval_seconds(self) -> int:
        if self.settings.gmail_inbound_auto_sync_continuous_enabled:
            return max(MIN_CONTINUOUS_IDLE_SLEEP_SECONDS, self.settings.gmail_inbound_auto_sync_idle_sleep_seconds)
        return max(MIN_AUTO_SYNC_INTERVAL_SECONDS, self.settings.gmail_inbound_auto_sync_interval_seconds)

    def add_account_result(self, result: GmailInboundAutoSyncResult, account_result: GmailInboundSyncResult) -> None:
        result.synced_messages += account_result.synced_messages
        result.linked_messages += account_result.linked_messages
        result.ignored_messages += account_result.ignored_messages
        result.unlinked_messages += account_result.unlinked_messages
        result.applied_reviews += account_result.applied_reviews
        result.negative_responses_detected += account_result.negative_responses_detected
        result.identity_repaired_messages += account_result.identity_repaired_messages
        result.starred_messages_seen += account_result.starred_messages_seen
        result.autopilot_sent_count += account_result.autopilot_sent_count
        result.autopilot_skipped_count += account_result.autopilot_skipped_count
        result.autopilot_failed_count += account_result.autopilot_failed_count
        result.errors.extend(account_result.errors)

    def add_watched_thread_result(
        self,
        result: GmailInboundAutoSyncResult,
        watched_result: GmailWatchedThreadMonitorResult,
    ) -> None:
        result.watched_threads_seen += watched_result.watched_threads_seen
        result.watched_threads_created += watched_result.watched_threads_created
        result.watched_thread_new_messages += watched_result.new_messages_detected
        result.watched_thread_processed_messages += watched_result.processed_messages
        result.watched_thread_positive_responses += watched_result.positive_responses
        result.watched_thread_refused_responses += watched_result.refused_responses
        result.watched_thread_actionable_refused_threads += watched_result.actionable_refused_threads
        result.watched_thread_evidence_requests += watched_result.evidence_requests
        result.watched_thread_manual_reviews += watched_result.manual_reviews
        result.autopilot_sent_count += watched_result.autopilot_sent_count
        result.autopilot_skipped_count += watched_result.autopilot_skipped_count
        result.autopilot_failed_count += watched_result.autopilot_failed_count
        result.errors.extend(watched_result.errors)

    def watched_result_ran_autopilot(self, watched_result: GmailWatchedThreadMonitorResult | None) -> bool:
        if watched_result is None:
            return False
        return (
            watched_result.autopilot_sent_count > 0
            or watched_result.autopilot_skipped_count > 0
            or watched_result.autopilot_failed_count > 0
        )

    def watched_result_needs_autopilot(self, watched_result: GmailWatchedThreadMonitorResult | None) -> bool:
        if watched_result is None:
            return False
        return watched_result.refused_responses > 0 or watched_result.actionable_refused_threads > 0

    def run_workspace_machine(self, db: Session, user: User, result: GmailInboundAutoSyncResult) -> None:
        from app.schemas.domain import WorkspaceMachineRunRequest
        from app.services.workspace_machine_service import WorkspaceMachineService

        try:
            machine_result = WorkspaceMachineService(db, user, self.provider).run(
                WorkspaceMachineRunRequest(
                    trigger="manual",
                    sync_gmail=False,
                    run_autopilot=self.settings.gmail_inbound_auto_sync_run_autopilot,
                    run_historical_cleanup=False,
                )
            )
        except Exception as exc:  # noqa: BLE001 - background recovery must not stop Gmail sync cycles.
            logger.exception("Workspace machine auto-run failed for user %s", user.id)
            result.workspace_machine_failures += 1
            result.errors.append(f"workspace_machine:user:{user.id}:{exc}")
            return
        result.workspace_machine_runs += 1
        autopilot_stage = next((stage for stage in machine_result.stages if stage.name == "autopilot"), None)
        if autopilot_stage is not None:
            result.autopilot_sent_count += autopilot_stage.sent_count
            result.autopilot_skipped_count += autopilot_stage.skipped_count
            result.autopilot_failed_count += autopilot_stage.failed_count
        if machine_result.status == "warning":
            result.workspace_machine_warnings += 1
        elif machine_result.status == "failed":
            result.workspace_machine_failures += 1

    def mark_sync_failure(
        self,
        db: Session,
        sync_service: GmailInboundSyncService,
        account_id: int,
        user_id: int,
        error_message: str,
    ) -> None:
        account = db.get(EmailAccount, account_id)
        if account is None:
            return
        sync_state = sync_service.get_or_create_sync_state(db, account)
        sync_state.status = "failed"
        sync_state.last_error = error_message[:2000]
        add_audit_log(
            db,
            entity_type="gmail_sync_state",
            entity_id=sync_state.id,
            action="gmail_inbound_sync.failed",
            user_id=user_id,
            new_value={"error": error_message[:2000]},
        )
        db.flush()

    def mark_sync_success(
        self,
        db: Session,
        sync_service: GmailInboundSyncService,
        account_id: int,
        user_id: int,
        watched_result: GmailWatchedThreadMonitorResult,
    ) -> None:
        account = db.get(EmailAccount, account_id)
        if account is None:
            return
        sync_state = sync_service.get_or_create_sync_state(db, account)
        now = utc_now()
        sync_state.status = "success"
        sync_state.last_sync_at = now
        sync_state.last_success_at = now
        sync_state.last_error = None
        add_audit_log(
            db,
            entity_type="gmail_sync_state",
            entity_id=sync_state.id,
            action="gmail_watched_threads_sync.success",
            user_id=user_id,
            new_value={
                "watched_threads_seen": watched_result.watched_threads_seen,
                "new_messages_detected": watched_result.new_messages_detected,
                "processed_messages": watched_result.processed_messages,
                "positive_responses": watched_result.positive_responses,
                "refused_responses": watched_result.refused_responses,
                "actionable_refused_threads": watched_result.actionable_refused_threads,
                "autopilot_sent_count": watched_result.autopilot_sent_count,
                "autopilot_skipped_count": watched_result.autopilot_skipped_count,
                "autopilot_failed_count": watched_result.autopilot_failed_count,
            },
        )
        db.flush()


class GmailInboundAutoSyncScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] = SessionLocal,
        service_factory: Callable[[], GmailInboundAutoSyncService] = GmailInboundAutoSyncService,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.service_factory = service_factory
        self.settings = settings or get_settings()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if not (
            self.settings.email_provider_enabled
            and self.settings.gmail_inbound_sync_enabled
            and self.settings.gmail_inbound_auto_sync_enabled
        ):
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        initial_delay = max(0, self.settings.gmail_inbound_auto_sync_initial_delay_seconds)
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Gmail auto-sync loop iteration failed")
            await asyncio.sleep(self.effective_sleep_seconds())

    def effective_sleep_seconds(self) -> int:
        if self.settings.gmail_inbound_auto_sync_continuous_enabled:
            return max(MIN_CONTINUOUS_IDLE_SLEEP_SECONDS, self.settings.gmail_inbound_auto_sync_idle_sleep_seconds)
        return max(MIN_AUTO_SYNC_INTERVAL_SECONDS, self.settings.gmail_inbound_auto_sync_interval_seconds)

    async def run_once(self) -> GmailInboundAutoSyncResult | None:
        if self._running:
            return None
        self._running = True
        try:
            return await asyncio.to_thread(self._run_once_sync)
        finally:
            self._running = False

    def _run_once_sync(self) -> GmailInboundAutoSyncResult:
        db = self.session_factory()
        try:
            result = self.service_factory().sync_due_accounts(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            logger.exception("Gmail auto-sync cycle failed")
            raise
        finally:
            db.close()


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
