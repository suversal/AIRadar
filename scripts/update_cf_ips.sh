#!/usr/bin/env bash
# 从 Cloudflare 官方地址拉取 IP 段，生成 infra/nginx/cloudflare-ips.conf。
# CF 偶尔会调整网段，官方建议定期同步；改完记得重新发布 greenvps。
# 用法：bash scripts/update_cf_ips.sh && TARGET=greenvps bash scripts/deploy_to_server.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/infra/nginx/cloudflare-ips.conf"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

V4="$(curl -fsS -m 30 https://www.cloudflare.com/ips-v4)"
V6="$(curl -fsS -m 30 https://www.cloudflare.com/ips-v6)"

# 拉到空内容就直接失败，否则会生成一个把所有人挡在外面的空白名单
[ -n "$V4" ] && [ -n "$V6" ] || { echo "拉取 Cloudflare IP 段失败，已中止（不覆盖现有文件）" >&2; exit 1; }

{
  echo "# Cloudflare 官方 IP 段 —— 本文件由 scripts/update_cf_ips.sh 生成，勿手工编辑。"
  echo "# 生成时间：$(date +%F\ %T)"
  echo "#"
  echo "# 这里做两件事："
  echo "#   1) set_real_ip_from + real_ip_header：把 CF 转发来的真实访客 IP 还原进 \$remote_addr，"
  echo "#      否则日志和限流看到的全是 CF 的地址。"
  echo "#   2) geo \$from_cloudflare：标记连接是否来自 CF。"
  echo "#"
  echo "# 关键点：geo 的源变量必须是 \$realip_remote_addr 而不是 \$remote_addr。"
  echo "# realip 模块在 access 阶段之前就把 \$remote_addr 换成了真实访客 IP，"
  echo "# 用它做白名单会把所有正常访客判成\"非 CF\"而 403。"
  echo "# \$realip_remote_addr 保留的是原始 TCP 对端地址，也就是 CF 边缘节点。"
  echo ""
  while read -r cidr; do
    [ -n "$cidr" ] && echo "set_real_ip_from $cidr;"
  done <<< "$V4"
  while read -r cidr; do
    [ -n "$cidr" ] && echo "set_real_ip_from $cidr;"
  done <<< "$V6"
  echo ""
  echo "real_ip_header CF-Connecting-IP;"
  echo ""
  echo "geo \$realip_remote_addr \$from_cloudflare {"
  echo "    default 0;"
  while read -r cidr; do
    [ -n "$cidr" ] && echo "    $cidr 1;"
  done <<< "$V4"
  while read -r cidr; do
    [ -n "$cidr" ] && echo "    $cidr 1;"
  done <<< "$V6"
  echo "}"
} > "$TMP"

mv "$TMP" "$OUT"
# 变量后紧跟中文全角字符时必须写 ${VAR}：裸 $VAR 会被 bash 连着多字节字符一起解析，
# 报 "unbound variable"。这个坑在本仓库的部署脚本里踩过不止一次。
echo "已生成 ${OUT}（IPv4 $(wc -l <<< "${V4}") 段 / IPv6 $(wc -l <<< "${V6}") 段）"
