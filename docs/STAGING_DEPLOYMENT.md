# Staging Deployment V1.1

This guide prepares a TENNET V1.1 RC staging deployment. It must not replace production.

## Domains

Official staging domains:

- `https://staging-app.thetennet.com`
- `https://staging-api.thetennet.com`

## Files

- `docker-compose.staging.yml`
- `.env.staging.example`
- `deploy/Caddyfile.staging`
- `scripts/smoke_test_v1_1.sh`

## Setup

1. Copy the staging environment template.

```bash
cp .env.staging.example .env.staging
```

2. Edit `.env.staging` on the staging host.

Required manual changes:

- replace `SECRET_KEY`;
- replace `POSTGRES_PASSWORD`;
- update `DATABASE_URL` with the same password;
- keep `EMAIL_PROVIDER_ENABLED=false` unless Gmail staging is intentionally tested;
- keep `GMAIL_INBOUND_SYNC_ENABLED=false` unless Gmail staging is intentionally tested;
- keep `RESEND_ENABLED=false` unless Resend staging is intentionally tested with a server-only API key;
- keep `AI_EVIDENCE_ANALYSIS_ENABLED=false`;
- keep `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false`;
- keep `APPEAL_AUTO_SEND_ENABLED=false`.

Do not copy production secrets into staging.

3. Validate compose.

```bash
STAGING_ENV_FILE=.env.staging docker compose --env-file .env.staging -f docker-compose.staging.yml config
```

4. Start staging.

```bash
STAGING_ENV_FILE=.env.staging docker compose --env-file .env.staging -f docker-compose.staging.yml up -d --build
```

5. Apply migrations.

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml exec backend alembic upgrade head
```

6. Run smoke test.

```bash
API_URL=https://staging-api.thetennet.com \
FRONTEND_URL=https://staging-app.thetennet.com \
EXPECTED_VERSION=1.1.1-tennet \
./scripts/smoke_test_v1_1.sh
```

For authenticated smoke checks, set `TENNET_SMOKE_EMAIL` and `TENNET_SMOKE_PASSWORD` in the shell before running the script. The script does not print the token.

## Volumes

Staging compose uses separate volumes:

- `postgres_staging_data`
- `evidence_staging_data`
- `import_staging_data`
- `caddy_staging_data`
- `caddy_staging_config`

Do not reuse production volumes.
