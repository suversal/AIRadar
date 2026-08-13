#!/usr/bin/env bash
# 重新构建并重启移动端测试用的生产模式前端服务（standalone，无热编译）。
set -euo pipefail

PORT="${PORT:-3001}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$SCRIPT_DIR/../apps/web"
LOG_FILE="/tmp/ai-radar-web-${PORT}.log"

cd "$WEB_DIR"

echo "==> 停止占用 ${PORT} 端口的旧服务（如果有）"
OLD_PID="$(lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
if [ -n "${OLD_PID}" ]; then
  kill "${OLD_PID}"
  sleep 1
fi

echo "==> 重新构建生产包"
npm run build

echo "==> 拷贝静态资源到 standalone 产物"
rm -rf .next/standalone/.next/static .next/standalone/public
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public

echo "==> 启动服务（端口 ${PORT}）"
PORT="${PORT}" nohup node .next/standalone/server.js > "${LOG_FILE}" 2>&1 &
disown
sleep 2

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "未知")"

echo ""
echo "完成，日志：${LOG_FILE}"
echo "本机访问：           http://localhost:${PORT}"
echo "手机（同 WiFi）访问： http://${LAN_IP}:${PORT}"
