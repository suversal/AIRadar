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
  # 先看容器状态，再看 HTTP —— 顺序不能反，理由见下面两段注释。
  #
  # 2026-08-13 的教训：nginx 配置漏挂了一个文件，容器进入 Restarting 循环、
  # 整站 521，但这一步当时只是 `ssh_retry ... ps` 把表格打印出来、**不做任何校验**，
  # 下面的 HTTP 检查又被 CF 缓存骗过，脚本一路绿灯报"发布完成"。
  # 容器状态是唯一不经过 CF、也不经过任何缓存的信号，必须硬校验。
  ps_table=$(ssh_retry "cd ${REMOTE_DIR} && ${COMPOSE} ps --format 'table {{.Service}}\t{{.Status}}'")
  echo "${ps_table}"
  if echo "${ps_table}" | grep -qiE "restarting|exited|unhealthy|created"; then
    echo "健康检查失败：${TARGET_NAME} 有容器未正常运行（见上表）"
    exit 1
  fi

  # 源站活性：从 nginx 容器内部直连 web:3000。
  # 这是唯一能真正证明"应用在响应"的检查——它既不过 Cloudflare，
  # 也不受源站那份 CF IP 白名单的限制（从服务器本机 curl 公网域名会被白名单挡成 403）。
  #
  # ⚠️ 不要试图用 "?healthcheck=$RANDOM" 这类 cache buster 从公网绕缓存：
  #    2026-08-17 实测，CF 那边的 Cache Rule 缓存键**忽略查询字符串**，
  #    带随机参数请求 /latest /all /daily 拿到的仍然是 cf-cache-status: HIT。
  #    公网这一层没有便宜的办法穿透，别在这上面浪费时间。
  # 检查清单按**服务机制**挑，不是按页面数量堆。同一机制通了，同机制的其它
  # 路径基本也通；机制不同就必须各验一条：
  #   /latest /all /daily        页面（SSR）
  #   /api/v1/items              route handler + 内网取数
  #   /feed.xml                  route handler + XML 出口
  #   /llms.txt                  route handler，不依赖上游
  #   /ai-radar-skill/VERSION    public/ 静态文件
  #
  # 最后那条是 2026-08-20 加的,它自己就是教训:Dockerfile 一直漏拷 public/,
  # standalone 产物里根本没有这个目录,Skill 包线上全 404——而这份检查当时只看
  # 三个页面,一路绿灯报"发布完成"。/brand/*.svg 更是早就 404 了没人发现,
  # 因为站内 logo 走的是内联 SVG 组件,视觉上看不出来。
  for path in /latest /all /daily '/api/v1/items?limit=1' /feed.xml /llms.txt /ai-radar-skill/VERSION; do
    if ssh_retry "${DOCKER} exec infra-nginx-1 wget -q -O /dev/null 'http://web:3000${path}'"; then
      echo "  ${TARGET_NAME} 源站 ${path} -> OK"
    else
      echo "健康检查失败：${TARGET_NAME} 源站 ${path} 无法从 nginx 容器内取到"
      exit 1
    fi
  done

  # MCP 是唯一的 POST 路由,GET 它会拿到 405,上面那个循环覆盖不到。
  # 用 tools/list 探一次:它不碰上游数据,失败就说明路由本身没起来。
  if ssh_retry "${DOCKER} exec infra-nginx-1 wget -q -O /dev/null --header='Content-Type: application/json' --post-data='{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}' http://web:3000/api/mcp"; then
    echo "  ${TARGET_NAME} 源站 /api/mcp (POST) -> OK"
  else
    echo "健康检查失败：${TARGET_NAME} MCP 端点无法从 nginx 容器内调通"
    exit 1
  fi

  # 公网这一层只用来确认 DNS/CF/证书链没断。它**可能被 CF 缓存骗过**
  # （源站已死仍返回 200），所以放在最后、也不作为唯一依据——
  # 真正的判据是上面两步。
  for path in /latest /all /daily; do
    code=$(curl -s -o /dev/null -m 20 -w "%{http_code}" "${BASE_URL}${path}")
    echo "  ${TARGET_NAME} 公网 ${path} -> HTTP ${code}（可能来自 CF 缓存）"
    [ "${code}" = "200" ] || { echo "健康检查失败：${TARGET_NAME} ${path} 返回 ${code}"; exit 1; }
  done

  echo "${TARGET_NAME} 发布完成。"
done
