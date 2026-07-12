#!/bin/zsh
# Scheduled crawl + pipeline refresh. Designed for launchd/cron:
# - a lock directory prevents overlapping runs
# - crawl and local report files always land under data/ even if the
#   database is down; only the DB persist step depends on Postgres
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="$ROOT/data/.refresh.lock"
LOG_DIR="$ROOT/data/logs"
mkdir -p "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$(date -u +%FT%TZ) another refresh is still running, skipping" >> "$LOG_DIR/refresh.log"
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi

{
  echo "==== refresh started $(date -u +%FT%TZ) ===="
  "$PYTHON" "$ROOT/scripts/run_crawl_once.py" --report data/crawl_report.json
  "$PYTHON" "$ROOT/scripts/run_pipeline_once.py" --persist-db
  echo "==== refresh finished $(date -u +%FT%TZ) ===="
} >> "$LOG_DIR/refresh.log" 2>&1
