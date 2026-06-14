# TENNET admin guide V1

This guide is for owners and operators managing production.

## Official domains

Use `https://app.thetennet.com` for production and `https://staging-app.thetennet.com` for staging.

Resend uses the verified domain `mail.thetennet.com` and remains disabled by default. Its API key must exist only in the host environment. Gmail remains the separate provider for Uber conversation threads when intentionally configured.

## Roles

`owner`:

- full access;
- users and restaurants management;
- all claim, Gmail, follow-up and reporting actions.

`manager`:

- assigned restaurants only;
- claim management;
- evidence upload;
- validation, drafts, manual Gmail send, inbound review and follow-ups for assigned restaurants;
- reporting and recovery cockpit for assigned restaurants.

`staff`:

- assigned restaurants only;
- order creation;
- evidence upload;
- read access where allowed;
- no user management, restaurant creation, Gmail send, response review, follow-up management, recovery exports or commercial exports.

## User and restaurant administration

1. Create the first owner from `/setup-owner`.
2. Create restaurants from `/restaurants/new`.
3. Add more restaurants at any time. There is no fixed restaurant limit.
4. Create users from `/users/new`.
5. Assign restaurants from the user detail page.
6. Deactivate restaurants instead of deleting operational history.

## Gmail OAuth

1. Create a Google Cloud OAuth client.
2. Register the production redirect URI:
   `https://api.thetennet.com/v1/email/gmail/oauth/callback`.
3. Configure scopes needed for compose, send and readonly.
4. Set `EMAIL_PROVIDER_ENABLED=true` only after OAuth is ready.
5. Connect Gmail from `/settings/email`.
6. If restaurants use different Uber/Gmail accounts, connect each Gmail account from `/settings/email`, then map each restaurant to the correct Gmail account in `Gmail par restaurant`.

TENNET stores OAuth tokens encrypted and never stores Gmail passwords. Mapping a restaurant to a Gmail account does not enable automatic sending. It only chooses the correct mailbox when an authorized user creates or sends a Gmail draft.

Emergency disable:

```bash
EMAIL_PROVIDER_ENABLED=false
GMAIL_INBOUND_SYNC_ENABLED=false
```

Restart the backend after changing production environment variables.

## Production configuration

Use `.env.production` on the host only. Never commit it.

Mandatory checks:

- `SECRET_KEY` is not a placeholder;
- `DATABASE_URL` uses PostgreSQL;
- `BACKEND_CORS_ORIGINS` is not wildcard;
- `DEBUG=false`;
- persistent volumes are mounted;
- HTTPS is active.

## Backups and restore

Use:

- `scripts/backup_postgres.sh`;
- `scripts/restore_postgres.sh`;
- `scripts/backup_evidence_files.sh`.

Recommended frequency:

- PostgreSQL daily;
- evidence/import files daily;
- retention at least 30 days;
- restore test monthly or before launch.

## Logs and restart

Read logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f
```

Restart one service:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart backend
```

## Disk monitoring

Check host disk:

```bash
df -h
```

Check evidence volume:

```bash
docker run --rm -v ubereats_claims_manager_evidence_data:/data:ro alpine:3.20 du -sh /data
```

Evidence and import files are local in V1. Plan enough disk and backups.

## Evidence request links

Owners and managers can create mobile upload links from `/evidence-tasks/{id}`.

Assigned staff can create a printable evidence ticket from `/evidence-tasks/{id}`. The ticket creates a one-use mobile upload link and QR code for the exact task, but it does not grant broader access, skip a task, complete a task manually, send an email or create a claim.

`/live-evidence` is the recommended web field station for restaurants. It shows only active evidence tasks visible to the user, recommends the next proof and starts ticket printing. Browser printing can use any printer already available to the device.

The Android native app now includes the `android_bluetooth_escpos` bridge for paired SUNMI/Bluetooth receipt printers. Staff users see a simplified field station screen and the primary action `Imprimer et prendre photo`. The printer bridge only prints TENNET evidence tickets; it must never read or automate an Uber Eats tablet.

Operational settings:

- `EVIDENCE_TASK_HIGH_AMOUNT` sets the high priority threshold;
- `EVIDENCE_TASK_URGENT_AMOUNT` sets the urgent priority threshold;
- `EVIDENCE_UPLOAD_LINK_EXPIRY_HOURS` controls link expiration;
- `EVIDENCE_UPLOAD_LINK_MAX_USES` controls allowed uploads per link.

Recommended production defaults:

- short enough expiration for operational control;
- one use per link;
- revoke links manually if sent to the wrong recipient;
- never paste a mobile upload token into support tickets or logs.

## Bulk evidence and analysis administration

Owners and managers can use `/evidence-imports` to process existing proof files.

Operational settings:

- `BULK_EVIDENCE_MAX_FILES_PER_BATCH` limits files per batch;
- `BULK_EVIDENCE_MAX_ZIP_SIZE_MB` limits ZIP uploads;
- `BULK_EVIDENCE_MAX_FILE_SIZE_MB` limits each imported file;
- `BULK_EVIDENCE_ALLOWED_EXTENSIONS` lists accepted extensions;
- `AI_EVIDENCE_ANALYSIS_ENABLED=false` disables external AI analysis by default;
- `AI_EVIDENCE_AUTO_ATTACH_ENABLED=false` keeps attachment decisions manual;
- `AI_EVIDENCE_HIGH_CONFIDENCE_THRESHOLD` and `AI_EVIDENCE_MEDIUM_CONFIDENCE_THRESHOLD` control review thresholds;
- `OCR_LOCAL_ENABLED` controls local OCR availability.

OpenAI credentials are optional and must remain in environment variables only. CI and default production must not call the real OpenAI API.

## Appeal workflow administration

Owners and managers can use `/appeals` to manage refusals.

Operational settings:

- `APPEAL_AUTO_SEND_ENABLED=false` keeps automatic sending disabled;
- `APPEAL_MIN_DAYS_BETWEEN_ATTEMPTS` controls cooldown;
- `APPEAL_MAX_ATTEMPTS_BEFORE_ESCALATION` controls escalation;
- `APPEAL_MAX_ATTEMPTS_BEFORE_MANUAL_REVIEW` stops repeated attempts;
- `APPEAL_REQUIRE_NEW_ARGUMENT_AFTER_REFUSAL` documents the need for a new argument;
- `APPEAL_ALLOW_SAME_TEMPLATE_RESEND` prevents duplicate drafts when false.

Recommended operating policy:

- review appeal queue daily;
- collect missing evidence before creating appeal drafts;
- do not mark an appeal sent unless the manual send happened;
- manually close only when the owner decides the case should stop;
- keep refusal reasons and notes factual.

## Recovery cockpit administration

Owners and managers can use `/recovery`, `/recovery/cases` and `/recovery/actions`.

Rules:

- owner sees all restaurants;
- manager sees assigned restaurants only;
- staff does not export financial recovery data;
- recovery exports must be treated like financial reports;
- customer refund decisions are manual and audited;
- TENNET does not guarantee reimbursement or automate disputes.

Operational review cadence:

- review `/recovery/actions` daily;
- review high-value missing evidence first;
- review active appeals and escalations daily;
- confirm recovered amounts only after payment evidence or accounting confirmation;
- document refusals and manual review notes.

## AutoPilot administration

Owners and managers can use `/autopilot` to preview and run controlled Gmail sending. Staff cannot run AutoPilot.

Activation sequence:

1. Configure Gmail and verify the account is connected.
2. Set `AUTOPILOT_ENABLED=true`.
3. Enable only the required mode flags: initial claims, follow-ups or appeals.
4. Enable AutoPilot per restaurant from `/restaurants`.
5. Run a dry-run and review every skipped reason.
6. Run the selected mode only after validation.

Operational settings:

- `AUTOPILOT_DAILY_SEND_LIMIT` caps global daily sends;
- `AUTOPILOT_PER_RESTAURANT_DAILY_LIMIT` caps sends by restaurant;
- `AUTOPILOT_MIN_AMOUNT` and `AUTOPILOT_MAX_AMOUNT_WITHOUT_OWNER_REVIEW` protect low and high value cases;
- `AUTOPILOT_REQUIRE_COMPLETE_EVIDENCE=true` blocks incomplete dossiers;
- `AUTOPILOT_REQUIRE_GMAIL_CONNECTED=true` blocks sending without Gmail;
- `AUTOPILOT_COOLDOWN_HOURS` limits repeated sends;
- `AUTOPILOT_MAX_APPEAL_ATTEMPTS` blocks infinite appeals;
- `AUTOPILOT_NEVER_CLOSE_ON_REFUSAL=true` keeps refusals open for review.

Emergency policy:

- use `POST /v1/autopilot/stop` or the UI emergency stop button if sending must stop immediately;
- investigate `AutopilotRun`, `AutopilotAction` and `AuditLog` before re-enabling;
- do not raise limits during an incident;
- TENNET does not guarantee reimbursement and must not be presented as doing so.

## Data retention

V1 does not include an automated retention workflow. Recommended operating policy:

- keep claim data only as long as operationally needed;
- document any manual deletion request;
- keep backups encrypted and access-limited;
- review old evidence files regularly.

## V1.1 staging administration

Use `docker-compose.staging.yml` and `.env.staging.example` for the V1.1 release candidate.

Rules:

- do not reuse production volumes;
- do not copy production secrets into staging;
- keep `EMAIL_PROVIDER_ENABLED=false` unless Gmail staging is intentionally tested;
- keep `AI_EVIDENCE_ANALYSIS_ENABLED=false` by default;
- keep `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false`;
- keep `APPEAL_AUTO_SEND_ENABLED=false`;
- run `scripts/smoke_test_v1_1.sh` before acceptance;
- validate with `docs/V1_1_ACCEPTANCE_TEST_PLAN.md`.

## Premium UX administration

Use `/smart-import` when an operator has a report, screenshot, PDF or ZIP but does not know the format. TENNET detects the content and routes the file without requiring a renamed file. Safe Uber reporting rows are applied automatically; blocked rows remain visible for review. Evidence batches are stored and analyzed with the local/fake provider by default.

Staff mobile usage should stay focused on proof tasks. Staff must not receive financial cockpit, Gmail, appeal or AutoPilot permissions.

See `docs/SMART_IMPORT.md`, `docs/MOBILE_USAGE.md` and `docs/DESIGN_SYSTEM.md`.

## Native mobile administration

The native mobile app lives in `mobile/tennet-native` and uses the official TENNET API by default. For staging tests, set `EXPO_PUBLIC_API_BASE_URL` and `EXPO_PUBLIC_WEB_APP_URL` before running Expo.

Android production builds include `mobile/tennet-native/plugins/withTennetNativePrinter.js`, which adds Bluetooth permissions and registers the native receipt-printer module during prebuild/EAS. Test the app on a physical Android device with the receipt printer already paired in Android settings.

Publishing to Google Play requires owner-controlled Play Console access, app signing and privacy declarations. Never commit keystores, service account JSON files, Play credentials or 2FA codes.

