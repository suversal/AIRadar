from __future__ import annotations

import math
from datetime import datetime

from app.models.domain import EventCluster, RawArticle, Source

ROLE_PRIORITY = {
    "authority": 4,
    "signal": 3,
    "context": 2,
    "aggregator": 1,
}

TIER_PRIORITY = {
    "T1": 4,
    "T1_5": 3,
    "T1.5": 3,
    "T2": 2,
    "T3": 1,
}


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def choose_main_article(
    articles: list[RawArticle],
    *,
    sources: dict[str, Source],
    final_scores: dict[str, float] | None = None,
) -> RawArticle:
    final_scores = final_scores or {}

    def sort_key(article: RawArticle) -> tuple[int, int, float, datetime, int]:
        source = sources.get(article.source_id)
        can_be_main = source.can_be_main_source if source else article.source_role != "aggregator"
        source_role = source.source_role if source else article.source_role
        tier = source.tier if source else article.source_tier
        return (
            1 if can_be_main else 0,
            ROLE_PRIORITY.get(source_role, 0),
            TIER_PRIORITY.get(tier, 0),
            final_scores.get(article.id, 0.0),
            article.published_at,
            len(article.content),
        )

    return max(articles, key=sort_key)


def cluster_articles(
    articles: list[RawArticle],
    embeddings: dict[str, list[float]],
    *,
    threshold: float = 0.85,
    sources: dict[str, Source] | None = None,
    final_scores: dict[str, float] | None = None,
) -> list[EventCluster]:
    sources = sources or {}
    final_scores = final_scores or {}
    buckets: list[list[RawArticle]] = []
    bucket_vectors: list[list[float]] = []

    for article in sorted(articles, key=lambda item: item.published_at):
        vector = embeddings.get(article.id)
        if vector is None:
            continue
        matched_index = None
        for index, bucket_vector in enumerate(bucket_vectors):
            if cosine_similarity(vector, bucket_vector) >= threshold:
                matched_index = index
                break
        if matched_index is None:
            buckets.append([article])
            bucket_vectors.append(vector)
        else:
            buckets[matched_index].append(article)

    clusters: list[EventCluster] = []
    for index, bucket in enumerate(buckets, start=1):
        main = choose_main_article(bucket, sources=sources, final_scores=final_scores)
        score = max(final_scores.get(article.id, 0.0) for article in bucket)
        first_seen = min(article.published_at for article in bucket)
        last_seen = max(article.published_at for article in bucket)
        clusters.append(
            EventCluster(
                id=f"c{index}",
                main_article_id=main.id,
                article_ids=[article.id for article in bucket],
                event_title=main.title,
                event_summary=main.content[:240],
                category="uncategorized",
                tags=[],
                final_score=score,
                source_count=len({article.source_id for article in bucket}),
                first_seen_at=first_seen,
                last_seen_at=last_seen,
            )
        )
    return clusters

