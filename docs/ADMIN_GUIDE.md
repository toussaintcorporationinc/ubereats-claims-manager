# TENNET admin guide V1

This guide is for owners and operators managing production.

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
   `https://api.example.com/v1/email/gmail/oauth/callback`.
3. Configure scopes needed for compose, send and readonly.
4. Set `EMAIL_PROVIDER_ENABLED=true` only after OAuth is ready.
5. Connect Gmail from `/settings/email`.

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

