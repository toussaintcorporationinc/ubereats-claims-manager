# Gmail Response Intelligence

TENNET can analyze Gmail replies from Uber support accounts and turn clear responses into tracked internal decisions.

## Goal

The engine reduces manual triage after Gmail sync:

- link Uber replies to existing TENNET claim orders;
- classify clear positive and negative replies;
- record a `ClaimResponseReview`;
- update recovery reporting through the existing order statuses;
- keep refusals alive through the persistent appeal workflow;
- optionally trigger AutoPilot appeals when a clear refusal is detected and every AutoPilot safety rule is enabled.

The analysis engine itself does not send email. When `AUTOPILOT_ENABLED=true`, `AUTOPILOT_APPEALS_ENABLED=true`, Gmail is connected, and the restaurant has `autopilot_enabled=true`, a newly detected refusal can trigger an AutoPilot appeal run.

## Zero-Click Sync

TENNET can run Gmail sync periodically on the backend when these flags are enabled:

- `GMAIL_INBOUND_AUTO_SYNC_ENABLED=true`
- `GMAIL_INBOUND_AUTO_SYNC_CONTINUOUS_ENABLED=true`
- `GMAIL_INBOUND_AUTO_SYNC_INTERVAL_SECONDS=30` when continuous mode is disabled
- `GMAIL_STARRED_MAX_MESSAGES_PER_SYNC=50000`
- `GMAIL_STARRED_FULL_HISTORY_ENABLED=true`
- `GMAIL_STARRED_PAGE_SIZE=500`
- `GMAIL_STARRED_MAX_PAGES_PER_SYNC=0`
- `GMAIL_INBOUND_AUTO_SYNC_IDLE_SLEEP_SECONDS=1`
- `GMAIL_INBOUND_AUTO_SYNC_INITIAL_DELAY_SECONDS=5`
- `GMAIL_INBOUND_AUTO_SYNC_EXISTING_REPROCESS_LIMIT=1000`
- `GMAIL_INBOUND_AUTO_SYNC_RUN_AUTOPILOT=true`
- `GMAIL_INBOUND_AUTO_SYNC_RUN_WORKSPACE_MACHINE=true`
- `GMAIL_DAILY_PROCESSING_TARGET=2000`
- `GMAIL_QUOTA_RETRY_SAFETY_SECONDS=30`
- `GMAIL_WATCHED_THREADS_ENABLED=true`
- `GMAIL_WATCHED_THREADS_POLL_SECONDS=30`
- `GMAIL_WATCHED_THREADS_FULL_RESCAN_MINUTES=15`
- `GMAIL_WATCHED_THREADS_MAX_PER_CYCLE=5000`
- `GMAIL_WATCHED_THREADS_BATCH_PER_CYCLE=100`
- `GMAIL_WATCHED_THREADS_PROCESS_NEW_MESSAGES=true`

Regle operationnelle : un fil Gmail etoile represente une relance urgente a traiter. TENNET analyse le message, detecte refus, paiement ou demande de preuve, puis laisse AutoPilot repondre uniquement si le dossier a une identite complete et une signature restaurant complete. Aucun email automatique ne doit contenir la marque interne TENNET.

The scheduler is disabled by default. When enabled with continuous mode, it chains Gmail cycles in the background instead of waiting for a long polling interval. It checks connected Gmail accounts, drains starred Gmail threads page by page, analyzes linked replies, applies high-confidence reviews, and can trigger AutoPilot appeals for clear refusals.

## Decisions

TENNET can recommend or apply these outcomes:

- `accepted`: Uber appears to accept the claim.
- `payment_to_verify`: Uber announces a payment or payout that still needs verification.
- `payment_confirmed`: Uber confirms payment and a monetary amount is detected in the email.
- `refused`: Uber refuses or denies compensation.
- `evidence_requested`: Uber asks for proof, screenshots, receipts, photos, or supporting evidence.
- `information_requested`: Uber asks for more information.
- `followup_needed`: Uber says the case is under review or still being investigated.
- `manual_review`: TENNET is not confident enough to decide.

If signals conflict, TENNET keeps the email in manual review.

Gmail starred messages are a business override: when an Uber email is marked `STARRED`, TENNET treats it as an urgent refused case to follow up, unless the same email contains a clear positive acceptance or payment signal. This keeps owner-marked refusals in the appeal/relance workflow while avoiding duplicate relances after a real payment confirmation.

## Amount Rules

TENNET never invents a recovered amount.

`payment_confirmed` is applied only when the email contains a strong payment confirmation signal and a detected amount such as `24,90 EUR` or `€24.90`.

If Uber mentions a payment without an amount, TENNET uses `payment_to_verify`.

## Refusals

A refusal never closes the claim automatically. When a `refused` review is created, TENNET opens or updates the existing appeal workflow so the case remains visible in the recovery cockpit.

If AutoPilot appeals are enabled, TENNET can create and send the next appeal automatically after Gmail sync. The appeal still uses the existing cooldown, max-attempt, daily-limit, per-restaurant-limit, no-duplicate-template, Gmail-connected, and safe-recipient checks.

## Gmail Scope

TENNET analyzes messages synchronized through connected Gmail accounts. Messages must be linked to a TENNET order before a decision can be applied.

Unlinked messages remain visible in the inbox and can be manually linked.

## Safety

- No email is sent unless AutoPilot is explicitly enabled globally and on the restaurant.
- No automatic irreversible close.
- No sending for unlinked messages, ignored senders, unrelated emails, invalid recipients, duplicate Gmail message ids, unresolved inbound replies, cooldown-active workflows, or final statuses.
- No fabricated amounts, order numbers, or proof.
- Ambiguous replies stay in manual review.
- Audit logs are created for analysis and applied reviews.
