#!/usr/bin/env bash
# 把本地 Docker 里的 radar 库完整推送到腾讯云服务器（整库覆盖，服务器旧数据会被替换）。
# 前提：本地 infra-postgres-1 容器在跑；能免密 ssh ubuntu@175.24.182.233。
# 用法：bash scripts/sync_db_to_server.sh
set -euo pipefail

SERVER="ubuntu@175.24.182.233"
LOCAL_CONTAINER="infra-postgres-1"
DUMP="$(mktemp -t radar-sync).dump"
trap 'rm -f "$DUMP"' EXIT

echo "[1/4] 导出本地数据库..."
docker exec "$LOCAL_CONTAINER" pg_dump -U radar -Fc radar > "$DUMP"
echo "      $(du -h "$DUMP" | cut -f1) 已导出"

echo "[2/4] 传输到服务器..."
scp -q "$DUMP" "$SERVER":/tmp/radar-sync.dump

echo "[3/4] 服务器端整库替换..."
ssh "$SERVER" '
  set -euo pipefail
  sudo docker exec infra-postgres-1 psql -U radar -d postgres -c "DROP DATABASE radar WITH (FORCE);" > /dev/null
  sudo docker exec infra-postgres-1 psql -U radar -d postgres -c "CREATE DATABASE radar OWNER radar;" > /dev/null
  sudo docker exec -i infra-postgres-1 pg_restore -U radar -d radar --no-owner < /tmp/radar-sync.dump
  rm -f /tmp/radar-sync.dump
  # 本地库的 refresh_schedule 是启用状态，恢复后必须关掉：线上不跑爬取/打分调度
  sudo docker exec infra-postgres-1 psql -U radar -d radar -c "UPDATE refresh_schedule SET enabled=false;" > /dev/null
  sudo docker restart infra-api-1 > /dev/null
'

echo "[4/4] 验证..."
ssh "$SERVER" 'sudo docker exec infra-postgres-1 psql -U radar -d radar -t -c \
  "select '"'"'processed_articles: '"'"' || count(*) from processed_articles \
   union all select '"'"'event_clusters: '"'"' || count(*) from event_clusters \
   union all select '"'"'pipeline_runs: '"'"' || count(*) from pipeline_runs;"'
curl -s -o /dev/null -m 15 -w "线上 /latest: HTTP %{http_code}\n" http://175.24.182.233/latest

echo "同步完成。"
