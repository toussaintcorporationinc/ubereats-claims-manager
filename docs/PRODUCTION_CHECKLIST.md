# Production checklist

Use this checklist before launching a TENNET commercial production instance.

## Infrastructure

- [ ] Official frontend domain `app.thetennet.com` configured.
- [ ] Official API domain `api.thetennet.com` configured.
- [ ] Temporary fallback domains `app.leboxerfrancais.com` and `api.leboxerfrancais.com` still available during migration.
- [ ] DNS points to the production host.
- [ ] HTTPS active through Caddy.
- [ ] `deploy/Caddyfile` includes official and fallback domains, without `auto_https on`.
- [ ] `docker-compose.prod.yml` validated.
- [ ] Persistent PostgreSQL volume mounted.
- [ ] Persistent evidence volume mounted.
- [ ] Persistent import volume mounted.
- [ ] Host disk monitoring in place.

## Environment

- [ ] `.env.production` exists on the host and is not committed.
- [ ] `SECRET_KEY` changed from placeholder.
- [ ] `POSTGRES_PASSWORD` changed from placeholder.
- [ ] `DATABASE_URL` points to PostgreSQL, not SQLite.
- [ ] `BACKEND_CORS_ORIGINS` uses the real frontend URL, not `*`.
- [ ] `DEBUG=false`.
- [ ] `DOCS_ENABLED` reviewed.
- [ ] `RATE_LIMIT_ENABLED=true`.
- [ ] `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false`.
- [ ] `EMAIL_PROVIDER_ENABLED` reviewed.
- [ ] `GMAIL_INBOUND_SYNC_ENABLED` reviewed.
- [ ] `RESEND_ENABLED=false` unless Resend is intentionally enabled.
- [ ] `RESEND_API_KEY` exists only on the host, never in GitHub.
- [ ] `RESEND_DOMAIN=mail.thetennet.com` if Resend is used.

## Database and backups

- [ ] Migrations executed with `alembic upgrade head`.
- [ ] PostgreSQL backup tested.
- [ ] Evidence/import files backup tested.
- [ ] PostgreSQL restore tested.
- [ ] Evidence/import files restore tested.
- [ ] Backup retention policy set to at least 30 days.
- [ ] Backups stored outside the application host or replicated.
- [ ] Backup encryption plan reviewed.

## Application setup

- [ ] First owner created.
- [ ] Restaurants created.
- [ ] Managers and staff created.
- [ ] Restaurant access assigned.
- [ ] Import test OK.
- [ ] Upload proof test OK.
- [ ] Claim validation test OK.
- [ ] Internal draft test OK.
- [ ] Reporting/export test OK.
- [ ] Acceptance test plan executed.
- [ ] Go-live runbook reviewed by operator.
- [ ] Release notes reviewed by owner.

## Gmail

- [ ] Google OAuth application configured.
- [ ] Production redirect URI registered in Google Console.
- [ ] Gmail scopes reviewed.
- [ ] Gmail connection test OK.
- [ ] Gmail draft creation test OK.
- [ ] Manual Gmail send test OK if enabled.
- [ ] Inbound sync test OK if enabled.
- [ ] Emergency Gmail disable procedure known.

## Resend

- [ ] Domain `mail.thetennet.com` verified in Resend.
- [ ] Resend DNS records documented outside secrets.
- [ ] Resend stays disabled by default.
- [ ] Resend is used only for transactional/manual sends when explicitly enabled.

## Operations

- [ ] Backend `/health` OK.
- [ ] Backend `/ready` OK.
- [ ] Backend `/version` OK and contains no secret.
- [ ] Frontend `/health` OK.
- [ ] `scripts/smoke_test.sh` OK.
- [ ] Docker logs reviewed.
- [ ] CI green.
- [ ] Security scans clean.
- [ ] No real client data in repository.
- [ ] No hardcoded restaurant limit.

## V1.1 RC pre-production checklist

- [ ] Staging acceptance completed with RC2, final `1.1.0-tennet`, or patch `1.1.1-tennet`.
- [ ] `.env.staging` uses staging-only secrets.
- [ ] `EMAIL_PROVIDER_ENABLED=false` unless Gmail staging test is explicit.
- [ ] `GMAIL_INBOUND_SYNC_ENABLED=false` unless Gmail staging test is explicit.
- [ ] `AI_EVIDENCE_ANALYSIS_ENABLED=false`.
- [ ] `AI_EVIDENCE_AUTO_ATTACH_ENABLED=false`.
- [ ] `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false`.
- [ ] `APPEAL_AUTO_SEND_ENABLED=false`.
- [ ] `scripts/smoke_test_v1_1.sh` passed.
- [ ] V1.1 acceptance plan completed.
- [ ] Real-format Uber exports validated in staging.
- [ ] No reimbursement guarantee appears in UI/docs.
- [ ] No automatic email, follow-up or appeal send occurred.
- [ ] Owner-only manual closure verified.
