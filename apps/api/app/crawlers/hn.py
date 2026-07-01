from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

from app.crawlers.base import BaseCrawler, normalize_article
from app.models.domain import RawArticle


class HackerNewsCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        with urllib.request.urlopen(self.source.url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hits = payload.get("hits", [])
        articles: list[RawArticle] = []
        for hit in hits[:limit]:
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            created_at = hit.get("created_at")
            published_at = (
                datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created_at
                else datetime.now(timezone.utc)
            )
            title = hit.get("title") or hit.get("story_title") or ""
            if not title:
                continue
            articles.append(
                normalize_article(
                    source=self.source,
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
        return articles

