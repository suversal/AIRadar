from __future__ import annotations

import json
import re
from datetime import datetime

from app.crawlers.base import BaseCrawler, fetch_url_text, normalize_article
from app.models.domain import RawArticle, Source


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip().lower()).replace(r"\ ", r"[\s_-]+")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def _matches_query_terms(text: str, query_terms: list[str]) -> bool:
    normalized = text.lower()
    return any(_term_pattern(term).search(normalized) for term in query_terms if term.strip())


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_huggingface_papers(
    payload: list[dict],
    source: Source,
    limit: int | None = None,
) -> list[RawArticle]:
    query_terms = source.config.get("query_terms") or []
    articles: list[RawArticle] = []
    for entry in payload:
        paper = entry.get("paper") or entry
        paper_id = paper.get("id")
        title = paper.get("title") or ""
        if not paper_id or not title:
            continue
        summary = paper.get("summary") or ""
        if query_terms and not _matches_query_terms(f"{title} {summary}", query_terms):
            continue
        authors = paper.get("authors") or []
        author = ", ".join(a.get("name", "") for a in authors[:5] if a.get("name")) or None
        # submittedOnDailyAt (when HF surfaced it on the daily digest) is what
        # makes this "today's pick" - the original arXiv publishedAt is
        # routinely a few days older and would get dropped by the pipeline's
        # today-only filter, silently zeroing this source out most days
        published_at = _parse_published_at(paper.get("submittedOnDailyAt")) or _parse_published_at(
            paper.get("publishedAt")
        )
        articles.append(
            normalize_article(
                source=source,
                source_url=f"https://huggingface.co/papers/{paper_id}",
                title=title,
                content=summary or title,
                author=author,
                published_at=published_at,
                language="en",
                raw_score={
                    "upvotes": paper.get("upvotes") or 0,
                    "comments": entry.get("numComments") or 0,
                },
                metadata={"source_type": "huggingface_papers", "paper_id": paper_id},
            )
        )
        if limit is not None and len(articles) >= limit:
            break
    return articles


class HuggingFacePapersCrawler(BaseCrawler):
    """HuggingFace's community-curated daily papers feed - already filtered by
    upvotes/relevance, so unlike raw arXiv it's small enough to ingest in full
    by default (query_terms in source.config narrows it further if needed)."""

    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        text = fetch_url_text(self.source.url, accept="application/json")
        payload = json.loads(text)
        return parse_huggingface_papers(payload, self.source, limit=limit)
