#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ubereats_claims_manager}"
EVIDENCE_VOLUME="${EVIDENCE_VOLUME:-${PROJECT_NAME}_evidence_data}"
IMPORT_VOLUME="${IMPORT_VOLUME:-${PROJECT_NAME}_import_data}"
BACKUP_DIR="${BACKUP_DIR:-backups/files}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUTPUT_NAME="evidence_imports_${TIMESTAMP}.tar.gz"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

docker run --rm \
  -v "${EVIDENCE_VOLUME}:/data/evidence:ro" \
  -v "${IMPORT_VOLUME}:/data/imports:ro" \
  -v "$(pwd)/${BACKUP_DIR}:/backup" \
  alpine:3.20 \
  tar -czf "/backup/${OUTPUT_NAME}" -C /data evidence imports

test -s "${BACKUP_DIR}/${OUTPUT_NAME}"
echo "Evidence/import files backup written to ${BACKUP_DIR}/${OUTPUT_NAME}"
