#!/usr/bin/env bash
# 把本地 Docker 里的 radar 库完整推送到服务器（整库覆盖，服务器旧数据会被替换）。
# 前提：本地 infra-postgres-1 容器在跑；能免密 ssh 到目标机。
# 用法：
#   bash scripts/sync_db_to_server.sh                        # 推 greenvps（默认）
#   TARGET=tencent bash scripts/sync_db_to_server.sh         # 腾讯云（已停机，见 deploy_targets.sh）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/deploy_targets.sh
source "$SCRIPT_DIR/deploy_targets.sh"
parse_targets

LOCAL_CONTAINER="infra-postgres-1"
DUMP="$(mktemp -t radar-sync).dump"
trap 'rm -f "$DUMP"' EXIT

# 服务器端的替换脚本。用 <<'REMOTE' 而不是把它塞进单引号参数里，是为了能在 SQL
# 里直接写单引号（旧写法要靠 '"'"' 这种转义，改一次错一次）。$DOCKER 由调用方
# 通过环境变量传进远端 bash，这里不展开。
#
# 为什么不直接 DROP DATABASE radar 再恢复：那样从 DROP 到 pg_restore 结束的
# 几十秒里线上根本没有库，页面会渲染成"API 服务暂时不可用"。改成先把新数据恢复
# 到 radar_new（这期间线上仍在用旧库，零影响），最后一步才改名交换，真正的停机
# 收敛到"改名 + api 重启"的两三秒。
read -r -d '' RESTORE_SCRIPT <<'REMOTE' || true
set -euo pipefail

psql_postgres() { $DOCKER exec infra-postgres-1 psql -U radar -d postgres -q "$@"; }

# 清掉上一轮中断可能留下的半成品，否则 CREATE DATABASE 会撞名
psql_postgres -c "DROP DATABASE IF EXISTS radar_new WITH (FORCE);" > /dev/null
psql_postgres -c "DROP DATABASE IF EXISTS radar_old WITH (FORCE);" > /dev/null

psql_postgres -c "CREATE DATABASE radar_new OWNER radar;" > /dev/null
$DOCKER exec -i infra-postgres-1 pg_restore -U radar -d radar_new --no-owner < /tmp/radar-sync.dump
rm -f /tmp/radar-sync.dump
# 本地库的 refresh_schedule 是启用状态，恢复后必须关掉：线上不跑爬取/打分调度
$DOCKER exec infra-postgres-1 psql -U radar -d radar_new -q -c "UPDATE refresh_schedule SET enabled=false;" > /dev/null

# ---- 以下是唯一有停机的一段 ----
# ALTER DATABASE ... RENAME 要求目标库没有活连接。只 terminate 不够：api 的
# 连接池会在 terminate 和 rename 之间抢着重连，所以先禁掉新连接再踢人。
# 万一中途失败，trap 负责把库名和连接开关都还原，不能让站点卡在不可连状态。
rollback_swap() {
  psql_postgres -c "ALTER DATABASE radar_old RENAME TO radar;" > /dev/null 2>&1 || true
  psql_postgres -c "ALTER DATABASE radar WITH ALLOW_CONNECTIONS true;" > /dev/null 2>&1 || true
}
trap rollback_swap ERR

psql_postgres -c "ALTER DATABASE radar WITH ALLOW_CONNECTIONS false;" > /dev/null
psql_postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'radar' AND pid <> pg_backend_pid();" > /dev/null
psql_postgres -c "ALTER DATABASE radar RENAME TO radar_old;" > /dev/null
psql_postgres -c "ALTER DATABASE radar_new RENAME TO radar;" > /dev/null
trap - ERR

# 连接池里全是指向旧库的死连接，必须重启才能接上新库
$DOCKER restart infra-api-1 > /dev/null
# ---- 停机结束 ----

psql_postgres -c "DROP DATABASE IF EXISTS radar_old WITH (FORCE);" > /dev/null
REMOTE

echo "[1/4] 导出本地数据库..."
docker exec "$LOCAL_CONTAINER" pg_dump -U radar -Fc radar > "$DUMP"
echo "      $(du -h "$DUMP" | cut -f1) 已导出"

for target in "${TARGETS[@]}"; do
  resolve_target "$target"
  echo
  echo "########## 推送到 ${TARGET_NAME} (${SERVER}) ##########"

  echo "[2/4] 传输到服务器..."
  scp_retry "$DUMP" /tmp/radar-sync.dump

  echo "[3/4] 服务器端整库替换..."
  ssh_retry_stdin "$RESTORE_SCRIPT" "DOCKER='${DOCKER}' bash -s"

  echo "[4/4] 验证..."
  ssh_retry_stdin '
    $DOCKER exec infra-postgres-1 psql -U radar -d radar -t -c \
      "select '"'"'processed_articles: '"'"' || count(*) from processed_articles
       union all select '"'"'event_clusters: '"'"' || count(*) from event_clusters
       union all select '"'"'pipeline_runs: '"'"' || count(*) from pipeline_runs;"
  ' "DOCKER='${DOCKER}' bash -s"
  curl -s -o /dev/null -m 20 -w "${TARGET_NAME} /latest: HTTP %{http_code}\n" "${BASE_URL}/latest"
done

echo
echo "同步完成。"
