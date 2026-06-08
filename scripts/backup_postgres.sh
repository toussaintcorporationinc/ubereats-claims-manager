#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_DIR="${BACKUP_DIR:-backups/postgres}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUTPUT="${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres \
  sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip -c > "$OUTPUT"

test -s "$OUTPUT"
echo "PostgreSQL backup written to $OUTPUT"
