# Rollback plan V1

Use this plan if a production deployment causes a critical issue.

## Application rollback

1. Identify the last known good git commit or image.
2. Stop the current stack:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

3. Checkout or deploy the previous version.
4. Start the stack:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

5. Verify `/health`, `/ready`, `/version` and login.

## Migration rollback

If the failed release applied database migrations:

1. Review the Alembic revision history.
2. Confirm whether data loss risk exists.
3. Prefer restoring a verified backup if the migration changed production data.
4. If safe, run the Alembic downgrade documented for the affected revision.

Never downgrade blindly on production.

## Database restore

1. Stop write traffic.
2. Keep a copy of the current failed state for investigation.
3. Restore the selected PostgreSQL dump with `scripts/restore_postgres.sh`.
4. Run `/ready`.
5. Verify key orders, users and reports.

## Evidence/import files restore

1. Stop backend writes.
2. Restore the evidence/import archive to the persistent volume.
3. Verify a sample evidence download.
4. Restart backend.

## Disable risky subsystems

Disable Gmail:

```bash
EMAIL_PROVIDER_ENABLED=false
GMAIL_INBOUND_SYNC_ENABLED=false
```

Disable follow-up automation flag:

```bash
FOLLOWUP_AUTOMATIC_SEND_ENABLED=false
```

V1 does not implement automatic sends, but the flag should remain false.

## Post-rollback verification

- `/health` OK.
- `/ready` OK.
- `/version` shows expected version.
- Owner can login.
- Evidence download works.
- Reports load.
- No Gmail send is attempted automatically.

## Communication

Tell the internal team:

- what changed;
- current service status;
- whether any manual Gmail actions should pause;
- when the next update is expected.

