"""Convert eligible SourcePilot X mirrors into ordinary pipeline articles.

SourcePilot remains the only network ingestion boundary.  This module reads
rows already mirrored in ``x_tweets`` and gives the existing article pipeline
the ``RawArticle`` shape it understands; it never fetches X or SourcePilot.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from app.crawlers.base import normalize_article, stable_hash
from app.models.domain import RawArticle, Source


X_TWEET_ACCOUNT_SOURCE_ID = "x_tweet_account"
X_TWEET_TOPIC_SOURCE_ID = "x_tweet_topic"
X_TWEET_SOURCE_IDS = frozenset({X_TWEET_ACCOUNT_SOURCE_ID, X_TWEET_TOPIC_SOURCE_ID})
X_TWEET_PIPELINE_TOPIC = "AI热点"

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+[^)]*)?\)")
_MARKDOWN_VIDEO_RE = re.compile(
    r"\[!\[([^\]]*)\]\((https?://[^)\s]+)\)\]\((https?://[^)\s]+)\)"
)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)(?:\s+[^)]*)?\)")
_MARKDOWN_MARKER_RE = re.compile(r"[*_`~]+")
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)$", re.DOTALL)


def _normalized_handle(value: object) -> str:
    return str(value or "").strip().lstrip("@").lower()


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def pipeline_source_id_for_tweet(
    tweet: dict[str, Any], subscribed_handles: set[str] | frozenset[str]
) -> str | None:
    """Return the internal provenance bucket for a V1-eligible original."""
    if str(tweet.get("tweet_type") or "original").lower() != "original":
        return None
    handle = _normalized_handle(tweet.get("author_handle"))
    if not handle:
        return None
    normalized_subscriptions = {_normalized_handle(value) for value in subscribed_handles}
    if handle in normalized_subscriptions:
        return X_TWEET_ACCOUNT_SOURCE_ID
    topics = {str(value).strip() for value in (tweet.get("topics") or [])}
    if X_TWEET_PIPELINE_TOPIC in topics:
        return X_TWEET_TOPIC_SOURCE_ID
    return None


def eligible_tweet_ids(
    tweets: list[dict[str, Any]], subscribed_handles: set[str] | frozenset[str]
) -> set[str]:
    return {
        str(tweet.get("tweet_id"))
        for tweet in tweets
        if tweet.get("tweet_id")
        and pipeline_source_id_for_tweet(tweet, subscribed_handles) is not None
    }


def tweet_content_hash(tweet: dict[str, Any]) -> str:
    """Hash semantic content, deliberately excluding changing engagement."""
    media = [
        {
            key: item.get(key)
            for key in ("type", "url", "width", "height")
            if item.get(key) is not None
        }
        for item in (tweet.get("media") or [])
        if isinstance(item, dict)
    ]
    basis = {
        "article_markdown": tweet.get("article_markdown") or "",
        "article_cover": tweet.get("article_cover") or "",
        "article_title": tweet.get("article_title") or "",
        "display_text": tweet.get("display_text") or "",
        "display_title": tweet.get("display_title") or "",
        "external_urls": [str(value) for value in (tweet.get("external_urls") or [])],
        "media": media,
    }
    encoded = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evidence_source_key(source_id: str, metadata: dict[str, Any] | None) -> str:
    metadata = metadata or {}
    if source_id in X_TWEET_SOURCE_IDS or metadata.get("source_type") == "x_tweet":
        handle = _normalized_handle(metadata.get("x_author_handle"))
        if handle:
            return f"x:@{handle}"
    return source_id


def display_source_name(source_name: str, metadata: dict[str, Any] | None) -> str:
    metadata = metadata or {}
    if metadata.get("source_type") == "x_tweet":
        handle = _normalized_handle(metadata.get("x_author_handle"))
        if handle:
            return f"@{handle}"
    return source_name


def display_source_profile(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return optional public author identity fields for an X-backed source."""
    metadata = metadata or {}
    if metadata.get("source_type") != "x_tweet":
        return {}
    handle = _normalized_handle(metadata.get("x_author_handle"))
    if not handle:
        return {}
    display_name = str(metadata.get("x_author_name") or "").strip() or f"@{handle}"
    avatar_url = str(metadata.get("x_author_avatar") or "").strip()
    return {
        "display_name": display_name,
        "handle": f"@{handle}",
        **({"avatar_url": avatar_url} if avatar_url else {}),
    }


def _plain_markdown(value: str) -> str:
    value = _MARKDOWN_IMAGE_RE.sub(lambda match: match.group(1), value)
    value = _MARKDOWN_LINK_RE.sub(lambda match: match.group(1), value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = _MARKDOWN_MARKER_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def _text_blocks(markdown: str) -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n", markdown):
        chunk = chunk.strip()
        if not chunk:
            continue
        # SP already weaves media into display_text/article_markdown. Parse
        # those markers instead of rendering payload.media a second time.
        media_blocks: list[dict[str, Any]] = []

        def capture_video(match: re.Match[str]) -> str:
            media_blocks.append(
                {
                    "type": "video",
                    "provider": "link",
                    "url": match.group(3),
                    "poster_url": match.group(2),
                    "title": match.group(1),
                }
            )
            return " "

        def capture_image(match: re.Match[str]) -> str:
            media_blocks.append(
                {"type": "image", "url": match.group(2), "alt": match.group(1)}
            )
            return " "

        without_media = _MARKDOWN_VIDEO_RE.sub(capture_video, chunk)
        without_media = _MARKDOWN_IMAGE_RE.sub(capture_image, without_media).strip()
        if not without_media:
            blocks.extend(media_blocks)
            continue
        heading = _HEADING_RE.match(without_media)
        if heading:
            text = _plain_markdown(heading.group(2))
            if text:
                blocks.append(
                    {
                        "type": "heading",
                        "level": min(len(heading.group(1)), 6),
                        "text": text,
                        "html": heading.group(2).strip(),
                    }
                )
                paragraphs.append(text)
            blocks.extend(media_blocks)
            continue
        text = _plain_markdown(without_media)
        if not text:
            blocks.extend(media_blocks)
            continue
        blocks.append({"type": "paragraph", "text": text, "html": without_media})
        paragraphs.append(text)
        blocks.extend(media_blocks)
    return blocks, paragraphs


def _source_list_block(tweet: dict[str, Any]) -> dict[str, Any] | None:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in tweet.get("external_urls") or []:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        host = (urlparse(url).hostname or "").lower()
        links.append({"label": host or url, "url": url, "host": host})
    return {"type": "source_list", "links": links} if links else None


def _tweet_url(tweet: dict[str, Any]) -> str:
    explicit = str(tweet.get("url") or "").strip()
    if explicit:
        return explicit
    handle = _normalized_handle(tweet.get("author_handle")) or "i"
    return f"https://x.com/{handle}/status/{tweet['tweet_id']}"


def _tweet_title(tweet: dict[str, Any], markdown: str) -> str:
    for value in (tweet.get("article_title"), tweet.get("display_title")):
        title = _plain_markdown(str(value or ""))
        if title:
            return title[:240]
    for line in markdown.splitlines():
        title = _plain_markdown(line)
        if title:
            return title[:160]
    handle = _normalized_handle(tweet.get("author_handle")) or "X 用户"
    return f"@{handle} 发布了一条 AI 动态"


def tweet_to_raw_article(tweet: dict[str, Any], source: Source) -> RawArticle:
    """Convert one already-qualified original tweet without network access."""
    tweet_id = str(tweet.get("tweet_id") or "").strip()
    handle = _normalized_handle(tweet.get("author_handle"))
    if not tweet_id or not handle:
        raise ValueError("tweet_id and author_handle are required")
    if str(tweet.get("tweet_type") or "original").lower() != "original":
        raise ValueError("only original tweets enter the article pipeline")

    markdown = str(tweet.get("article_markdown") or tweet.get("display_text") or "").strip()
    if not markdown:
        raise ValueError("tweet has no displayable content")
    text_blocks, paragraphs = _text_blocks(markdown)
    tweet_url = _tweet_url(tweet)
    source_list = _source_list_block(tweet)
    blocks = list(text_blocks)
    if source_list:
        blocks.append(source_list)
    images = [
        {key: value for key, value in block.items() if key != "type"}
        for block in text_blocks
        if block.get("type") == "image"
    ]
    content = "\n\n".join(paragraphs).strip() or _plain_markdown(markdown)

    metadata: dict[str, Any] = {
        "source_type": "x_tweet",
        "content_origin": "x_tweet",
        "x_tweet_id": tweet_id,
        "x_author_handle": handle,
        "x_author_name": str(tweet.get("author_name") or "").strip() or f"@{handle}",
        "x_author_avatar": str(tweet.get("author_avatar") or "").strip(),
        "x_content_hash": tweet_content_hash(tweet),
        "original_text": content,
        "original_paragraphs": paragraphs,
        "original_blocks": blocks,
        "original_images": images,
    }

    translation = tweet.get("translation") or {}
    translated_markdown = str(translation.get("display_text_zh") or "").strip()
    if translated_markdown:
        translated_text_blocks, translated_paragraphs = _text_blocks(translated_markdown)
        original_text_blocks = [
            block for block in text_blocks if block.get("type") in {"paragraph", "heading"}
        ]
        if translated_paragraphs and len(translated_paragraphs) == len(original_text_blocks):
            translated_blocks = list(translated_text_blocks)
            if source_list:
                translated_blocks.append(source_list)
            metadata.update(
                {
                    "translated_paragraphs": translated_paragraphs,
                    "translated_blocks": translated_blocks,
                    "translation_source_language": tweet.get("lang") or source.language,
                    "translation_target_language": "zh",
                    "translation_source_hash": stable_hash("\n".join(paragraphs))[:16],
                }
            )

    return normalize_article(
        source=source,
        source_url=tweet_url,
        title=_tweet_title(tweet, markdown),
        content=content,
        author=f"@{handle}",
        published_at=_parse_datetime(tweet.get("created_at")),
        language=str(tweet.get("lang") or source.language),
        raw_score={
            "likes": tweet.get("likes"),
            "retweets": tweet.get("retweets"),
            "replies": tweet.get("replies"),
            "views": tweet.get("views"),
        },
        metadata=metadata,
    )


def load_x_tweet_articles(
    repository: Any,
    sources: list[Source],
    *,
    now: datetime,
    recent_days: int = 7,
    limit: int = 100,
) -> tuple[list[RawArticle], dict[str, Any]]:
    """Read recent eligible mirrors and convert each independently."""
    source_by_id = {source.id: source for source in sources}
    missing = X_TWEET_SOURCE_IDS.difference(source_by_id)
    if missing:
        raise RuntimeError(f"missing internal X sources: {sorted(missing)}")
    rows = repository.x_tweets_for_article_pipeline(
        since=now - timedelta(days=max(1, recent_days)),
        limit=max(1, limit),
    )
    articles: list[RawArticle] = []
    report: dict[str, Any] = {
        "candidates": len(rows),
        "converted": 0,
        "failed": 0,
        "by_source": {X_TWEET_ACCOUNT_SOURCE_ID: 0, X_TWEET_TOPIC_SOURCE_ID: 0},
        "errors": [],
    }
    for tweet in rows:
        # Provenance is chosen once, when the row first becomes eligible.
        source_id = str(tweet.get("article_pipeline_source_id") or "")
        if source_id not in X_TWEET_SOURCE_IDS:
            report["failed"] += 1
            report["errors"].append(f"{tweet.get('tweet_id')}: missing pipeline source")
            continue
        try:
            articles.append(tweet_to_raw_article(tweet, source_by_id[source_id]))
        except Exception as exc:
            report["failed"] += 1
            if len(report["errors"]) < 10:
                report["errors"].append(f"{tweet.get('tweet_id')}: {exc}")
            continue
        report["converted"] += 1
        report["by_source"][source_id] += 1
    return articles, report
