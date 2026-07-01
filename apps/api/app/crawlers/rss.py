from __future__ import annotations

import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from app.crawlers.base import BaseCrawler, clean_text, normalize_article
from app.models.domain import RawArticle, Source


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", value))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _child_text(element: ET.Element, names: list[str]) -> str:
    for name in names:
        child = element.find(name)
        if child is not None and child.text:
            return child.text
    for child in list(element):
        local_name = child.tag.split("}")[-1]
        if local_name in names and child.text:
            return child.text
    return ""


def _entry_link(element: ET.Element) -> str:
    direct = _child_text(element, ["link"])
    if direct:
        return direct
    for child in list(element):
        local_name = child.tag.split("}")[-1]
        if local_name == "link":
            href = child.attrib.get("href")
            if href:
                return href
    return ""


def parse_rss(xml_text: str, source: Source, limit: int | None = None) -> list[RawArticle]:
    root = ET.fromstring(xml_text)
    entries = root.findall(".//item")
    if not entries:
        entries = [node for node in root.iter() if node.tag.split("}")[-1] == "entry"]

    articles: list[RawArticle] = []
    for entry in entries[:limit]:
        title = _child_text(entry, ["title"])
        link = _entry_link(entry)
        content = (
            _child_text(entry, ["description", "summary", "content"])
            or _child_text(entry, ["encoded"])
        )
        author = _child_text(entry, ["author", "creator"])
        published = _child_text(entry, ["pubDate", "published", "updated"])
        if not title or not link:
            continue
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
                metadata={"source_type": "rss"},
            )
        )
    return articles


class RSSCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        with urllib.request.urlopen(self.source.url, timeout=20) as response:
            xml_text = response.read().decode("utf-8", errors="replace")
        return parse_rss(xml_text, self.source, limit=limit)

