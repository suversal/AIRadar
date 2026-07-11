from __future__ import annotations

import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.crawlers.article_content import extract_article_content
from app.crawlers.base import BaseCrawler, clean_text, fetch_url_text, normalize_article
from app.models.domain import RawArticle, Source


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", value))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw_value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
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


def parse_rss(xml_text: str, source: Source, limit: int | None = None) -> list[RawArticle]:
    root = ET.fromstring(xml_text)
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
        if source.id == "aihot_feed" or (source.config or {}).get(
            "original_url_from_description"
        ):
            link = _original_url_from_description(content_html) or link
        original_content = extract_article_content(content_html, base_url=link, title=title)
        content = original_content["original_text"] or strip_html(content_html)
        author = _entry_author(entry)
        published = _child_text(entry, ["pubDate", "published", "updated"])
        if not title or not link:
            continue
        metadata = {
            "source_type": "rss",
            "feed_category": _child_text(entry, ["category"]),
            "feed_position": position,
            "original_text": original_content["original_text"],
            "original_paragraphs": original_content["original_paragraphs"],
            "original_images": original_content["original_images"],
            "original_blocks": original_content["original_blocks"],
        }
        articles.append(
            normalize_article(
                source=source,
                source_url=link,
                title=title,
                content=strip_html(content),
                author=author,
                published_at=parse_datetime(published),
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
        xml_text = fetch_url_text(self.source.url)
        articles = parse_rss(xml_text, self.source, limit=limit)
        if (self.source.config or {}).get("use_feed_content_only"):
            return articles
        for article in articles:
            self._prefer_full_page(article)
        return articles

    def _prefer_full_page(self, article: RawArticle) -> None:
        from app.crawlers.page_content import prefer_full_page_content

        prefer_full_page_content(article, cache_dir=self.page_cache_dir)
