from __future__ import annotations

import json
from datetime import datetime

from app.crawlers.base import BaseCrawler, fetch_url_text, normalize_article
from app.models.domain import RawArticle, Source

# Undocumented, unauthenticated third-party API (AttentionVC tracks viral X
# posts; endpoint found by inspecting their site's own frontend requests -
# not a stable public contract). Failure here is expected occasionally and
# is already absorbed by crawlers/run.py's per-source try/except, so this
# crawler does not need its own fallback.
#
# `window` must stay in the `Nd` form (e.g. 3d) - the `Nh` forms (24h/48h/72h)
# hit a stale cache on this endpoint and return data 2-3 weeks old.


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_english(entry: dict) -> bool:
    langs_detected = entry.get("langsDetected") or []
    if langs_detected:
        return "en" in langs_detected
    lang = entry.get("lang")
    return lang in ("en", "zxx")


def parse_attentionvc_entries(
    payload: dict,
    source: Source,
    limit: int | None = None,
) -> list[RawArticle]:
    entries = payload.get("entries") or []
    articles: list[RawArticle] = []
    for entry in entries:
        tweet_id = entry.get("tweetId")
        title = entry.get("title") or ""
        author = entry.get("author") or {}
        handle = author.get("handle")
        if not tweet_id or not title or not handle:
            continue
        if not _is_english(entry):
            continue
        articles.append(
            normalize_article(
                source=source,
                source_url=f"https://x.com/{handle}/status/{tweet_id}",
                title=title,
                content=entry.get("previewText") or title,
                author=f"@{handle}",
                published_at=_parse_published_at(entry.get("tweetCreatedAt")),
                language="en",
                raw_score={
                    "views": entry.get("viewCount") or 0,
                    "likes": entry.get("likeCount") or 0,
                    "retweets": entry.get("retweetCount") or 0,
                },
                metadata={"source_type": "attentionvc", "tweet_id": tweet_id},
            )
        )
        if limit is not None and len(articles) >= limit:
            break
    return articles


class AttentionVcCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        text = fetch_url_text(self.source.url, accept="application/json")
        payload = json.loads(text)
        return parse_attentionvc_entries(payload, self.source, limit=limit)
