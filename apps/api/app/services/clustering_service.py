from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.crawlers.base import stable_hash
from app.models.domain import EventCluster, RawArticle, Source
from app.services.x_tweet_articles import evidence_source_key


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
    "T1": 3,
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


def reference_keys_for_article(source_url: str | None, metadata: dict | None) -> set[str]:
    """Return every deterministic identity known for one article.

    Official/original feeds often place the canonical article directly in
    ``source_url`` and therefore have no redundant ``source_list`` block.
    Aggregators such as Telegram carry their own post URL in ``source_url``
    and cite the official article in ``original_blocks``. Considering both
    lets those two shapes meet on the same canonical key even when semantic
    embeddings are unavailable or cross-language similarity is conservative.
    """
    keys = reference_keys_from_metadata(metadata)
    source_key = canonical_reference_key(source_url)
    if source_key:
        keys.add(source_key)
    return keys


def article_reference_keys(article: RawArticle) -> set[str]:
    return reference_keys_for_article(article.source_url, article.metadata)


def event_match_document(article: RawArticle) -> dict[str, Any]:
    """Minimal provider-neutral document used by the second-stage verifier."""
    return {
        "id": article.id,
        "source": article.source_name,
        "published_at": article.published_at.isoformat(),
        "title": article.title,
        "content": article.content,
    }


def _fits_event_time_window(
    bucket: list[RawArticle],
    article: RawArticle,
    *,
    max_event_span_hours: float | None,
) -> bool:
    if max_event_span_hours is None:
        return True
    timestamps = [item.published_at for item in bucket]
    timestamps.append(article.published_at)
    span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600
    return span_hours <= max_event_span_hours


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def centroid(vectors: list[list[float]]) -> list[float]:
    """Component-wise mean of a bucket's member vectors."""
    if not vectors:
        return []
    width = len(vectors[0])
    usable = [vector for vector in vectors if len(vector) == width]
    if not usable:
        return []
    return [sum(values) / len(usable) for values in zip(*usable)]


#: Floor of the recall band: below this an article is not even a candidate for
#: a bucket, above it the same-event verifier decides.
#:
#: Cosine similarity cannot separate "same event" from "same kind of text" in
#: this corpus, so the band exists instead of a better threshold. Measured
#: 2026-08-03 on the live embeddings:
#:
#:   7 unrelated arXiv papers (AURORA-LM, UEmbed, a power-systems education
#:   paper, ...)             pairwise 0.860-0.928, mean 0.899
#:   8 reports of one event (阿里发布 Qwen3.8-Max)
#:                           pairwise 0.463-0.878, mean 0.703
#:
#: Unrelated papers score *higher* than genuine same-event coverage - arXiv
#: titles are near-identical in register, so the vector captures genre and
#: field rather than event identity. No threshold can satisfy both sets, which
#: is why vectors only ever recall candidates here and the verifier judges
#: them. 0.80 keeps recall affordable: on 2026-08-12, 97% of all candidate
#: pairs fell below it.
GRAY_ZONE_FLOOR = 0.80

#: How many recall-band buckets one article may be checked against. The
#: verifier costs an API call per bucket, so only the closest are asked.
GRAY_ZONE_CANDIDATE_LIMIT = 2

# X posts are often short English announcements while the already-selected
# event is represented by a Chinese media title.  The shared embedding model
# remains the primary recall path; this stricter text band only nominates a
# small number of recent X-related event pairs for the existing AI verifier.
# It never merges by itself and therefore does not loosen the vector gate.
X_TEXT_RECALL_FLOOR = 0.62
X_TEXT_RECALL_CANDIDATE_LIMIT = 2


def _normalized_event_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", normalized)


def _title_bigrams(value: str) -> set[str]:
    normalized = _normalized_event_title(value)
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _text_affinity(left_value: str, right_value: str) -> float:
    left = _normalized_event_title(left_value)
    right = _normalized_event_title(right_value)
    if not left or not right:
        return 0.0
    sequence_score = SequenceMatcher(None, left, right).ratio()
    left_bigrams = _title_bigrams(left)
    right_bigrams = _title_bigrams(right)
    union = left_bigrams | right_bigrams
    bigram_score = len(left_bigrams & right_bigrams) / len(union) if union else 0.0
    return max(sequence_score, bigram_score)


def event_text_affinity(
    left_title: str,
    right_title: str,
    *,
    left_summary: str = "",
    right_summary: str = "",
) -> float:
    """Cheap normalized-text recall score; AI verification remains mandatory."""
    title_score = _text_affinity(left_title, right_title)
    # Summaries are longer and naturally share more generic wording, so they
    # may recover a paraphrased title but receive a conservative discount.
    summary_score = _text_affinity(left_summary, right_summary) * 0.85
    return max(title_score, summary_score)


def bucket_affinity(vector: list[float], member_vectors: list[list[float]]) -> float | None:
    """Recall score of ``vector`` against a bucket, measured on its centroid.

    Only used to rank and shortlist recall-band candidates for the verifier,
    never to merge on its own. The centroid is the right shortlisting signal
    because complete-linkage (the merge gate below) gets progressively harsher
    as a bucket grows: every extra member adds another link that can fall below
    the bar, so the more coverage a real event accumulates the less likely its
    next report is to reach the gate. That is how 阿里发布 Qwen3.8-Max ended up
    as 8 separate events on 2026-08-03.
    """
    if not member_vectors:
        return None
    center = centroid(member_vectors)
    if not center:
        return None
    return cosine_similarity(vector, center)


def weakest_link(vector: list[float], member_vectors: list[list[float]]) -> float:
    """Complete-linkage score: similarity to the least similar bucket member."""
    if not member_vectors:
        return 0.0
    return min(cosine_similarity(vector, member) for member in member_vectors)


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
    max_event_span_hours: float | None = 24,
    same_event_verifier: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> list[EventCluster]:
    sources = sources or {}
    final_scores = final_scores or {}
    buckets: list[list[RawArticle]] = []
    # every member's vector, not just the founding one: membership is judged
    # against the bucket's centroid with a floor under the weakest individual
    # link (see bucket_affinity). Single-linkage against one fixed reference
    # vector would let unrelated articles chain in transitively (A~B and B~C
    # each clear the bar while A and C are unrelated); plain complete-linkage
    # blocks that but also caps how large a correct bucket can grow.
    bucket_vectors: list[list[list[float]]] = []
    bucket_similarities: list[dict[str, float]] = []
    bucket_reference_keys: list[set[str]] = []

    for article in sorted(articles, key=lambda item: item.published_at):
        vector = embeddings.get(article.id)
        reference_keys = article_reference_keys(article)
        reference_match = next(
            (
                index
                for index, (existing_keys, bucket) in enumerate(
                    zip(bucket_reference_keys, buckets)
                )
                if reference_keys
                and reference_keys.intersection(existing_keys)
                and _fits_event_time_window(
                    bucket,
                    article,
                    max_event_span_hours=max_event_span_hours,
                )
            ),
            None,
        )
        if vector is None:
            # Any successfully scored item must survive an embedding outage.
            # Keep it standalone unless an exact cited-source link proves the
            # event, so vector availability affects grouping but not display.
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
            member_vectors = bucket_vectors[matched_index]
            # an exact cited-source match already proves the event, so this is
            # only the similarity worth recording, never a gate
            center = centroid(member_vectors)
            matched_score = cosine_similarity(vector, center) if center else 1.0
        else:
            direct_matches: list[tuple[float, int]] = []
            gray_matches: list[tuple[float, int]] = []
            for index, member_vectors in enumerate(bucket_vectors):
                if not member_vectors:
                    continue
                if not _fits_event_time_window(
                    buckets[index],
                    article,
                    max_event_span_hours=max_event_span_hours,
                ):
                    continue
                # complete-linkage stays the gate for merging without asking the
                # verifier. Loosening it to the centroid was measured on
                # 2026-08-03 and merged 7 unrelated arXiv papers into one event:
                # in this corpus a loose vector rule buys mis-merges, not recall.
                gate = weakest_link(vector, member_vectors)
                if gate >= threshold:
                    direct_matches.append((gate, index))
                    continue
                if same_event_verifier is None:
                    continue
                recall = bucket_affinity(vector, member_vectors)
                if recall is not None and recall >= GRAY_ZONE_FLOOR:
                    gray_matches.append((recall, index))

            for score, index in sorted(direct_matches, reverse=True):
                if same_event_verifier is not None and not all(
                    same_event_verifier(
                        event_match_document(existing),
                        event_match_document(article),
                    )
                    for existing in buckets[index]
                ):
                    continue
                matched_index = index
                matched_score = score
                break

            if matched_index is None:
                # Below threshold the verifier is the entire judgement, so ask
                # it about the member most likely to be confirmed: if even the
                # closest report in the bucket is a different event, no other
                # member will be the same one. Without a verifier the band is
                # skipped outright - vector similarity already said it cannot
                # decide, and guessing here is what fragments real events.
                for score, index in sorted(gray_matches, reverse=True)[
                    :GRAY_ZONE_CANDIDATE_LIMIT
                ]:
                    closest = max(
                        buckets[index],
                        key=lambda member: cosine_similarity(
                            vector, embeddings.get(member.id) or []
                        ),
                    )
                    if not same_event_verifier(
                        event_match_document(closest),
                        event_match_document(article),
                    ):
                        continue
                    matched_index = index
                    matched_score = score
                    break
        if matched_index is None:
            buckets.append([article])
            bucket_vectors.append([vector])
            bucket_similarities.append({article.id: 1.0})
            bucket_reference_keys.append(reference_keys)
        else:
            buckets[matched_index].append(article)
            bucket_vectors[matched_index].append(vector)
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
                source_count=len(
                    {
                        evidence_source_key(article.source_id, article.metadata)
                        for article in bucket
                    }
                ),
                first_seen_at=first_seen,
                last_seen_at=last_seen,
                article_similarities=similarities,
            )
        )
    return clusters
