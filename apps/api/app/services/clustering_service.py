from __future__ import annotations

import math
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.crawlers.base import stable_hash
from app.models.domain import EventCluster, RawArticle, Source


def stable_cluster_id(main_article_id: str) -> str:
    """Content-derived cluster id so events keep their identity across runs."""
    return f"e{stable_hash(main_article_id)[:12]}"

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

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "spm",
}
_X_STATUS_HOSTS = {
    "mobile.twitter.com",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
}


def canonical_reference_key(url: str | None) -> str | None:
    """Return a conservative identity key for an article's cited source.

    Exact source links are stronger same-event evidence than a fuzzy vector.
    Root/homepage links are deliberately ignored because many unrelated news
    items cite the same publisher homepage. X/Twitter status aliases collapse
    to the numeric status id, so ``x.com/i/status/…`` and a username URL match.
    """
    if not url:
        return None
    try:
        parsed = urlsplit(str(url).strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if host in _X_STATUS_HOSTS:
        for index, part in enumerate(path_parts[:-1]):
            if part.lower() == "status" and path_parts[index + 1].isdigit():
                return f"x-status:{path_parts[index + 1]}"
    normalized_path = parsed.path.rstrip("/")
    if not normalized_path:
        return None
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY_KEYS
        )
    )
    return f"url:{host}{normalized_path}{'?' + query if query else ''}"


def reference_keys_from_metadata(metadata: dict | None) -> set[str]:
    """Extract strong cited-source identities from semantic article blocks."""
    keys: set[str] = set()
    for block in (metadata or {}).get("original_blocks") or []:
        if not isinstance(block, dict) or block.get("type") != "source_list":
            continue
        for link in block.get("links") or []:
            if not isinstance(link, dict):
                continue
            key = canonical_reference_key(link.get("url"))
            if key:
                keys.add(key)
    return keys


def article_reference_keys(article: RawArticle) -> set[str]:
    return reference_keys_from_metadata(article.metadata)


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
    bucket_similarities: list[dict[str, float]] = []
    bucket_reference_keys: list[set[str]] = []

    for article in sorted(articles, key=lambda item: item.published_at):
        vector = embeddings.get(article.id)
        reference_keys = article_reference_keys(article)
        reference_match = next(
            (
                index
                for index, existing_keys in enumerate(bucket_reference_keys)
                if reference_keys and reference_keys.intersection(existing_keys)
            ),
            None,
        )
        if vector is None:
            # A trusted curated item must survive an embedding outage. Keep it
            # standalone unless an exact cited-source link proves the event.
            if reference_match is None:
                buckets.append([article])
                bucket_vectors.append([])
                bucket_similarities.append({})
                bucket_reference_keys.append(reference_keys)
            else:
                buckets[reference_match].append(article)
                bucket_reference_keys[reference_match].update(reference_keys)
            continue
        matched_index = reference_match
        matched_score = 0.0
        if matched_index is not None:
            matched_score = cosine_similarity(vector, bucket_vectors[matched_index])
            if not bucket_vectors[matched_index]:
                bucket_vectors[matched_index] = vector
        else:
            for index, bucket_vector in enumerate(bucket_vectors):
                score = cosine_similarity(vector, bucket_vector)
                if score >= threshold:
                    matched_index = index
                    matched_score = score
                    break
        if matched_index is None:
            buckets.append([article])
            bucket_vectors.append(vector)
            bucket_similarities.append({article.id: 1.0})
            bucket_reference_keys.append(reference_keys)
        else:
            buckets[matched_index].append(article)
            bucket_similarities[matched_index][article.id] = matched_score
            bucket_reference_keys[matched_index].update(reference_keys)

    clusters: list[EventCluster] = []
    for bucket, similarities in zip(buckets, bucket_similarities):
        main = choose_main_article(bucket, sources=sources, final_scores=final_scores)
        score = max(final_scores.get(article.id, 0.0) for article in bucket)
        first_seen = min(article.published_at for article in bucket)
        last_seen = max(article.published_at for article in bucket)
        clusters.append(
            EventCluster(
                id=stable_cluster_id(main.id),
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
                article_similarities=similarities,
            )
        )
    return clusters
