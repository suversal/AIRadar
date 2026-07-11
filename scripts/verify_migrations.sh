#!/usr/bin/env bash
# Verify that Alembic alone can build the full schema: replay every migration
# onto an empty scratch pgvector database, then - if the reference Postgres
# container is running - diff the resulting schema against it line by line.
# Exits non-zero on any failure. Run after adding any migration.
#
#   scripts/verify_migrations.sh
#
# Env overrides: VERIFY_PG_PORT (default 55440), REF_CONTAINER (default
# infra-postgres-1), REF_DB_USER/REF_DB_NAME (default radar/radar).
set -euo pipefail

PORT="${VERIFY_PG_PORT:-55440}"
REF_CONTAINER="${REF_CONTAINER:-infra-postgres-1}"
REF_DB_USER="${REF_DB_USER:-radar}"
REF_DB_NAME="${REF_DB_NAME:-radar}"
NAME="hotai-verify-migrations-$$"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALEMBIC="$ROOT/.venv/bin/alembic"

cleanup() { docker stop "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# pg_dump output contains per-dump random \restrict tokens plus comments and
# session SETs - none of that is schema; strip it before diffing
normalize() { grep -vE '^--|^$|^SET |^SELECT pg_catalog|^\\(un)?restrict'; }

docker run -d --rm --name "$NAME" \
  -e POSTGRES_USER=radar -e POSTGRES_PASSWORD=radar -e POSTGRES_DB=radar \
  -p "$PORT:5432" pgvector/pgvector:pg16 >/dev/null

for _ in $(seq 1 30); do
  docker exec "$NAME" pg_isready -U radar -d radar >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" psql -U radar -d radar -q -c "CREATE EXTENSION IF NOT EXISTS vector;"

(
  cd "$ROOT/apps/api"
  DATABASE_URL="postgresql+psycopg://radar:radar@localhost:$PORT/radar" "$ALEMBIC" upgrade head
)
echo "OK: alembic upgrade head built the schema from an empty database"

if docker ps --format '{{.Names}}' | grep -qx "$REF_CONTAINER"; then
  fresh="$(mktemp)"
  ref="$(mktemp)"
  docker exec "$NAME" pg_dump -U radar -d radar --schema-only --no-owner --no-privileges | normalize > "$fresh"
  docker exec "$REF_CONTAINER" pg_dump -U "$REF_DB_USER" -d "$REF_DB_NAME" --schema-only --no-owner --no-privileges | normalize > "$ref"
  if ! diff -u "$ref" "$fresh"; then
    echo "FAIL: migration-built schema differs from reference database ($REF_CONTAINER)" >&2
    exit 1
  fi
  echo "OK: schema identical to reference database ($REF_CONTAINER)"
else
  echo "SKIP: reference container $REF_CONTAINER not running; replay-only check passed"
fi
