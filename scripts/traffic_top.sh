#!/usr/bin/env bash
# 流量速查：站点变慢或疑似被攻击时，第一时间跑这个。
#
# 真被打的时候没人有心情现敲 awk，所以把"该看什么"固化下来。
# 排查顺序参考 docs/2026-08-13-hardening-plan.md 第三节的 5 分钟处置流程。
#
#   bash scripts/traffic_top.sh              # 看最近 10 分钟
#   bash scripts/traffic_top.sh 1h           # 看最近 1 小时
#   TARGET=greenvps bash scripts/traffic_top.sh
#
# 依赖 nginx 的 radar 日志格式（infra/nginx/00-hardening.conf）：
#   IP - [时间] "请求行" 状态码 字节 耗时s cache=命中状态 cf=Ray ref="..." ua="..."

set -euo pipefail

SINCE="${1:-10m}"
TARGET="${TARGET:-greenvps}"
CONTAINER="${CONTAINER:-infra-nginx-1}"
TOP="${TOP:-15}"

case "$TARGET" in
  greenvps) SSH_HOST="greenvps" ;;
  local)    SSH_HOST="" ;;
  *)        SSH_HOST="$TARGET" ;;
esac

run() {
  if [ -z "$SSH_HOST" ]; then
    sh -c "$1"
  else
    ssh "$SSH_HOST" "$1"
  fi
}

LOG=$(run "docker logs --since $SINCE $CONTAINER 2>&1" || true)
TOTAL=$(printf '%s\n' "$LOG" | grep -c . || true)

echo "============================================================"
echo " 目标 $TARGET / 容器 $CONTAINER / 窗口 最近 $SINCE"
echo " 日志行数：$TOTAL"
echo "============================================================"

if [ "$TOTAL" -eq 0 ]; then
  echo "没有日志。确认容器名对不对，或者这段时间真的没有流量。"
  exit 0
fi

section() { echo; echo "── $1 ──────────────────────────────────"; }

section "请求最多的 IP（攻击时这里会有一两个 IP 明显冒头）"
printf '%s\n' "$LOG" | awk '{print $1}' | sort | uniq -c | sort -rn | head -"$TOP"

section "请求最多的路径"
printf '%s\n' "$LOG" | awk -F'"' '{print $2}' | awk '{print $1, $2}' | sort | uniq -c | sort -rn | head -"$TOP"

section "User-Agent 分布（署名式攻击会在这里露出来，比如 #TeamAntiAI）"
printf '%s\n' "$LOG" | grep -o 'ua="[^"]*"' | sort | uniq -c | sort -rn | head -"$TOP"

section "状态码分布（429 变多 = 限流在起作用；5xx 变多 = 已经打穿了）"
printf '%s\n' "$LOG" | awk '{print $6}' | sort | uniq -c | sort -rn

section "缓存命中情况（HIT 占比越高越安全；大量 MISS 说明缓存没在工作）"
printf '%s\n' "$LOG" | grep -o 'cache=[A-Z-]*' | sort | uniq -c | sort -rn

section "最慢的请求 Top $TOP（耗时是攻击的第一个信号，往往先于报错）"
printf '%s\n' "$LOG" | grep -oE '[0-9.]+s cache=' | tr -d 's cache=' | sort -rn | head -"$TOP" |
  while read -r t; do printf '  %ss\n' "$t"; done

section "回到 429 的 IP（已经被限流挡住的）"
printf '%s\n' "$LOG" | awk '$6 == 429 {print $1}' | sort | uniq -c | sort -rn | head -"$TOP"

echo
echo "接下来："
echo "  · 单个 IP 占比畸高      → 加进 nginx 黑名单，重启 infra-nginx-1"
echo "  · 多 IP 但路径高度集中   → 是应用层 CC，去 CF 开 'I'm Under Attack'"
echo "  · cache 全是 MISS       → 先查缓存为什么没生效，别急着封 IP"
