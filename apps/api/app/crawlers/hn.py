from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.crawlers.base import BaseCrawler, normalize_article
from app.models.domain import RawArticle, Source

DEFAULT_QUERY_TERMS = [
    "ai",
    "artificial intelligence",
    "llm",
    "openai",
    "anthropic",
    "agent",
    "machine learning",
    "deep learning",
    "neural",
    "model",
]


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip().lower()).replace(r"\ ", r"[\s_-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def _matches_query_terms(text: str, query_terms: list[str]) -> bool:
    normalized = text.lower()
    return any(_term_pattern(term).search(normalized) for term in query_terms if term.strip())


def _hit_text(hit: dict) -> str:
    return " ".join(
        str(value or "")
        for value in [
            hit.get("title"),
            hit.get("story_title"),
            hit.get("story_text"),
            hit.get("url"),
        ]
    )


def parse_hn_hits(
    hits: list[dict],
    source: Source,
    limit: int | None = None,
) -> list[RawArticle]:
    query_terms = source.config.get("query_terms") or DEFAULT_QUERY_TERMS
    # HN's own community signal is the quality bar: posts nobody upvoted or
    # discussed are (measured on real data 2026-07-11) mostly self-promo
    # landing pages or unreadable shells - not worth an AI scoring call.
    # Either signal clears the bar; both thresholds are per-source config.
    min_points = int(source.config.get("min_points", 5))
    min_comments = int(source.config.get("min_comments", 3))
    articles: list[RawArticle] = []
    for hit in hits:
        title = hit.get("title") or hit.get("story_title") or ""
        if not title:
            continue
        if query_terms and not _matches_query_terms(_hit_text(hit), query_terms):
            continue
        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        if points < min_points and comments < min_comments:
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        created_at = hit.get("created_at")
        published_at = (
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_at
            else datetime.now(timezone.utc)
        )
        articles.append(
            normalize_article(
                source=source,
                source_url=url,
                title=title,
                content=hit.get("story_text") or title,
                author=hit.get("author"),
                published_at=published_at,
                language="en",
                raw_score={
                    "points": hit.get("points") or 0,
                    "comments": hit.get("num_comments") or 0,
                },
                metadata={"hn_object_id": hit.get("objectID")},
            )
        )
        if limit is not None and len(articles) >= limit:
            break
    return articles


class HackerNewsCrawler(BaseCrawler):
    """HN's Algolia API only carries the submitted title and (for text
    posts) a story_text field that's empty for the common case of a post
    linking out to an external article - the real body always lives at
    that linked URL, same as an RSS feed's own lossy/empty description."""

    def __init__(self, source: Source, *, page_cache_dir: Path | None = None):
        super().__init__(source)
        self.page_cache_dir = page_cache_dir

    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        request = urllib.request.Request(
            self.source.url,
            headers={"User-Agent": "SuversalAIRadar/0.1 (+https://github.com/suversal/HotAI)"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hits = payload.get("hits", [])
        articles = parse_hn_hits(hits, self.source, limit=limit)
        for article in articles:
            self._prefer_full_page(article)
        return articles

    def _prefer_full_page(self, article: RawArticle) -> None:
        from app.crawlers.page_content import prefer_full_page_content

        prefer_full_page_content(article, cache_dir=self.page_cache_dir)
