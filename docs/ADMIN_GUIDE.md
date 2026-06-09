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
- confirm recovered amounts only after payment evidence or accounting confirmation;
- document refusals and manual review notes.

## Data retention

V1 does not include an automated retention workflow. Recommended operating policy:

- keep claim data only as long as operationally needed;
- document any manual deletion request;
- keep backups encrypted and access-limited;
- review old evidence files regularly.

