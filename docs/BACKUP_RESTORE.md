# Backup and restore

Backups are mandatory before commercial production use.

## Recommended schedule

- PostgreSQL: daily backup.
- Evidence/import files: daily backup.
- Retention: at least 30 days.
- Restore test: at least monthly and before major releases.

Store backups outside the application host when possible. Encrypt backups before transferring to external storage.

## PostgreSQL backup

Run from the repository root on the production host:

```bash
./scripts/backup_postgres.sh
```

Optional variables:

```bash
ENV_FILE=.env.production
COMPOSE_FILE=docker-compose.prod.yml
BACKUP_DIR=backups/postgres
```

The script creates a compressed SQL dump:

```text
backups/postgres/postgres_YYYYMMDDTHHMMSSZ.sql.gz
```

The dump uses `--clean --if-exists` so restore can replace existing database objects.

## Evidence and import files backup

Run:

```bash
./scripts/backup_evidence_files.sh
```

The script archives Docker volumes:

- `ubereats_claims_manager_evidence_data`
- `ubereats_claims_manager_import_data`

Output:

```text
backups/files/evidence_imports_YYYYMMDDTHHMMSSZ.tar.gz
```

Override volume names if the Compose project name changes:

```bash
COMPOSE_PROJECT_NAME=custom_name ./scripts/backup_evidence_files.sh
```

## PostgreSQL restore

Restoration is destructive. Use a maintenance window.

1. Stop traffic if needed.
2. Verify the dump file exists.
3. Run:

```bash
./scripts/restore_postgres.sh backups/postgres/postgres_YYYYMMDDTHHMMSSZ.sql.gz
```

4. Type `RESTORE` when prompted.
5. Run migrations:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

6. Run health checks:

```bash
API_URL=https://api.thetennet.com FRONTEND_URL=https://app.thetennet.com ./scripts/healthcheck.sh
```

## Files restore

To restore evidence/import files, extract the archive into the Docker volumes using a temporary container. Example:

```bash
docker run --rm \
  -v ubereats_claims_manager_evidence_data:/data/evidence \
  -v ubereats_claims_manager_import_data:/data/imports \
  -v "$(pwd)/backups/files:/backup:ro" \
  alpine:3.20 \
  tar -xzf /backup/evidence_imports_YYYYMMDDTHHMMSSZ.tar.gz -C /data
```

Then restart the backend:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart backend
```

## Incident procedure

1. Stop writes if the incident is ongoing.
2. Take an immediate backup, even if suspected partial.
3. Identify the latest known-good PostgreSQL and file backups.
4. Restore in a staging environment first when possible.
5. Validate `/ready`, uploads, downloads, imports and reports.
6. Restore production only after validation.
7. Document incident time, affected orders and operator actions.
