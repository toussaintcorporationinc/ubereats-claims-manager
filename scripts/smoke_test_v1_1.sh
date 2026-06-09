#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
EXPECTED_VERSION="${EXPECTED_VERSION:-1.1.0-rc1-tennet}"

request_public() {
  local label="$1"
  local url="$2"
  echo "Checking ${label}: ${url}"
  curl -fsS --max-time 20 "${url}" >/dev/null
}

request_protected() {
  local label="$1"
  local path="$2"
  echo "Checking protected ${label}: ${path}"
  curl -fsS --max-time 20 -H "Authorization: Bearer ${TENNET_SMOKE_TOKEN}" "${API_URL}${path}" >/dev/null
}

request_public "backend health" "${API_URL}/health"
request_public "backend readiness" "${API_URL}/ready"
version_payload="$(curl -fsS --max-time 20 "${API_URL}/version")"
if ! printf '%s' "${version_payload}" | grep -q "${EXPECTED_VERSION}"; then
  echo "ERROR: /version does not contain ${EXPECTED_VERSION}" >&2
  exit 1
fi
request_public "frontend health" "${FRONTEND_URL}/health"

if [[ -z "${TENNET_SMOKE_EMAIL:-}" || -z "${TENNET_SMOKE_PASSWORD:-}" ]]; then
  echo "TENNET_SMOKE_EMAIL and TENNET_SMOKE_PASSWORD not set; skipping authenticated V1.1 endpoint smoke checks."
  echo "Smoke test V1.1 public checks OK"
  exit 0
fi

login_payload="$(
  python3 - <<'PY'
import json
import os

print(json.dumps({"email": os.environ["TENNET_SMOKE_EMAIL"], "password": os.environ["TENNET_SMOKE_PASSWORD"]}))
PY
)"

login_response="$(
  curl -fsS --max-time 20 \
    -H "Content-Type: application/json" \
    -d "${login_payload}" \
    "${API_URL}/v1/auth/login"
)"

TENNET_SMOKE_TOKEN="$(
  LOGIN_RESPONSE="${login_response}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["LOGIN_RESPONSE"])
print(payload["access_token"])
PY
)"
export TENNET_SMOKE_TOKEN

request_protected "Uber status" "/v1/uber/status"
request_protected "Recovery summary" "/v1/recovery/summary"
request_protected "Evidence imports" "/v1/evidence-imports"
request_protected "Appeals" "/v1/appeals"
request_protected "Customer refunds" "/v1/customer-refunds"

echo "Smoke test V1.1 OK"
