#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

curl -fsS "${API_URL}/health" >/dev/null
echo "Backend /health ok"

curl -fsS "${API_URL}/ready" >/dev/null
echo "Backend /ready ok"

curl -fsS "${API_URL}/version" >/dev/null
echo "Backend /version ok"

curl -fsS "${FRONTEND_URL}/health" >/dev/null
echo "Frontend /health ok"
