#!/usr/bin/env bash
# 一键发布代码到服务器：rsync → 重建镜像 → 重启 → 迁移 → 健康检查。
# 用法：
#   bash scripts/deploy_to_server.sh                     # greenvps，重建 api + web
#   bash scripts/deploy_to_server.sh web                 # greenvps，只改了前端
#   TARGET=tencent bash scripts/deploy_to_server.sh      # 腾讯云（已停机，见 deploy_targets.sh）
# 安全性：服务器上构建失败会直接终止，旧版本容器继续在线不受影响。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/deploy_targets.sh
source "$SCRIPT_DIR/deploy_targets.sh"
parse_targets

SERVICES="${1:-api web}"
[ "${SERVICES}" = "all" ] && SERVICES="api web"

for target in "${TARGETS[@]}"; do
  resolve_target "$target"
  COMPOSE="${DOCKER} compose --env-file .env ${COMPOSE_FILES}"
  echo
  echo "########## 发布到 ${TARGET_NAME} (${SERVER}) ##########"

  echo "[1/4] 同步代码到服务器..."
  # 排除规则见 rsync_retry。注意 /data /output 带前导斜杠 = 只排除仓库根目录的
  # 同名目录；裸写 data 会误伤 apps/api/app/data/（默认信源模块），导致线上 500。
  # 证书存在 data/certs/ 也正是靠这条排除规则躲开 --delete。
  rsync_retry "${REPO_ROOT}/" "${REMOTE_DIR}/"

  echo "[2/4] 重建镜像并重启（${SERVICES}）..."
  # 最后重启 nginx：web 容器重建后内网 IP 可能变化，而 nginx 只在启动时解析
  # 一次 upstream 主机名，不重启会拿着旧 IP 返回 502。
  ssh_retry "cd ${REMOTE_DIR} && ${COMPOSE} build ${SERVICES} && ${COMPOSE} up -d && ${DOCKER} restart infra-nginx-1 > /dev/null"

  echo "[3/4] 应用数据库迁移..."
  ssh_retry "cd ${REMOTE_DIR} && ${COMPOSE} exec -T api alembic upgrade head"

  echo "[4/4] 健康检查..."
  ssh_retry "cd ${REMOTE_DIR} && ${COMPOSE} ps --format 'table {{.Service}}\t{{.Status}}'"
  for path in /latest /all /daily; do
    code=$(curl -s -o /dev/null -m 20 -w "%{http_code}" "${BASE_URL}${path}")
    echo "  ${TARGET_NAME} ${path} -> HTTP ${code}"
    [ "${code}" = "200" ] || { echo "健康检查失败：${TARGET_NAME} ${path} 返回 ${code}"; exit 1; }
  done

  echo "${TARGET_NAME} 发布完成。"
done
