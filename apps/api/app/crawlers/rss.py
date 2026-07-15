from __future__ import annotations

import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.crawlers.article_content import extract_article_content
from app.crawlers.base import BaseCrawler, clean_text, fetch_url_text, normalize_article
from app.models.domain import RawArticle, Source


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", value))


def _fixed_offset(value: str) -> timezone:
    sign = -1 if value.strip().startswith("-") else 1
    hours_str, _, minutes_str = value.strip().lstrip("+-").partition(":")
    return timezone(sign * timedelta(hours=int(hours_str), minutes=int(minutes_str or 0)))


def parse_datetime(value: str | None, *, assume_tz: str | None = None) -> datetime | None:
    if not value:
        return None
    raw_value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        # A few Chinese feeds (observed: 36Kr) emit an ISO-like value such as
        # ``2026-07-15 11:05:44  +0800``. Python 3.9's fromisoformat rejects
        # both the whitespace before the offset and the compact +HHMM form.
        iso_value = re.sub(r"\s+([+-]\d{2})(\d{2})$", r"\1:\2", raw_value)
        iso_value = re.sub(r"\s+([+-]\d{2}:\d{2})$", r"\1", iso_value)
        try:
            parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None:
        return None
    if assume_tz:
        # some feeds (observed: InfoQ 中文) label pubDate "GMT" but the
        # wall-clock numbers are actually local time - discard whatever
        # offset was parsed and reinterpret the same y/m/d/h/m/s under the
        # configured offset instead of trusting the feed's own label
        parsed = parsed.replace(tzinfo=_fixed_offset(assume_tz))
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _child_text(element: ET.Element, names: list[str]) -> str:
    for name in names:
        child = element.find(name)
        if child is not None:
            text = clean_text(" ".join(child.itertext()))
            if text:
                return text
    for name in names:
        for child in list(element):
            local_name = child.tag.split("}")[-1]
            if local_name != name:
                continue
            text = clean_text(" ".join(child.itertext()))
            if text:
                return text
    return ""


def _child_raw_text(element: ET.Element, names: list[str]) -> str:
    for name in names:
        child = element.find(name)
        if child is not None:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    for name in names:
        for child in list(element):
            local_name = child.tag.split("}")[-1]
            if local_name != name:
                continue
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _entry_link(element: ET.Element) -> str:
    direct = _child_text(element, ["link"])
    if direct:
        return direct
    first_href = ""
    for child in list(element):
        local_name = child.tag.split("}")[-1]
        if local_name == "link":
            href = child.attrib.get("href")
            rel = child.attrib.get("rel", "alternate")
            if href and rel == "alternate":
                return href
            if href:
                first_href = first_href or href
    return first_href


def _entry_author(element: ET.Element) -> str:
    creator = _child_text(element, ["creator"])
    if creator:
        return creator
    for child in list(element):
        if child.tag.split("}")[-1] != "author":
            continue
        name = _child_text(child, ["name"])
        if name:
            return name
        text = clean_text(" ".join(child.itertext()))
        if text:
            return text
    return ""


def _original_url_from_description(description: str) -> str:
    match = re.search(
        r"(?:🔗\s*)?阅读原文\s*[：:]\s*(https?://[^\s<>]+)",
        description,
        flags=re.IGNORECASE,
    )
    if match is None:
        return ""
    candidate = match.group(1).rstrip("，。；、")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


# AI HOT's own description already reads: "<AI 摘要>\n\n🔗 阅读原文：<url>\n\n
# via AI HOT · <permalink>" - everything from the "阅读原文" marker onward is
# boilerplate we generate ourselves elsewhere, only the summary paragraph
# itself is useful as summary_zh
_AIHOT_READ_ORIGINAL_MARKER_RE = re.compile(r"(?:🔗\s*)?阅读原文\s*[：:]")


def _truncate_at_aihot_marker(text: str) -> str:
    match = _AIHOT_READ_ORIGINAL_MARKER_RE.search(text)
    return text[: match.start()] if match else text


def _aihot_summary_from_description(description: str) -> str:
    text = strip_html(description)
    return clean_text(_truncate_at_aihot_marker(text))


# XML 1.0 disallows most C0 control chars; some feeds (e.g. Smol AI News,
# whose posts embed raw code snippets) leak them in raw and trip
# ElementTree's strict parser with "not well-formed (invalid token)".
_INVALID_XML_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def parse_rss(xml_text: str, source: Source, limit: int | None = None) -> list[RawArticle]:
    root = ET.fromstring(_INVALID_XML_CHARS_RE.sub("", xml_text))
    entries = root.findall(".//item")
    if not entries:
        entries = [node for node in root.iter() if node.tag.split("}")[-1] == "entry"]

    articles: list[RawArticle] = []
    for position, entry in enumerate(entries[:limit], start=1):
        title = _child_text(entry, ["title"])
        link = _entry_link(entry)
        content_html = (
            _child_raw_text(entry, ["description", "summary", "content"])
            or _child_raw_text(entry, ["encoded"])
        )
        config = source.config or {}
        # AI HOT's own item permalink (/items/{id}) already IS the feed's
        # native <link> - capture it before the "阅读原文" override below
        # replaces `link` with the third-party original URL, so the
        # dedicated aihot full-content fetch (page_content-equivalent) knows
        # where to go without re-deriving it
        aihot_permalink = link if config.get("use_aihot_item_page") else ""
        body_html = content_html
        if source.id == "aihot_feed" or config.get("original_url_from_description"):
            # _original_url_from_description needs the full text (the URL sits
            # right after the marker), so it must run before truncation; the
            # marker itself and everything after it is our own generated
            # link-out boilerplate, not article body - strip it before parsing
            # content so it never leaks into original_blocks/original_text.
            link = _original_url_from_description(content_html) or link
            body_html = _truncate_at_aihot_marker(content_html)
        original_content = extract_article_content(body_html, base_url=link, title=title)
        content = original_content["original_text"] or strip_html(body_html)
        author = _entry_author(entry)
        published = _child_text(entry, ["pubDate", "published", "updated"])
        parsed_published = parse_datetime(
            published, assume_tz=(source.config or {}).get("pubdate_assume_tz")
        )
        if not title or not link:
            continue
        metadata = {
            "source_type": "rss",
            "feed_category": _child_text(entry, ["category"]),
            "feed_position": position,
            "rss_pubdate_raw": published,
            "rss_pubdate_missing": parsed_published is None,
            "original_text": original_content["original_text"],
            "original_paragraphs": original_content["original_paragraphs"],
            "original_images": original_content["original_images"],
            "original_blocks": original_content["original_blocks"],
        }
        if config.get("original_url_from_description"):
            metadata["aihot_summary_zh"] = _aihot_summary_from_description(content_html)
        if aihot_permalink:
            metadata["aihot_permalink"] = aihot_permalink
        articles.append(
            normalize_article(
                source=source,
                source_url=link,
                title=title,
                content=strip_html(content),
                author=author,
                published_at=parsed_published,
                language=source.language,
                raw_score={},
                metadata=metadata,
            )
        )
    return articles


class RSSCrawler(BaseCrawler):
    """RSS only discovers articles; the body always comes from the real
    article page (RSS <description>/<summary> is frequently a lossy teaser,
    not real content). The feed's own text is kept only as a fallback for
    when the page fetch itself fails (blocked, network error, no
    extractable content region)."""

    def __init__(self, source: Source, *, page_cache_dir: Path | None = None):
        super().__init__(source)
        self.page_cache_dir = page_cache_dir

    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        # 只拉 feed 元数据。正文拉取延迟到 AI 预筛通过之后由 pipeline 执行
        # (2026-07-12 流程重排):非 AI 文章因此零外站请求
        use_curl = bool((self.source.config or {}).get("use_curl"))
        xml_text = fetch_url_text(self.source.url, use_curl=use_curl)
        articles = parse_rss(xml_text, self.source, limit=limit)
        if (self.source.config or {}).get("use_feed_content_only"):
            return articles
        for article in articles:
            article.metadata["body_fetch"] = "deferred"
        return articles
