from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.domain import ProcessedArticle, RawArticle, ScoreDimensions, Source
from app.services.taxonomy import resolve_focus_category

BASE_SCORE_WEIGHTS = {
    "ai_relevance": 0.25,
    "novelty": 0.20,
    "impact": 0.20,
    "information_density": 0.15,
    "actionability": 0.10,
    "creator_value": 0.10,
}

SOURCE_TIER_WEIGHTS = {
    "T1": 1.20,
    "T1_5": 1.10,
    "T1.5": 1.10,
    "T2": 1.00,
    "T3": 0.85,
}

CATEGORY_THRESHOLDS = {
    "model_release": 65,
    "product_release": 68,
    "open_source": 70,
    "research": 75,
    "industry": 70,
    "funding": 72,
    "opinion": 78,
    "tutorial": 72,
}


def _clamp_score(value: float) -> float:
    return max(0.0, min(10.0, float(value)))


def compute_base_score(dimensions: ScoreDimensions) -> float:
    return round(
        _clamp_score(dimensions.ai_relevance) * BASE_SCORE_WEIGHTS["ai_relevance"]
        + _clamp_score(dimensions.novelty) * BASE_SCORE_WEIGHTS["novelty"]
        + _clamp_score(dimensions.impact) * BASE_SCORE_WEIGHTS["impact"]
        + _clamp_score(dimensions.information_density)
        * BASE_SCORE_WEIGHTS["information_density"]
        + _clamp_score(dimensions.actionability) * BASE_SCORE_WEIGHTS["actionability"]
        + _clamp_score(dimensions.creator_value) * BASE_SCORE_WEIGHTS["creator_value"],
        4,
    )


def category_threshold(category: str) -> int:
    return CATEGORY_THRESHOLDS.get(category, 70)


def freshness_weight(published_at: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600)
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.9
    if age_hours <= 168:
        return 0.75
    return 0.6


def category_weight(category: str) -> float:
    if category == "model_release":
        return 1.05
    if category in {"opinion", "funding"}:
        return 0.95
    return 1.0


def community_heat_bonus(source_count: int) -> float:
    if source_count >= 5:
        return 1.12
    if source_count >= 3:
        return 1.08
    if source_count >= 2:
        return 1.04
    return 1.0


def compute_final_score(
    *,
    base_score: float,
    source_tier: str,
    category: str,
    published_at: datetime,
    now: datetime | None = None,
    source_count: int = 1,
    is_duplicate: bool = False,
) -> float:
    event_penalty = 0.92 if is_duplicate else 1.0
    authority_bonus = 1.03 if source_tier in {"T1", "T1_5", "T1.5"} else 1.0
    score = (
        base_score
        * 10
        * SOURCE_TIER_WEIGHTS.get(source_tier, 1.0)
        * freshness_weight(published_at, now)
        * event_penalty
        * category_weight(category)
        * authority_bonus
        * community_heat_bonus(source_count)
    )
    return round(min(score, 100.0), 2)


def select_processed_article(
    *,
    article: RawArticle,
    source: Source,
    dimensions: ScoreDimensions,
    category: str,
    tags: list[str],
    generated_fields: dict[str, Any],
    now: datetime | None = None,
    source_count: int = 1,
    is_duplicate: bool = False,
    focus_category: str | None = None,
) -> ProcessedArticle:
    base_score = compute_base_score(dimensions)
    final_score = compute_final_score(
        base_score=base_score,
        source_tier=source.tier,
        category=category,
        published_at=article.published_at,
        now=now,
        source_count=source_count,
        is_duplicate=is_duplicate,
    )
    threshold = category_threshold(category)
    selected = final_score >= threshold
    return ProcessedArticle(
        raw_article_id=article.id,
        event_cluster_id=None,
        dimensions=dimensions,
        base_score=base_score,
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
        rejection_reason=None if selected else f"below_threshold:{threshold}",
        selection_origin="score",
        selection_reason=(
            f"final_score:{final_score}>=threshold:{threshold}" if selected else None
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
