# Production deployment

This guide describes a Docker-based production deployment for TENNET.

## Target architecture

- Caddy terminates HTTPS for `app.thetennet.com` and `api.thetennet.com`.
- Frontend runs Next.js production server on the internal Docker network.
- Backend runs FastAPI/Uvicorn on the internal Docker network.
- PostgreSQL stores application data.
- Docker named volumes persist PostgreSQL, evidence files, import files and Caddy state.

No production secret should be committed to Git.

## Files

- `docker-compose.prod.yml`
- `.env.production.example`
- `deploy/Caddyfile`
- `scripts/backup_postgres.sh`
- `scripts/restore_postgres.sh`
- `scripts/backup_evidence_files.sh`
- `scripts/healthcheck.sh`
- `scripts/smoke_test.sh`

## First setup

1. Copy the production environment template.

```bash
cp .env.production.example .env.production
```

2. Edit `.env.production`.

Required changes:

- replace `SECRET_KEY` with a long random value;
- replace `POSTGRES_PASSWORD`;
- update `DATABASE_URL` with the same PostgreSQL password;
- keep `FRONTEND_URL=https://app.thetennet.com`, `API_BASE_URL=https://api.thetennet.com` and `NEXT_PUBLIC_API_BASE_URL=https://api.thetennet.com`;
- keep `BACKEND_CORS_ORIGINS=https://app.thetennet.com`;
- keep `RESEND_ENABLED=false` unless Resend is intentionally enabled with a server-only API key;
- configure Gmail OAuth only when ready.

3. Review `deploy/Caddyfile`.

It should include the official `thetennet.com` production routes. Do not add `auto_https on`; Caddy manages HTTPS automatically.

4. Start production services.

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

5. Apply migrations.

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

6. Verify readiness.

```bash
API_URL=https://api.thetennet.com FRONTEND_URL=https://app.thetennet.com ./scripts/healthcheck.sh
API_URL=https://api.thetennet.com FRONTEND_URL=https://app.thetennet.com ./scripts/smoke_test.sh
```

7. Create the first owner.

Open `https://app.thetennet.com/setup-owner` and create the first owner account.

## Production safeguards

In `ENVIRONMENT=production`, the backend refuses to start when:

- `SECRET_KEY` is missing or still a placeholder;
- `DATABASE_URL` uses SQLite;
- `BACKEND_CORS_ORIGINS` contains `*`;
- `DEBUG=true`.

## Deployment commands

Validate compose:

```bash
PRODUCTION_ENV_FILE=.env.production docker compose --env-file .env.production -f docker-compose.prod.yml config
```

Pull and rebuild:

```bash
git pull --ff-only
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

Restart one service:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart backend
```

Stop:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

Do not run `down -v` in production unless intentionally deleting persistent data.
