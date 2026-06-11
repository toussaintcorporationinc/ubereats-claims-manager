# Domain Migration - thetennet.com

`thetennet.com` is the official TENNET domain.

## Official URLs

Production:

- `https://app.thetennet.com`
- `https://api.thetennet.com`

Staging:

- `https://staging-app.thetennet.com`
- `https://staging-api.thetennet.com`

## Temporary fallbacks

The previous `leboxerfrancais.com` URLs remain active during the migration window:

- `https://app.leboxerfrancais.com`
- `https://api.leboxerfrancais.com`
- `https://staging-app.leboxerfrancais.com`
- `https://staging-api.leboxerfrancais.com`

Do not remove fallback DNS, Caddy routes or CORS entries until production and staging have been validated on `thetennet.com`.

## Repository defaults

- `deploy/Caddyfile` contains official production and staging routes plus temporary fallback routes.
- `.env.production.example` uses `app.thetennet.com` and `api.thetennet.com`.
- `.env.staging.example` uses `staging-app.thetennet.com` and `staging-api.thetennet.com`.
- Fallback frontend domains stay in `BACKEND_CORS_ORIGINS` while migration is active.

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

Fallbacks:

```bash
curl -fsS https://api.leboxerfrancais.com/health
curl -I https://app.leboxerfrancais.com
curl -fsS https://staging-api.leboxerfrancais.com/health
curl -I https://staging-app.leboxerfrancais.com
```

## Safety rules

- Do not commit `.env.production` or `.env.staging`.
- Do not remove fallback domains until the operator approves.
- Do not modify Gmail OAuth secrets as part of domain migration.
- Do not enable OpenAI, automatic followups, automatic appeals or AutoPilot by default.
- Do not add `auto_https on` to the Caddyfile; Caddy manages HTTPS automatically.
