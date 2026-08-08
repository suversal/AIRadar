"""X 推文中文化（方案 B：翻译在 AR 侧做，SP 不做）。

为什么在这里而不是上游：X 的接口响应不带翻译（客户端的「翻译帖子」是点击时
另调的内部接口），SP 侧模拟调它要耗账号池配额、扩大封号面积；而中文化本来
就是 AIRADAR 的职责（采集/打分分工），且这边有现成的 AI provider。

与「推文不进 LLM 管线」（接入方案决策 4）不冲突：那条禁的是打分/聚类/成报，
翻译是独立的轻量批处理——每轮只翻新增或原文变更的推文，不碰管线。

失效重翻：译文带 source_hash（原文指纹）。长文正文（article_markdown）是
SP 后补的，补上后 display_text 从一句入口语变成整篇文章，hash 变了自动重翻。

Markdown 保护：图片/视频缩略图这类纯标记段落不送模型（模型会改坏 URL），
按段落位置原样织回译文。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: 每轮最多翻多少条——失控保护，正常增量每轮就几条到十几条
DEFAULT_BATCH_LIMIT = 30
#: 每次 provider 调用的段落字符预算。中文输出 token 约等于字符数，
#: 要留在最小的 chat max_tokens(2048) 之下（与 pipeline/runner 同一考量）
_CHUNK_CHAR_BUDGET = 1200

#: 纯标记段落：整段是图片 / 可点击缩略图 / 裸链接，不送模型
_MARKUP_ONLY = re.compile(
    r"^\s*(\[?!\[[^\]]*\]\([^)]*\)\]?(\([^)]*\))?|\<?https?://\S+\>?)\s*$"
)


def source_hash(tweet: dict[str, Any]) -> str:
    basis = "\x00".join(
        [tweet.get("display_text") or "", tweet.get("quoted_text") or ""]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _cjk_ratio(text: str) -> float:
    """CJK 字符占非空白字符的比例，用来判断「本来就是中文」。"""
    meaningful = [c for c in text if not c.isspace()]
    if not meaningful:
        return 0.0
    cjk = sum(1 for c in meaningful if "一" <= c <= "鿿")
    return cjk / len(meaningful)


def needs_translation(row: Any) -> bool:
    """无译文，或原文变了（source_hash 不匹配）。skipped 记录也带 hash，
    中文推文不会每轮被重新判一遍。"""
    tweet = row.payload
    current = source_hash(tweet)
    existing = row.translation or {}
    return existing.get("source_hash") != current


def _translate_markdown(translate: Any, markdown: str) -> str:
    """逐段翻译并保持 Markdown 结构。标记段原位保留；文本段按预算分批。"""
    paragraphs = markdown.split("\n\n")
    text_indexes = [
        i
        for i, p in enumerate(paragraphs)
        if p.strip() and not _MARKUP_ONLY.match(p)
    ]
    translated = list(paragraphs)

    batch: list[int] = []
    batch_chars = 0

    def flush() -> None:
        nonlocal batch, batch_chars
        if not batch:
            return
        source = [paragraphs[i] for i in batch]
        result = translate(source)
        if len(result) != len(source):
            # 模型把多段并成了一段（实测发生过 3→1）。错位拼接比不翻更糟，
            # 退回逐段单发——段落数恒为 1:1，代价只是多几次调用
            logger.warning(
                "translation returned %d paragraphs for %d inputs; retrying one by one",
                len(result),
                len(source),
            )
            for index in batch:
                single = translate([paragraphs[index]])
                if len(single) == 1:
                    translated[index] = single[0]
        else:
            for index, text in zip(batch, result):
                translated[index] = text
        batch = []
        batch_chars = 0

    for i in text_indexes:
        length = len(paragraphs[i])
        if batch and batch_chars + length > _CHUNK_CHAR_BUDGET:
            flush()
        batch.append(i)
        batch_chars += length
    flush()
    return "\n\n".join(translated)


def translate_x_tweets(
    repository: Any,
    provider: Any,
    *,
    limit: int = DEFAULT_BATCH_LIMIT,
) -> dict[str, Any]:
    """批量翻译需要翻的推文。单条失败不拖垮整批，译文即时回写。

    provider 需实现 translate_paragraphs(list[str]) -> list[str]
    （FakeAIProvider / Kimi / DeepSeek / OpenAI 都有）。
    """
    report: dict[str, Any] = {"translated": 0, "skipped_zh": 0, "failed": 0}
    translate = getattr(provider, "translate_paragraphs", None)
    if translate is None:
        report["error"] = "provider has no translate_paragraphs"
        return report

    candidates = [
        row for row in repository.x_tweets_for_translation() if needs_translation(row)
    ]
    for row in candidates[:limit]:
        tweet = row.payload
        current_hash = source_hash(tweet)
        display_text = tweet.get("display_text") or ""
        if _cjk_ratio(display_text) > 0.3:
            repository.save_x_tweet_translation(
                row.tweet_id, {"skipped": "zh", "source_hash": current_hash}
            )
            report["skipped_zh"] += 1
            continue
        try:
            display_zh = _translate_markdown(translate, display_text)
            quoted = (tweet.get("quoted_text") or "").strip()
            quoted_zh = None
            if quoted and _cjk_ratio(quoted) <= 0.3:
                quoted_zh = _translate_markdown(translate, quoted)
        except Exception as exc:
            logger.warning("tweet translation failed for %s: %s", row.tweet_id, exc)
            report["failed"] += 1
            continue
        repository.save_x_tweet_translation(
            row.tweet_id,
            {
                "display_text_zh": display_zh,
                "quoted_text_zh": quoted_zh,
                "source_hash": current_hash,
                "model": getattr(provider, "model", None)
                or getattr(provider, "scoring_model", None)
                or type(provider).__name__,
                "translated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        report["translated"] += 1
    remaining = len(candidates) - min(len(candidates), limit)
    if remaining:
        report["remaining"] = remaining  # 超预算的下轮接着翻，不静默丢
    return report
