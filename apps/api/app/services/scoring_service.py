from __future__ import annotations

from typing import Any

from app.models.domain import AIFocus, ContentValueDimensions, ProcessedArticle, RawArticle, Source
from app.services.taxonomy import resolve_focus_category

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

# 统一门槛，不再按8个内容类目各自设不同阈值——"多少分算精选"只取决于内容
# 本身的价值，跟它被分到哪个category无关。
VALUE_SCORE_THRESHOLD = 60.0

# 只有这两个分类才会进入value_score的计算与入选判断；tangential(AI只是顺带
# 提及)在分类层就直接淘汰，不再往下算分。
SELECTABLE_AI_FOCUS: frozenset[str] = frozenset({"primary", "contributing"})


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
) -> ProcessedArticle:
    final_score = compute_final_score(dimensions, source.tier)

    is_ai_content = ai_focus in SELECTABLE_AI_FOCUS
    meets_value_bar = final_score >= VALUE_SCORE_THRESHOLD
    selected = is_ai_content and meets_value_bar

    if not is_ai_content:
        rejection_reason = f"ai_focus:{ai_focus}"
    elif not meets_value_bar:
        rejection_reason = f"final_score:{final_score}<threshold:{VALUE_SCORE_THRESHOLD}"
    else:
        rejection_reason = None

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
        selected=selected,
        status="processed" if selected else "rejected",
        rejection_reason=rejection_reason,
        selection_origin="score",
        selection_reason=(
            f"final_score:{final_score}>=threshold:{VALUE_SCORE_THRESHOLD}" if selected else None
        ),
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
    )
