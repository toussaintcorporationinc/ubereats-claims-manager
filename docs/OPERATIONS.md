# Operations runbook

This runbook is for day-to-day production operation.

## Logs

All services:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f
```

Backend only:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f backend
```

Frontend only:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f frontend
```

Caddy only:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f caddy
```

## Health checks

Backend:

```bash
curl -fsS https://api.example.com/health
curl -fsS https://api.example.com/ready
curl -fsS https://api.example.com/version
```

Frontend:

```bash
curl -fsS https://app.example.com/health
```

Script:

```bash
API_URL=https://api.example.com FRONTEND_URL=https://app.example.com ./scripts/healthcheck.sh
```

Full smoke test:

```bash
API_URL=https://api.example.com FRONTEND_URL=https://app.example.com ./scripts/smoke_test.sh
```

## Database

Check PostgreSQL readiness:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Run migrations:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

## Disk and volumes

Host disk:

```bash
df -h
```

Docker volumes:

```bash
docker volume ls | grep ubereats_claims_manager
docker system df
```

Evidence volume size:

```bash
docker run --rm -v ubereats_claims_manager_evidence_data:/data:ro alpine:3.20 du -sh /data
```

Import volume size:

```bash
docker run --rm -v ubereats_claims_manager_import_data:/data:ro alpine:3.20 du -sh /data
```

## Service restarts

Backend:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart backend
```

Frontend:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart frontend
```

Caddy:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart caddy
```

## First owner

Open:

```text
https://app.example.com/setup-owner
```

The public setup endpoint closes after the first owner exists.

## Gmail operations

Connect Gmail:

1. Set `EMAIL_PROVIDER_ENABLED=true`.
2. Set Google OAuth client id, secret and redirect URI.
3. Ensure Google Console allows `https://api.example.com/v1/email/gmail/oauth/callback`.
4. Open `/settings/email` as owner or manager.

Emergency disable Gmail provider:

```bash
EMAIL_PROVIDER_ENABLED=false
docker compose --env-file .env.production -f docker-compose.prod.yml up -d backend
```

Emergency disable inbound sync:

```bash
GMAIL_INBOUND_SYNC_ENABLED=false
docker compose --env-file .env.production -f docker-compose.prod.yml up -d backend
```

Manual Gmail send remains guarded by explicit user confirmation. There is no automatic send path.

## Followups

Check due followups:

1. Open `/followups`.
2. Filter `pending` tasks.
3. Recalculate only as owner or manager.

Followups create tasks and drafts only. Sending remains manual.

## Reports and exports

Open `/reports` as owner or manager.

Use filters before large exports. `EXPORT_MAX_ROWS` limits export volume.

Customer names are excluded by default and should be included only when operationally necessary.
