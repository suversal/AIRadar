#!/usr/bin/env bash
# 一键发布代码到腾讯云服务器：rsync → 重建镜像 → 重启 → 迁移 → 健康检查。
# 用法：
#   bash scripts/deploy_to_server.sh        # 重建 api + web（默认）
#   bash scripts/deploy_to_server.sh web    # 只改了前端
#   bash scripts/deploy_to_server.sh api    # 只改了后端
# 安全性：服务器上构建失败会直接终止，旧版本容器继续在线不受影响。
set -euo pipefail

SERVER="ubuntu@175.24.182.233"
REMOTE_DIR="/home/ubuntu/hotai"
SERVICES="${1:-api web}"
[ "$SERVICES" = "all" ] && SERVICES="api web"

echo "[1/4] 同步代码到服务器..."
# 注意：/data /output 带前导斜杠 = 只排除仓库根目录的同名目录；
# 裸写 data 会误伤 apps/api/app/data/（默认信源模块），导致线上 500。
rsync -az --delete \
  --exclude .git --exclude node_modules --exclude '.next*' --exclude .venv \
  --exclude __pycache__ --exclude /data --exclude /output --exclude /outputs \
  --exclude .env --exclude tsconfig.tsbuildinfo \
  "$(cd "$(dirname "$0")/.." && pwd)/" "$SERVER":"$REMOTE_DIR"/

echo "[2/4] 重建镜像并重启（$SERVICES）..."
ssh "$SERVER" "cd $REMOTE_DIR && sudo docker compose --env-file .env -f infra/docker-compose.prod.yml build $SERVICES && sudo docker compose --env-file .env -f infra/docker-compose.prod.yml up -d"

echo "[3/4] 应用数据库迁移..."
ssh "$SERVER" "cd $REMOTE_DIR && sudo docker compose --env-file .env -f infra/docker-compose.prod.yml exec -T api alembic upgrade head"

echo "[4/4] 健康检查..."
ssh "$SERVER" "cd $REMOTE_DIR && sudo docker compose --env-file .env -f infra/docker-compose.prod.yml ps --format 'table {{.Service}}\t{{.Status}}'"
for path in /latest /all /daily; do
  code=$(curl -s -o /dev/null -m 15 -w "%{http_code}" "http://175.24.182.233$path")
  echo "  线上 $path -> HTTP $code"
  [ "$code" = "200" ] || { echo "健康检查失败：$path 返回 $code"; exit 1; }
done

echo "发布完成。"
