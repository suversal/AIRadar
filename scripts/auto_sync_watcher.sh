#!/bin/zsh
# 看门狗：发现本地库有新完成的 pipeline 运行时，自动把整库推送到腾讯云。
# 由 launchd (com.suversal.ai-radar.autosync) 每 10 分钟调一次。
# 与应用内置调度器（refresh_schedule，每 2 小时刷新一次）解耦：
# 这里只看结果表 pipeline_runs，不关心刷新是谁触发的。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="$ROOT/data/.last_synced_run"
LOCK_DIR="$ROOT/data/.autosync.lock"
LOG="$ROOT/data/logs/autosync.log"
mkdir -p "$ROOT/data/logs"

log() { echo "$(date +%F\ %T) $*" >> "$LOG"; }

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "上一次推送仍在进行，跳过"
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

psql_local() {
  docker exec infra-postgres-1 psql -U radar -d radar -t -A -c "$1"
}

# 刷新进行中则等下个周期（超过 3 小时的 running 视为僵尸记录，忽略）
RUNNING=$(psql_local "select count(*) from pipeline_runs where status='running' and started_at > now() - interval '3 hours';")
if [ "$RUNNING" != "0" ]; then
  log "有刷新正在运行（$RUNNING 个），本轮跳过"
  exit 0
fi

LATEST=$(psql_local "select coalesce(max(id),0) from pipeline_runs where status='succeeded' and finished_at is not null;")
LAST_SYNCED=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

if [ "$LATEST" -le "$LAST_SYNCED" ]; then
  exit 0
fi

log "发现新完成的运行 #$LATEST（上次已推送到 #$LAST_SYNCED），开始推送..."
if bash "$ROOT/scripts/sync_db_to_server.sh" >> "$LOG" 2>&1; then
  echo "$LATEST" > "$STATE_FILE"
  log "推送完成，线上已更新到运行 #$LATEST"
else
  log "推送失败（退出码 $?），下个周期重试"
  exit 1
fi
