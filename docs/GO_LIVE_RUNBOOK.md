# TENNET go-live runbook V1

This runbook prepares a controlled commercial launch of TENNET V1.

Core rule: no email, reply or follow-up is sent automatically. Gmail sends require an explicit manual confirmation in the application.

## Phase 1 - Preparation

1. Confirm the production host is ready for Docker and Docker Compose.
2. Configure DNS for the frontend and API domains.
3. Verify `app.thetennet.com` and `api.thetennet.com` in `deploy/Caddyfile`.
4. Copy `.env.production.example` to `.env.production` on the host.
5. Replace every placeholder secret in `.env.production`.
6. Confirm `SECRET_KEY` is long, random and unique to production.
7. Confirm `DATABASE_URL` points to PostgreSQL.
8. Confirm persistent volumes are available for PostgreSQL, evidence files, import files and Caddy.
9. Configure Gmail OAuth in Google Cloud if Gmail is enabled.
10. Confirm backups and restore procedures have been tested before launch.

## Phase 2 - Deployment

```bash
git pull origin main
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

Then verify:

```bash
curl -fsS https://api.thetennet.com/health
curl -fsS https://api.thetennet.com/ready
curl -fsS https://api.thetennet.com/version
curl -fsS https://app.thetennet.com/health
```

Create the first owner at `/setup-owner`, then create restaurants, managers and staff users.

## Phase 3 - Real Test

1. Create a test restaurant and a test order.
2. Upload a test `cancellation_proof`.
3. Upload a test `preparation_proof` or `waste_photo`.
4. Validate the order and confirm it becomes `ready_to_send`.
5. Generate an internal draft.
6. Connect a dedicated Gmail sandbox account.
7. Create a Gmail draft.
8. Send one manual test email to a controlled address only.
9. Sync inbound replies.
10. Export one CSV and one XLSX report.

## Phase 4 - Launch

1. Inform the team that V1 is live.
2. Create staff accounts and assign restaurants.
3. Train users with `docs/USER_GUIDE.md`.
4. Import the first operational files.
5. Check `/dashboard`, `/followups` and `/reports`.
6. Confirm no automatic email or follow-up path is enabled.

## Phase 5 - Monitoring

Daily checks:

- backend `/health`, `/ready` and `/version`;
- Docker logs for backend, frontend, PostgreSQL and Caddy;
- disk usage for PostgreSQL, evidence and import volumes;
- backup completion;
- Gmail OAuth errors if enabled;
- upload errors;
- export errors;
- due follow-ups and manual reviews.

## Phase 6 - Rollback

1. Stop the production stack.
2. Restore the previous application image or git revision.
3. Restore PostgreSQL only if the migration/data state requires it.
4. Restore evidence/import files if file data was changed or lost.
5. Disable Gmail if email operations are impacted:

```bash
EMAIL_PROVIDER_ENABLED=false
GMAIL_INBOUND_SYNC_ENABLED=false
```

6. Restart services and verify `/health`, `/ready`, `/version`.
7. Communicate the rollback status internally.

## V1.1 RC staging note

Before any V1.1 production rollout, run the staging release candidate flow:

1. Deploy `1.1.1-tennet` with `docker-compose.staging.yml` or keep the previously accepted RC2 staging environment as evidence.
2. Use only fictitious examples from `docs/examples/v1_1` first.
3. Run `scripts/smoke_test_v1_1.sh`.
4. Execute `docs/V1_1_ACCEPTANCE_TEST_PLAN.md`.
5. Validate with real-format Uber exports in staging.
6. Confirm no automatic email, follow-up or appeal send occurred.
7. Document open risks in `docs/KNOWN_LIMITATIONS_V1_1.md`.

Production `v1.0.3-tennet` should remain untouched until V1.1 acceptance is complete and the final tag is selected for rollout.

