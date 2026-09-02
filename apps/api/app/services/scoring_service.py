from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.domain import AIFocus, ContentValueDimensions, ProcessedArticle, RawArticle, Source
from app.services.taxonomy import resolve_focus_category
from app.services.topics import derive_topic_ids

# 内容价值分(value_score, 0-100)的三维权重。ai_focus不参与这个加权求和——
# 是否为AI内容由独立的分类层决定(select_processed_article只有在ai_focus属于
# SELECTABLE_AI_FOCUS时才会计算这三维)，value_score只回答"这条已经确认是AI
# 内容的文章，有多重要/多新/多扎实"，两个问题不再互相稀释。
VALUE_DIMENSION_WEIGHTS = {
    "impact": 0.4,
    "novelty": 0.3,
    "substance": 0.3,
}

# 信源可信度系数——只做加成，不做惩罚：T3(基线)=1.0，tier越高加成越明显。
# 不像之前的evidence_score那样单独设可信度门槛，而是直接乘在内容分上：同样
# 写得好的内容，从更权威的信源报道出来，最终分数应该更突出，但不会因为信源
# 等级较低就把内容本身的分数往下打折——那样会出现"内容明明不错，只因为信源
# 是T3就被扣分"的问题(2026-07-28讨论中的真实案例：一篇impact/novelty/
# substance=7/6/7的Kimi K3开源报道，只因信源是T3就被打折，不合理)。
# 未配置/未知tier按T3(不加成)处理。
TIER_COEFFICIENT = {
    "T1": 1.2,
    "T2": 1.1,
    "T3": 1.0,
}
DEFAULT_TIER_COEFFICIENT = 1.0

# 普通内容的精选门槛。保留历史常量名以避免调用方大面积改名，
# 但它实际比较的是已包含信源 tier 加成的 final_score。2026-09-02
# 从 60 小幅提到 65，不改 AI 三维分、权重或提示词；必读运营更新和
# arXiv 预印本由下面的独立策略判断。
VALUE_SCORE_THRESHOLD = 65.0

# 只有这两个分类才会进入value_score的计算与入选判断；tangential(AI只是顺带
# 提及)在分类层就直接淘汰，不再往下算分。
SELECTABLE_AI_FOCUS: frozenset[str] = frozenset({"primary", "contributing"})

ARXIV_SOURCE_ID = "arxiv_ai"
ARXIV_MIN_IMPACT = 7.0
ARXIV_MIN_NOVELTY = 8.0
ARXIV_MIN_SUBSTANCE = 9.0

_CONFIRMED_MODEL_RELEASE = re.compile(
    r"(?:正式)?(?:发布|推出|上线|开放(?:使用|调用|权重)?|公测)"
    r"|(?:模型|权重).{0,8}开源|开源.{0,8}(?:模型|权重)"
    r"|\b(?:releases|released|launches|launched|introduces|introduced)\b"
    r"|\b(?:now|generally) available\b|\bopen[- ]weights?\b",
    re.IGNORECASE,
)
_UNCONFIRMED_MODEL_RELEASE = re.compile(
    r"消息称|爆料|传闻|泄露|预计|计划|规划|目标|拟于?|将于|即将|或将|或于|有望"
    r"|内测|灰测|内部测试|测试中|踪迹|曝光|预告|发布在即|延后|推迟"
    r"|或.{0,10}(?:发布|推出|上线|开放|开源|公测)"
    r"|(?:明日|明天|下周|月底|年内|周[一二三四五六日天]).{0,8}(?:发布|推出|上线|开放|开源|公测)"
    r"|将(?:正式)?(?:发布|推出|上线|开放|开源|公测)"
    r"|\b(?:reportedly|rumou?rs?|leaks?|plans? to|expected to|coming soon|next week|preview|testing|teases?)\b",
    re.IGNORECASE,
)
_AI_MODEL_IDENTITY = re.compile(
    r"(?:AI|人工智能)?(?:大|语言|推理|视频|图像|多模态|生成式)?模型"
    r"|\b(?:AI|foundation|language|reasoning|video|image|multimodal) models?\b"
    r"|\b(?:GPT|Claude|Gemini|GLM|Qwen|Llama|DeepSeek|Kimi|Grok|Mistral|Wan)\s*[-\w.]*\b"
    r"|(?:\bOpenAI\b.{0,24}\bo\d(?:[-\w.]*)?\b|\bo\d(?:[-\w.]*)?\b.{0,24}\bOpenAI\b)",
    re.IGNORECASE,
)

_USAGE_TERM = r"(?:额度|配额|限额|用量|使用上限|使用限制|usage limits?|rate limits?|quotas?)"
_USAGE_ACTION = (
    r"(?:重置|恢复|重启|上调|下调|提高|提升|增加|降低|减少|延长|取消|"
    r"重新限制|调整|刷新|reset|restore|restart|increase|decrease|extend|remove|adjust)"
)
_CONFIRMED_USAGE_UPDATE = re.compile(
    rf"(?:{_USAGE_TERM}.{{0,24}}{_USAGE_ACTION}|{_USAGE_ACTION}.{{0,24}}{_USAGE_TERM})",
    re.IGNORECASE,
)
_NO_USAGE_LIMIT = re.compile(
    r"(?:无|取消|without|no).{0,12}(?:使用)?(?:限制|限额|limit)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SelectionDecision:
    selected: bool
    selection_origin: str
    selection_reason: str | None
    rejection_reason: str | None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _clamp_dimension(value: float) -> float:
    return max(0.0, min(10.0, float(value)))


def compute_value_score(dimensions: ContentValueDimensions) -> float:
    weighted = (
        _clamp_dimension(dimensions.impact) * VALUE_DIMENSION_WEIGHTS["impact"]
        + _clamp_dimension(dimensions.novelty) * VALUE_DIMENSION_WEIGHTS["novelty"]
        + _clamp_dimension(dimensions.substance) * VALUE_DIMENSION_WEIGHTS["substance"]
    )
    return round(_clamp(weighted * 10), 2)


def compute_final_score(dimensions: ContentValueDimensions, source_tier: str) -> float:
    value_score = compute_value_score(dimensions)
    coefficient = TIER_COEFFICIENT.get(source_tier, DEFAULT_TIER_COEFFICIENT)
    return round(_clamp(value_score * coefficient), 2)


def _selection_title_text(article: RawArticle, generated_fields: dict[str, Any]) -> str:
    """优先事件只看原始标题和中文标题。

    不用摘要，因为摘要常会在背景段提到“发布”、“额度”，
    容易把解读、传闻或泛产品新闻误判为必读更新。
    """
    return "\n".join(
        part.strip()
        for part in (article.title, str(generated_fields.get("title_zh") or ""))
        if part and part.strip()
    )


def _is_confirmed_model_release(
    *, article: RawArticle, category: str, generated_fields: dict[str, Any]
) -> bool:
    if category != "model_release":
        return False
    title = _selection_title_text(article, generated_fields)
    if not _AI_MODEL_IDENTITY.search(title):
        return False
    # 按标题分句判断：“已发布 A，将开放 API”仍是已发布；
    # 但“今晚将开源权重”的未来分句不能当成已发布。
    clauses = re.split(r"[\n，,。；;：:！!？?]+", title)
    return any(
        _CONFIRMED_MODEL_RELEASE.search(clause)
        and not _UNCONFIRMED_MODEL_RELEASE.search(clause)
        for clause in clauses
    )


def _is_confirmed_usage_update(
    *,
    article: RawArticle,
    category: str,
    dimensions: ContentValueDimensions,
    generated_fields: dict[str, Any],
) -> bool:
    # 额度变更必须是一级事件，且至少有基本事实信息；这样可以
    # 救回“恢复/重置额度”，又不会把教程、猜测和普通解读直接精选。
    if category not in {"product_release", "model_release", "industry_news"}:
        return False
    if dimensions.substance < 4:
        return False
    title = _selection_title_text(article, generated_fields)
    return bool(_CONFIRMED_USAGE_UPDATE.search(title) or _NO_USAGE_LIMIT.search(title))


def _is_arxiv_breakthrough(dimensions: ContentValueDimensions) -> bool:
    return (
        dimensions.impact >= ARXIV_MIN_IMPACT
        and dimensions.novelty >= ARXIV_MIN_NOVELTY
        and dimensions.substance >= ARXIV_MIN_SUBSTANCE
    )


def decide_featured_selection(
    *,
    article: RawArticle,
    source: Source,
    ai_focus: AIFocus,
    dimensions: ContentValueDimensions,
    category: str,
    generated_fields: dict[str, Any],
    final_score: float | None = None,
) -> SelectionDecision:
    """在不改动 AI 打分的前提下，只决定一篇已打分文章是否精选。"""
    if final_score is None:
        final_score = compute_final_score(dimensions, source.tier)

    if ai_focus not in SELECTABLE_AI_FOCUS:
        return SelectionDecision(
            selected=False,
            selection_origin="score",
            selection_reason=None,
            rejection_reason=f"ai_focus:{ai_focus}",
        )

    is_arxiv = source.id == ARXIV_SOURCE_ID or article.source_id == ARXIV_SOURCE_ID
    if is_arxiv:
        if ai_focus == "primary" and _is_arxiv_breakthrough(dimensions):
            return SelectionDecision(
                selected=True,
                selection_origin="policy",
                selection_reason="source_gate:arxiv_breakthrough",
                rejection_reason=None,
            )
        return SelectionDecision(
            selected=False,
            selection_origin="policy",
            selection_reason=None,
            rejection_reason="source_gate:arxiv_not_breakthrough",
        )

    if final_score >= VALUE_SCORE_THRESHOLD:
        return SelectionDecision(
            selected=True,
            selection_origin="score",
            selection_reason=f"final_score:{final_score}>=threshold:{VALUE_SCORE_THRESHOLD}",
            rejection_reason=None,
        )

    # 优先规则只在分数未过线时托底，过线文章仍保持原有 score 来源。
    if ai_focus == "primary" and _is_confirmed_model_release(
        article=article, category=category, generated_fields=generated_fields
    ):
        return SelectionDecision(
            selected=True,
            selection_origin="policy",
            selection_reason="priority:confirmed_model_release",
            rejection_reason=None,
        )

    if ai_focus == "primary" and _is_confirmed_usage_update(
        article=article,
        category=category,
        dimensions=dimensions,
        generated_fields=generated_fields,
    ):
        return SelectionDecision(
            selected=True,
            selection_origin="policy",
            selection_reason="priority:usage_limit_update",
            rejection_reason=None,
        )

    return SelectionDecision(
        selected=False,
        selection_origin="score",
        selection_reason=None,
        rejection_reason=f"final_score:{final_score}<threshold:{VALUE_SCORE_THRESHOLD}",
    )


def select_processed_article(
    *,
    article: RawArticle,
    source: Source,
    ai_focus: AIFocus,
    dimensions: ContentValueDimensions,
    category: str,
    tags: list[str],
    generated_fields: dict[str, Any],
    focus_category: str | None = None,
    model_used: str | None = None,
    topic_ids: list[str] | None = None,
) -> ProcessedArticle:
    final_score = compute_final_score(dimensions, source.tier)

    # 主题归属:AI 给了(含空列表)就用 AI 的;没给(旧缓存、离线兜底、
    # 模型漏字段)用关键词推导——保证新写入的行恒有值,读取层不用兜底
    if topic_ids is None:
        topic_ids = derive_topic_ids(
            {
                "title": generated_fields.get("title_zh", ""),
                "one_line_summary": generated_fields.get("one_line_summary", ""),
                "tags": tags,
            }
        )

    decision = decide_featured_selection(
        article=article,
        source=source,
        ai_focus=ai_focus,
        dimensions=dimensions,
        category=category,
        generated_fields=generated_fields,
        final_score=final_score,
    )

    return ProcessedArticle(
        raw_article_id=article.id,
        event_cluster_id=None,
        ai_focus=ai_focus,
        dimensions=dimensions,
        final_score=final_score,
        title_zh=generated_fields["title_zh"],
        one_line_summary=generated_fields["one_line_summary"],
        summary_zh=generated_fields["summary_zh"],
        reason_zh=generated_fields["reason_zh"],
        action_zh=generated_fields["action_zh"],
        category=category,
        tags=tags[:5],
        selected=decision.selected,
        status="processed" if decision.selected else "rejected",
        rejection_reason=decision.rejection_reason,
        selection_origin=decision.selection_origin,
        selection_reason=decision.selection_reason,
        focus_category=resolve_focus_category(
            focus_category,
            category,
            text=" ".join(
                [
                    article.title,
                    generated_fields.get("title_zh", ""),
                    generated_fields.get("one_line_summary", ""),
                    generated_fields.get("summary_zh", ""),
                    " ".join(tags),
                ]
            ),
        ),
        model_used=model_used,
        topic_ids=topic_ids,
    )
