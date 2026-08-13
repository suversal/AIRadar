#!/bin/zsh
# 看门狗：发现本地库有新完成的 pipeline 运行时，自动把整库推送到线上。
# 由 launchd (com.suversal.ai-radar.autosync) 每 10 分钟调一次。
# 与应用内置调度器（refresh_schedule，每 2 小时刷新一次）解耦：
# 这里只看结果表 pipeline_runs，不关心刷新是谁触发的。
set -euo pipefail

# 推送目标：只推 greenvps。腾讯云那台 2026-08-13 已停机下线，留在列表里会让
# 本轮在第一站就失败退出（sync_db_to_server.sh 是 set -e 的串行循环），
# 排在后面的 greenvps 根本轮不到，线上数据会静默停更——这正是当天发生过的事。
# 任一目标失败都会让本轮整体失败并在下个周期重试，状态文件不推进。
: "${TARGET:=greenvps}"
export TARGET

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="$ROOT/data/.last_synced_run"
LOCK_DIR="$ROOT/data/.autosync.lock"
LOG="$ROOT/data/logs/autosync.log"
FAIL_FILE="$ROOT/data/.autosync_fail_count"
mkdir -p "$ROOT/data/logs"

# 连续失败多少轮开始告警。一轮 10 分钟，所以 3 轮 ≈ 30 分钟——
# 比单次网络抖动长，比"没人发现"短。之后每 6 轮（约 1 小时）再提醒一次，
# 既不刷屏也不让人忘掉。2026-08-13 那次连续失败了 60 轮都没人知道。
ALERT_AFTER=3
ALERT_EVERY=6

log() { echo "$(date +%F\ %T) $*" >> "$LOG"; }

# macOS 通知。告警本身绝不能反过来让同步失败，所以全程吞掉错误：
# 通知权限没给、osascript 不可用时静默跳过，日志里仍有完整记录。
#
# 局限：看门狗由 launchd 拉起，Mac 关机或睡眠时它根本不跑，这条通知也不会响。
# 也就是说它能覆盖"机器醒着但推送一直失败"，覆盖不了"机器压根没开"。
notify() {
  osascript -e "display notification \"$2\" with title \"$1\" sound name \"Basso\"" >/dev/null 2>&1 || true
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  # 锁已存在：如果持锁进程还活着才是真忙；持锁进程已死（睡眠打断、被杀）
  # 就是残锁，清掉继续，否则会像 2026-07-28 那样空转两天。
  HOLDER=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
  if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
    log "上一次推送仍在进行（PID $HOLDER），跳过"
    exit 0
  fi
  log "发现残锁（持锁进程 ${HOLDER:-未知} 已不存在），自动清理"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

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

log "发现新完成的运行 #$LATEST（上次已推送到 #$LAST_SYNCED），开始推送到 $TARGET ..."

# 必须写成 `rc=0; cmd || rc=$?`：开头有 set -e，把命令裸放在 if 外面一失败就当场退出。
# 也不能在 else 分支里读 $?——中间插一条命令就把它冲掉了。
FAILS=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
rc=0
bash "$ROOT/scripts/sync_db_to_server.sh" >> "$LOG" 2>&1 || rc=$?

if [ "$rc" -eq 0 ]; then
  echo "$LATEST" > "$STATE_FILE"
  log "推送完成，线上已更新到运行 #$LATEST"
  # 之前告警过就补一条恢复通知，否则用户会一直以为还挂着
  if [ "$FAILS" -ge "$ALERT_AFTER" ]; then
    notify "AI·RADAR 同步已恢复" "连续失败 $FAILS 轮后恢复，线上已更新到运行 #$LATEST"
    log "（同步已恢复，此前连续失败 $FAILS 轮）"
  fi
  echo 0 > "$FAIL_FILE"
else
  FAILS=$(( FAILS + 1 ))
  echo "$FAILS" > "$FAIL_FILE"
  log "推送失败（退出码 $rc），下个周期重试（连续第 $FAILS 轮）"

  # 第 ALERT_AFTER 轮告警一次，之后每 ALERT_EVERY 轮再来一次
  if [ "$FAILS" -eq "$ALERT_AFTER" ] ||
     { [ "$FAILS" -gt "$ALERT_AFTER" ] && [ $(( (FAILS - ALERT_AFTER) % ALERT_EVERY )) -eq 0 ]; }; then
    notify "AI·RADAR 同步失败" "已连续失败 $FAILS 轮（约 $(( FAILS * 10 )) 分钟），线上数据停更中。详见 data/logs/autosync.log"
    log "（已弹出失败通知：连续 $FAILS 轮）"
  fi
  exit 1
fi
