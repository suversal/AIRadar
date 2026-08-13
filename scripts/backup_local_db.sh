#!/bin/zsh
# 每日备份本地 radar 库到 ~/Backups/hotai/，由 launchd (com.suversal.ai-radar.backup) 触发。
# 保留策略：每月 1 号的快照永久保留；其余保留最近 14 天。
# 恢复方法见 docs/tencent-cloud-deployment-ops.md「备份」一节。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$HOME/Backups/hotai"
LOG="$ROOT/data/logs/backup.log"
TODAY="$(date +%Y%m%d)"
TARGET="$BACKUP_DIR/radar-$TODAY.dump"
mkdir -p "$BACKUP_DIR" "$ROOT/data/logs"

log() { echo "$(date +%F\ %T) $*" >> "$LOG"; }

# 当天已备份过就不重复（launchd 在睡眠唤醒后可能补触发多次）
if [ -s "$TARGET" ]; then
  exit 0
fi

if ! docker exec infra-postgres-1 pg_dump -U radar -Fc radar > "$TARGET.tmp" 2>>"$LOG"; then
  log "备份失败：pg_dump 出错（本地 postgres 容器是否在运行？）"
  rm -f "$TARGET.tmp"
  exit 1
fi

# 小于 1M 视为异常产物，不入库也不触发清理，避免坏备份挤掉好备份
SIZE=$(stat -f%z "$TARGET.tmp")
if [ "$SIZE" -lt 1048576 ]; then
  log "备份异常：产物只有 ${SIZE} 字节，已丢弃"
  rm -f "$TARGET.tmp"
  exit 1
fi

mv "$TARGET.tmp" "$TARGET"
log "备份完成：$TARGET（$(du -h "$TARGET" | cut -f1)）"

# 清理：删 14 天前的非每月 1 号快照
find "$BACKUP_DIR" -name 'radar-*.dump' -mtime +14 ! -name 'radar-??????01.dump' -delete
log "当前备份共 $(ls "$BACKUP_DIR"/radar-*.dump 2>/dev/null | wc -l | tr -d ' ') 份，占用 $(du -sh "$BACKUP_DIR" | cut -f1)"
