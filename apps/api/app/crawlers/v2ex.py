from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.crawlers.base import BaseCrawler, clean_text, fetch_url_text, normalize_article
from app.models.domain import RawArticle, Source


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip().lower()).replace(r"\ ", r"[\s_-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def _matches_query_terms(text: str, query_terms: list[str]) -> bool:
    normalized = text.lower()
    return any(_term_pattern(term).search(normalized) for term in query_terms if term.strip())


def parse_v2ex_topics(
    payload: list[dict],
    source: Source,
    limit: int | None = None,
) -> list[RawArticle]:
    query_terms = source.config.get("query_terms") or []
    min_replies = int(source.config.get("min_replies", 1))
    articles: list[RawArticle] = []
    for topic in payload:
        title = topic.get("title") or ""
        url = topic.get("url") or ""
        if not title or not url:
            continue
        replies = int(topic.get("replies") or 0)
        if replies < min_replies:
            continue
        content = clean_text(topic.get("content") or "") or title
        if query_terms and not _matches_query_terms(f"{title} {content}", query_terms):
            continue
        created = topic.get("created")
        published_at = (
            datetime.fromtimestamp(created, tz=timezone.utc) if created else None
        )
        member = topic.get("member") or {}
        node = topic.get("node") or {}
        articles.append(
            normalize_article(
                source=source,
                source_url=url,
                title=title,
                content=content,
                author=member.get("username"),
                published_at=published_at,
                language="zh",
                raw_score={"replies": replies},
                metadata={"source_type": "v2ex", "node": node.get("name")},
            )
        )
    # sort by reply count desc, closest available proxy for "hot" - must
    # happen before the limit slice, not during collection, or a limit
    # would just keep the first N in feed order instead of the top N
    articles.sort(key=lambda a: a.raw_score.get("replies", 0), reverse=True)
    return articles[:limit] if limit is not None else articles


class V2exCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        # v2ex.com's API has been observed to lag past fetch_url_text's
        # 10s default under its own rate limiting; give it more room
        text = fetch_url_text(self.source.url, accept="application/json", timeout=20)
        payload = json.loads(text)
        return parse_v2ex_topics(payload, self.source, limit=limit)
