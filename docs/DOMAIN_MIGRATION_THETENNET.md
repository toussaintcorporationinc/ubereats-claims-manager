# Domain Migration - thetennet.com

`thetennet.com` is the official TENNET domain.

## Official URLs

Production:

- `https://app.thetennet.com`
- `https://api.thetennet.com`

Staging:

- `https://staging-app.thetennet.com`
- `https://staging-api.thetennet.com`

## Canonical domain only

TENNET uses `thetennet.com` as its only official public domain. New configuration, documentation, app listings and mobile builds must not show legacy brand domains.

## Repository defaults

- `deploy/Caddyfile` contains official production and staging routes for `thetennet.com`.
- `.env.production.example` uses `app.thetennet.com` and `api.thetennet.com`.
- `.env.staging.example` uses `staging-app.thetennet.com` and `staging-api.thetennet.com`.
- `BACKEND_CORS_ORIGINS` contains only the official frontend domain for the target environment.

## Validation

Production:

```bash
curl -fsS https://api.thetennet.com/health
curl -fsS https://api.thetennet.com/ready
curl -fsS https://api.thetennet.com/version
curl -I https://app.thetennet.com
```

Staging:

```bash
curl -fsS https://staging-api.thetennet.com/health
curl -fsS https://staging-api.thetennet.com/ready
curl -fsS https://staging-api.thetennet.com/version
curl -I https://staging-app.thetennet.com
```

## Safety rules

- Do not commit `.env.production` or `.env.staging`.
- Do not modify Gmail OAuth secrets as part of domain migration.
- Do not enable OpenAI, automatic followups, automatic appeals or AutoPilot by default.
- Do not add `auto_https on` to the Caddyfile; Caddy manages HTTPS automatically.
