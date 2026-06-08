#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"

request() {
  local label="$1"
  local url="$2"
  echo "Checking ${label}: ${url}"
  curl -fsS --max-time 15 "${url}" >/dev/null
}

if [[ "${ENVIRONMENT:-}" == "production" ]]; then
  if [[ -z "${SECRET_KEY:-}" || "${SECRET_KEY}" == "change-me-long-random-secret" ]]; then
    echo "ERROR: SECRET_KEY is missing or still uses the production placeholder." >&2
    exit 1
  fi

  if [[ -z "${DATABASE_URL:-}" || "${DATABASE_URL}" == sqlite* ]]; then
    echo "ERROR: DATABASE_URL must point to PostgreSQL in production." >&2
    exit 1
  fi

  if [[ "${BACKEND_CORS_ORIGINS:-}" == "*" ]]; then
    echo "ERROR: BACKEND_CORS_ORIGINS cannot be wildcard in production." >&2
    exit 1
  fi
fi

request "backend health" "${API_URL}/health"
request "backend readiness" "${API_URL}/ready"
request "backend version" "${API_URL}/version"
request "frontend health" "${FRONTEND_URL}/health"

echo "Smoke test OK"

