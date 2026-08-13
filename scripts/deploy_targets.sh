#!/usr/bin/env bash
# 部署骨架，被 deploy_to_server.sh / sync_db_to_server.sh 共用：
# 带重试和 IPv6 回退的 ssh/scp/rsync，以及把 TARGET 拆成目标列表的 parse_targets。
#
# **具体推到哪台机器不在本文件里**。服务器地址、用户名、部署路径这些属于本机
# 私有配置，放在同目录的 deploy_targets.local.sh（不进 git），照
# deploy_targets.local.sh.example 复制一份填好即可。这样脚本本体能进仓库、
# 有版本历史，敏感信息仍然只在本机。
#
# 选择目标用 TARGET 环境变量，不设时用 local 文件里的 DEFAULT_TARGET：
#   bash scripts/deploy_to_server.sh                  # 默认目标
#   TARGET=greenvps bash scripts/deploy_to_server.sh  # 指定目标
#   TARGET=a,b bash scripts/sync_db_to_server.sh      # 依次推多台
#
# ⚠️ 多目标是**串行**的，且调用方开着 set -e：排在前面的目标失败会让整轮当场
# 退出，后面的目标一次都轮不到。2026-08-13 腾讯云停机后没及时从默认列表里摘掉，
# 就是这么让线上静默停更了 10 小时。下线一台机器时，先改 DEFAULT_TARGET 再停机。

# local 文件里定义 resolve_target() 与 DEFAULT_TARGET。允许用环境变量指到别处，
# 方便在另一台机器上用不同的目标集跑同一份脚本。
DEPLOY_TARGETS_LOCAL="${DEPLOY_TARGETS_LOCAL:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy_targets.local.sh}"

if [ ! -f "${DEPLOY_TARGETS_LOCAL}" ]; then
  echo "找不到本机目标定义：${DEPLOY_TARGETS_LOCAL}" >&2
  echo "复制一份模板再填：cp scripts/deploy_targets.local.sh.example scripts/deploy_targets.local.sh" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${DEPLOY_TARGETS_LOCAL}"

if ! declare -f resolve_target > /dev/null; then
  echo "${DEPLOY_TARGETS_LOCAL} 里没有定义 resolve_target()，照模板补上" >&2
  exit 1
fi

# 带重试 + IPv6 回退的 ssh。跨太平洋的链路 v4 偶发 "banner exchange timeout"，
# 一次发布里 rsync/ssh 有好几处，任意一处抖动都会让整次发布白跑。
#
# 关键：只在 ssh 自身连不上（退出码 255）时才重试。命令真的跑起来了就原样返回，
# 否则会把"构建失败"这种有副作用的步骤重复执行。
#
# 所有重试函数里都必须写 `rc=0; cmd || rc=$?`，不能写 `cmd; rc=$?`：
# 调用方开了 set -e，裸命令一失败整个脚本就当场退出，rc=$? 那行根本轮不到执行，
# 重试逻辑等于没有。`|| rc=$?` 把命令放进 OR 列表，set -e 才会放行。
ssh_retry() {
  local i host rc
  for i in 1 2 3; do
    for host in "${SERVER}" ${SERVER_FALLBACK:-}; do
      rc=0
      ssh -o ConnectTimeout=20 -o ServerAliveInterval=15 "${host}" "$@" || rc=$?
      [ "${rc}" -ne 255 ] && return "${rc}"
      echo "  （ssh ${host} 连接失败，换通道重试）" >&2
    done
    sleep 4
  done
  return 255
}

# 需要往远端喂脚本时用这个：heredoc 的 stdin 只能被读一次，
# 直接给 ssh_retry 会在第二次重试时喂进空输入。这里把脚本正文存成参数，
# 每次重试重新 printf 一份。
ssh_retry_stdin() {
  local input="$1"; shift
  local i host rc
  for i in 1 2 3; do
    for host in "${SERVER}" ${SERVER_FALLBACK:-}; do
      rc=0
      printf '%s' "${input}" | ssh -o ConnectTimeout=20 -o ServerAliveInterval=15 "${host}" "$@" || rc=$?
      [ "${rc}" -ne 255 ] && return "${rc}"
      echo "  （ssh ${host} 连接失败，换通道重试）" >&2
    done
    sleep 4
  done
  return 255
}

# 传文件用。数据库 dump 有几十兆，跨太平洋更容易中途断。
scp_retry() {
  local i host rc
  for i in 1 2 3; do
    for host in "${SERVER}" ${SERVER_FALLBACK:-}; do
      rc=0
      scp -q -o ConnectTimeout=20 "$1" "${host}":"$2" || rc=$?
      [ "${rc}" -eq 0 ] && return 0
      echo "  （scp 到 ${host} 失败 rc=${rc}，换通道重试）" >&2
    done
    sleep 4
  done
  return 1
}

# rsync 同理。rsync 本身幂等，连接类错误直接整体重试即可。
#
# 排除规则里 /data 的前导斜杠是必须的：裸 data 会连 apps/api/app/data/ 一起排掉，
# 线上会 500。踩过一次。
rsync_retry() {
  local i host rc
  for i in 1 2 3; do
    for host in "${SERVER}" ${SERVER_FALLBACK:-}; do
      rc=0
      rsync -az --delete \
        --exclude .git --exclude node_modules --exclude '.next*' --exclude .venv \
        --exclude __pycache__ --exclude /data --exclude /output --exclude /outputs \
        --exclude .env --exclude tsconfig.tsbuildinfo \
        "$1" "${host}":"$2" || rc=$?
      [ "${rc}" -eq 0 ] && return 0
      echo "  （rsync 到 ${host} 失败 rc=${rc}，换通道重试）" >&2
    done
    sleep 4
  done
  return 1
}

# 把 TARGET 里的逗号分隔列表拆成数组 TARGETS
parse_targets() {
  local raw="${TARGET:-${DEFAULT_TARGET:-}}"
  if [ -z "${raw}" ]; then
    echo "没有指定 TARGET，${DEPLOY_TARGETS_LOCAL} 里也没有 DEFAULT_TARGET" >&2
    return 1
  fi
  IFS=',' read -r -a TARGETS <<< "$raw"
  local t
  for t in "${TARGETS[@]}"; do
    resolve_target "$t" || return 1
  done
}
