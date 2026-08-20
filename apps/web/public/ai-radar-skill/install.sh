#!/usr/bin/env bash
#
# AI·RADAR Agent Skill 安装器
#
# 设计原则（每一条都是为了不弄坏你已有的环境）：
#   1. 不猜平台。必须显式 --target，装错目录比没装更难查。
#   2. 不覆盖别家 Skill。目标目录若不是本 Skill 的，直接停下。
#   3. 发现重复副本就停。多个平台各存一份正文，升级时必然漏掉一份。
#   4. 先下载校验，再原子替换。不会出现"删了旧的、新的没下来"的中间态。
#   5. 旧版本备份保留，不做 rm -rf。
#
# 用法：
#   bash <(curl -fsSL https://radar.suversal.com/ai-radar-skill/install.sh) --target agents
#   bash <(curl -fsSL https://radar.suversal.com/ai-radar-skill/install.sh) --target claude
#
# 执行前请先审阅本脚本与 SKILL.md：
#   curl -fsSL https://radar.suversal.com/ai-radar-skill/install.sh | less
#   curl -fsSL https://radar.suversal.com/ai-radar-skill/SKILL.md   | less

set -euo pipefail

SKILL_NAME="ai-radar"
BASE_URL="${AI_RADAR_SKILL_BASE:-https://radar.suversal.com/ai-radar-skill}"
FILES=(SKILL.md VERSION)

AGENTS_ROOT="$HOME/.agents/skills"
CLAUDE_ROOT="$HOME/.claude/skills"

TARGET=""
MIGRATE_LEGACY=0
DRY_RUN=0

die() { printf '\n错误：%s\n' "$1" >&2; exit 1; }
info() { printf '%s\n' "$1"; }

usage() {
  cat <<'EOF'
AI·RADAR Agent Skill 安装器

  --target agents    装到 ~/.agents/skills/ai-radar
                     这是跨工具的共享 skills 目录。如果你的 Agent 从这里加载
                     Skill，装一次就能被发现；具体约定请查它自己的文档。

  --target claude    装到 ~/.agents/skills/ai-radar，并在
                     ~/.claude/skills/ai-radar 建一个指向它的软链。
                     不复制第二份正文，升级只需动一处。

  --migrate-legacy   发现 ~/.codex/skills/ai-radar 等旧副本时，把它们移到
                     同目录下的 .ai-radar-legacy-<时间戳> 备份，然后继续安装。
                     不加这个参数时遇到旧副本会停下让你确认。

  --dry-run          只打印将要做什么，不改任何文件。
  --help             显示本说明。
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    # 必须先查有没有值：`install.sh --target` 时 $# 是 1，shift 2 返回非零，
    # set -e 会让脚本一声不吭地退出 1，用户连"必须指定 --target"都看不到。
    --target)
      [ $# -ge 2 ] || die "--target 后面要跟 agents 或 claude。用 --help 看用法。"
      TARGET="$2"; shift 2 ;;
    --target=*) TARGET="${1#*=}"; shift ;;
    --migrate-legacy) MIGRATE_LEGACY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "不认识的参数：$1。用 --help 看用法。" ;;
  esac
done

if [ -z "$TARGET" ]; then
  usage
  die "必须指定 --target。安装器不猜平台——装错目录的 Skill 不会报错，只是永远不触发。"
fi

case "$TARGET" in
  agents|claude) ;;
  *) die "--target 只能是 agents 或 claude，收到 \"$TARGET\"。" ;;
esac

command -v curl >/dev/null 2>&1 || die "需要 curl。"

# ---------- 1. 先看有没有重复副本 ----------
# 各平台早期各自约定过 skills 目录。同时存在多份正文时，升级只会命中一份，
# 之后 Agent 用的是哪份全看它先扫到谁——这种问题极难排查，所以宁可停下。
LEGACY_DIRS=(
  "$HOME/.codex/skills/$SKILL_NAME"
  "$HOME/.gemini/skills/$SKILL_NAME"
  "$HOME/.config/opencode/skills/$SKILL_NAME"
)
# claude 目标下软链是预期产物，不算旧副本；真实目录才算。
if [ "$TARGET" = "agents" ] && [ -d "$CLAUDE_ROOT/$SKILL_NAME" ] && [ ! -L "$CLAUDE_ROOT/$SKILL_NAME" ]; then
  LEGACY_DIRS+=("$CLAUDE_ROOT/$SKILL_NAME")
fi

# 注意 bash 3.2（macOS 自带）在 set -u 下展开空数组会报 unbound variable，
# 所以每处展开前都先用 ${#arr[@]} 判长度。
FOUND_LEGACY=()
for dir in "${LEGACY_DIRS[@]}"; do
  [ -e "$dir" ] && FOUND_LEGACY+=("$dir")
done

if [ ${#FOUND_LEGACY[@]} -gt 0 ] && [ "$MIGRATE_LEGACY" -eq 0 ]; then
  printf '\n发现本 Skill 的其它副本：\n' >&2
  for dir in "${FOUND_LEGACY[@]}"; do printf '  %s\n' "$dir" >&2; done
  cat >&2 <<EOF

留着它们的话，升级只会更新本次目标目录，Agent 可能仍在读旧副本。

请先确认这些目录确实是本 Skill 留下的，然后二选一：
  · 自己删掉或移走它们，再重跑本安装器；
  · 或者加 --migrate-legacy，让安装器把它们备份到同目录下的
    .${SKILL_NAME}-legacy-<时间戳>，再继续安装。
EOF
  exit 1
fi

# ---------- 2. 下载到临时目录并校验 ----------
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/${SKILL_NAME}-install.XXXXXX")"
cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT

info "从 $BASE_URL 下载…"
for file in "${FILES[@]}"; do
  if ! curl -fsSL --max-time 30 "$BASE_URL/$file" -o "$STAGING/$file"; then
    die "下载 $file 失败。检查网络或稍后重试；本次没有改动任何文件。"
  fi
done

# 校验的是"下全了、没下到错误页"，不是来源真实性——传输安全由 HTTPS 负责。
[ -s "$STAGING/SKILL.md" ] || die "下载到的 SKILL.md 是空的，已中止。"
head -n 1 "$STAGING/SKILL.md" | grep -q '^---$' \
  || die "下载到的 SKILL.md 不是有效的 Skill 文件（缺少 frontmatter），可能拿到了错误页。已中止。"
grep -q "^name: $SKILL_NAME\$" "$STAGING/SKILL.md" \
  || die "下载到的 SKILL.md 里的 name 不是 ${SKILL_NAME}，已中止。"

VERSION="$(tr -d ' \t\n\r' < "$STAGING/VERSION")"
[ -n "$VERSION" ] || die "VERSION 文件为空，已中止。"
info "完整包校验通过，版本 ${VERSION}。"

# ---------- 3. 确认目标目录可以动 ----------
INSTALL_DIR="$AGENTS_ROOT/$SKILL_NAME"

if [ -e "$INSTALL_DIR" ]; then
  if [ ! -f "$INSTALL_DIR/SKILL.md" ] || ! grep -q "^name: $SKILL_NAME\$" "$INSTALL_DIR/SKILL.md" 2>/dev/null; then
    die "$INSTALL_DIR 已存在，但里面不是 $SKILL_NAME 的 Skill。安装器不会覆盖别人的东西，请自行确认后处理。"
  fi
  OLD_VERSION="$(tr -d ' \t\n\r' < "$INSTALL_DIR/VERSION" 2>/dev/null || echo '未知')"
  info "将把已安装的 $OLD_VERSION 升级到 ${VERSION}。"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  info ""
  info "[dry-run] 将要做的事："
  if [ ${#FOUND_LEGACY[@]} -gt 0 ]; then
    for dir in "${FOUND_LEGACY[@]}"; do info "  备份旧副本 $dir"; done
  fi
  info "  安装到 $INSTALL_DIR"
  [ "$TARGET" = "claude" ] && info "  建软链 $CLAUDE_ROOT/$SKILL_NAME -> $INSTALL_DIR"
  info "[dry-run] 没有改动任何文件。"
  exit 0
fi

# ---------- 4. 备份旧副本 ----------
STAMP="$(date +%Y%m%d%H%M%S)"
if [ ${#FOUND_LEGACY[@]} -gt 0 ]; then
  for dir in "${FOUND_LEGACY[@]}"; do
    backup="$(dirname "$dir")/.${SKILL_NAME}-legacy-${STAMP}"
    mv "$dir" "$backup"
    info "旧副本已备份到 $backup"
  done
fi

# ---------- 5. 原子替换 ----------
mkdir -p "$AGENTS_ROOT"
STAGED_FINAL="$AGENTS_ROOT/.$SKILL_NAME-staged-$STAMP"
cp -R "$STAGING" "$STAGED_FINAL"

if [ -e "$INSTALL_DIR" ]; then
  # 先把旧的挪开再把新的换上，两步都是同一文件系统内的 mv（原子操作），
  # 中途失败最坏是留下一个备份目录，不会出现"两边都没有"的状态。
  mv "$INSTALL_DIR" "$AGENTS_ROOT/.$SKILL_NAME-backup-$STAMP"
fi
mv "$STAGED_FINAL" "$INSTALL_DIR"
info "已安装到 $INSTALL_DIR"

# ---------- 6. Claude Code 软链 ----------
if [ "$TARGET" = "claude" ]; then
  mkdir -p "$CLAUDE_ROOT"
  LINK="$CLAUDE_ROOT/$SKILL_NAME"
  if [ -L "$LINK" ]; then
    rm "$LINK"
  elif [ -e "$LINK" ]; then
    mv "$LINK" "$CLAUDE_ROOT/.$SKILL_NAME-backup-$STAMP"
    info "$LINK 原有内容已备份。"
  fi
  ln -s "$INSTALL_DIR" "$LINK"
  info "已创建软链 $LINK -> $INSTALL_DIR"
fi

cat <<EOF

装好了。接下来：

  1. 开一个新会话。多数 Agent 只在会话开始时扫描 Skill，当前对话不一定看得到。
  2. 问一句验证：「过去 24 小时 AI 圈最重要的 5 件事是什么？」
     成功的样子：回答注明"过去 24 小时"，给出中文摘要（当天不足就如实说明只有几条），
     标题链接到 radar.suversal.com 的阅读页。

没触发的话按这个顺序排查：
  · 确认文件在 $INSTALL_DIR/SKILL.md
  · 关掉旧会话重开一个
  · 让 Agent 列出它发现的 skills，确认里面有 $SKILL_NAME
  · 仍失败：把平台、版本和安装路径提交到 https://radar.suversal.com/feedback
    （别贴 token 或本地文件内容）
EOF
