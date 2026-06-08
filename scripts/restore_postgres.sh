#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
DUMP_FILE="${1:-}"

if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "Usage: $0 path/to/postgres_YYYYMMDDTHHMMSSZ.sql.gz" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

echo "This will restore PostgreSQL from: $DUMP_FILE"
echo "Existing database objects may be dropped by the dump."
read -r -p "Type RESTORE to continue: " CONFIRMATION

if [[ "$CONFIRMATION" != "RESTORE" ]]; then
  echo "Restore cancelled."
  exit 1
fi

gunzip -c "$DUMP_FILE" | docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres \
  sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

echo "PostgreSQL restore completed."
