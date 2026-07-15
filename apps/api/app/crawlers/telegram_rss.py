from __future__ import annotations

import html as html_module
import logging
import math
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from app.crawlers.base import BaseCrawler, clean_text, fetch_url_text, normalize_article
from app.crawlers.rss import (
    _INVALID_XML_CHARS_RE,
    _child_raw_text,
    _child_text,
    _entry_author,
    _entry_link,
    parse_datetime,
)
from app.models.domain import RawArticle, Source


LOGGER = logging.getLogger(__name__)

DEFAULT_RSSHUB_INSTANCES = (
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://hub.slarker.me",
    "https://rsshub.pseudoyu.com",
    "https://rsshub.rss.tips",
    "https://rsshub.ktachibana.party",
    "https://rss.owo.nz",
    "https://rss.wudifeixue.com",
    "https://rss.littlebaby.life/rsshub",
    "https://rsshub.henry.wang",
    "https://holoxx.f5.si",
    "https://rsshub.umzzz.com",
    "https://rsshub.isrss.com",
    "https://rsshub.email-once.com",
    "https://rss.datuan.dev",
    "https://rss.4040940.xyz",
    "https://rsshub.cups.moe",
    "https://rss.spriple.org",
    "https://rsshub-balancer.virworks.moe",
)

MAX_BLOCKS = 120
MAX_IMAGES = 30
MAX_QUOTE_DEPTH = 4
SAFE_INLINE_TAGS = {"strong", "b", "em", "i", "code"}
TRANSPARENT_INLINE_TAGS = {"tg-emoji"}
SKIP_TAGS = {"script", "style", "noscript", "iframe", "object"}
VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source"}
BLOCK_CONTAINER_TAGS = {"p", "div", "section", "article", "li"}
TELEGRAM_LINK_HOSTS = {"t.me", "telegram.me"}
_UPDATE_PREFIX_RE = re.compile(r"^(?:update\s*\d*|更新\s*\d*)\s*[：:]?", re.IGNORECASE)
_SOURCE_PREFIX_RE = re.compile(r"^(?:来源|source)\s*[：:]|^[—–-]{1,3}\s*", re.IGNORECASE)
_SAFE_COLOR_RE = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\)|"
    r"red|orange|yellow|green|blue|purple|black|white|gray|grey|pink|brown|"
    r"cyan|magenta|gold|navy|teal|maroon|olive|silver|crimson|indigo|violet|"
    r"coral|salmon|khaki|orchid|tomato|chocolate|tan)$",
    re.IGNORECASE,
)
_STYLE_COLOR_RE = re.compile(r"color\s*:\s*([^;]+)", re.IGNORECASE)


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[str | "_HtmlNode"] = field(default_factory=list)


class _HtmlTreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("root")
        self.stack = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        node = _HtmlNode(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.stack[-1].children.append(data)


def _safe_http_url(value: str | None, *, base_url: str = "") -> str:
    if not value:
        return ""
    candidate = urljoin(base_url, value.strip())
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "").lower().removeprefix("www.")


def _is_telegram_link(value: str) -> bool:
    host = _host(value)
    return host in TELEGRAM_LINK_HOSTS or any(
        host.endswith(f".{candidate}") for candidate in TELEGRAM_LINK_HOSTS
    )


def _is_article_source(value: str) -> bool:
    host = _host(value)
    return bool(host) and not _is_telegram_link(value) and not (
        host == "telesco.pe" or host.endswith(".telesco.pe")
    )


def _visible_text(value: str | _HtmlNode) -> str:
    if isinstance(value, str):
        return value
    if value.tag == "br":
        return "\n"
    if value.tag == "img":
        return ""
    return "".join(_visible_text(child) for child in value.children)


def _safe_color(attrs: dict[str, str | None]) -> str:
    style = attrs.get("style") or ""
    raw = attrs.get("color") or ((_STYLE_COLOR_RE.search(style) or [None, ""])[1])
    candidate = str(raw or "").strip().strip(";")
    return candidate if candidate and _SAFE_COLOR_RE.fullmatch(candidate) else ""


class TelegramDescriptionParser:
    def __init__(self, *, base_url: str, title: str) -> None:
        self.base_url = base_url
        self.title = title
        self._image_count = 0

    def parse(self, html_text: str) -> dict[str, Any]:
        tree = _HtmlTreeParser()
        tree.feed(html_text or "")
        tree.close()
        blocks = self._parse_sequence(tree.root.children, depth=0)
        blocks = self._remove_duplicate_title(blocks)
        blocks = self._organize_top_level(blocks)
        total_blocks = self._count_blocks(blocks)
        if total_blocks > MAX_BLOCKS:
            LOGGER.warning(
                "Telegram description exceeded %s blocks for %s; truncating %s blocks",
                MAX_BLOCKS,
                self.base_url,
                total_blocks - MAX_BLOCKS,
            )
            blocks = self._limit_blocks(blocks, [MAX_BLOCKS])
        paragraphs = self._plain_paragraphs(blocks)
        images = self._collect_images(blocks)
        return {
            "original_text": "\n\n".join(paragraphs),
            "original_paragraphs": paragraphs,
            "original_images": images,
            "original_blocks": blocks,
        }

    def _parse_sequence(
        self, values: list[str | _HtmlNode], *, depth: int
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        segment: list[str | _HtmlNode] = []
        br_count = 0

        def flush_segment() -> None:
            nonlocal segment
            block = self._segment_block(segment)
            segment = []
            if block:
                blocks.append(block)

        def flush_breaks() -> None:
            nonlocal br_count
            if br_count >= 2:
                flush_segment()
            elif br_count == 1 and segment:
                segment.append(" ")
            br_count = 0

        for value in values:
            if isinstance(value, _HtmlNode) and value.tag == "br":
                br_count += 1
                continue
            flush_breaks()
            if not isinstance(value, _HtmlNode):
                segment.append(value)
                continue
            classes = set((value.attrs.get("class") or "").split())
            if value.tag == "div" and "rsshub-quote" in classes:
                flush_segment()
                quote_node = self._first_descendant(value, "blockquote")
                if quote_node is not None:
                    blocks.append(self._quote_block(quote_node, kind="reply", depth=depth))
                continue
            if value.tag == "blockquote":
                flush_segment()
                text = clean_text(_visible_text(value))
                kind = "update" if _UPDATE_PREFIX_RE.match(text) else "quote"
                blocks.append(self._quote_block(value, kind=kind, depth=depth))
                continue
            if value.tag == "img":
                flush_segment()
                block = self._image_block(value)
                if block:
                    blocks.append(block)
                continue
            if value.tag in BLOCK_CONTAINER_TAGS or re.fullmatch(r"h[1-6]", value.tag):
                flush_segment()
                nested = self._parse_sequence(value.children, depth=depth)
                if re.fullmatch(r"h[1-6]", value.tag) and nested:
                    first = nested[0]
                    if first.get("type") == "paragraph":
                        first = dict(first)
                        first["type"] = "heading"
                        first["level"] = int(value.tag[1])
                        nested[0] = first
                blocks.extend(nested)
                continue
            segment.append(value)
        flush_breaks()
        flush_segment()
        return self._finalize_level(blocks)

    def _segment_block(self, values: list[str | _HtmlNode]) -> dict[str, Any] | None:
        if not values:
            return None
        text, html, links, has_markup = self._render_inline(values)
        text = clean_text(text)
        if not text and not links:
            return None
        source_links = [link for link in links if _is_article_source(link["url"])]
        if source_links and self._looks_like_source_segment(text, source_links):
            return {"type": "source_list", "links": self._dedupe_links(source_links)}
        text, html, links = self._strip_signature_suffix(text, html, links)
        if not text and not links:
            return None
        block: dict[str, Any] = {"type": "paragraph", "text": text}
        if has_markup and html.strip():
            block["html"] = html.strip()
        block["_links"] = links
        block["_candidate_signature"] = self._looks_like_signature(text, links)
        return block

    def _render_inline(
        self, values: list[str | _HtmlNode]
    ) -> tuple[str, str, list[dict[str, str]], bool]:
        text_parts: list[str] = []
        html_parts: list[str] = []
        links: list[dict[str, str]] = []
        has_markup = False

        def render(value: str | _HtmlNode) -> None:
            nonlocal has_markup
            if isinstance(value, str):
                text_parts.append(value)
                html_parts.append(html_module.escape(value, quote=False))
                return
            if value.tag == "br":
                text_parts.append(" ")
                html_parts.append(" ")
                return
            if value.tag == "a":
                label = clean_text(_visible_text(value))
                href = _safe_http_url(value.attrs.get("href"), base_url=self.base_url)
                inner_text_start = len(text_parts)
                inner_html_start = len(html_parts)
                for child in value.children:
                    render(child)
                if href:
                    rendered = "".join(html_parts[inner_html_start:])
                    del html_parts[inner_html_start:]
                    html_parts.append(
                        f'<a href="{html_module.escape(href, quote=True)}">{rendered}</a>'
                    )
                    links.append(
                        {"label": label or _host(href) or href, "url": href, "host": _host(href)}
                    )
                    has_markup = True
                elif len(text_parts) == inner_text_start and label:
                    text_parts.append(label)
                    html_parts.append(html_module.escape(label, quote=False))
                return
            if value.tag in SAFE_INLINE_TAGS:
                canonical = {"b": "strong", "i": "em"}.get(value.tag, value.tag)
                start = len(html_parts)
                for child in value.children:
                    render(child)
                rendered = "".join(html_parts[start:])
                del html_parts[start:]
                html_parts.append(f"<{canonical}>{rendered}</{canonical}>")
                has_markup = True
                return
            if value.tag in {"span", "font"}:
                start = len(html_parts)
                for child in value.children:
                    render(child)
                rendered = "".join(html_parts[start:])
                del html_parts[start:]
                color = _safe_color(value.attrs)
                if color:
                    html_parts.append(
                        f'<span style="color: {html_module.escape(color, quote=True)}">'
                        f"{rendered}</span>"
                    )
                    has_markup = True
                else:
                    html_parts.append(rendered)
                return
            for child in value.children:
                render(child)

        for value in values:
            render(value)
        return "".join(text_parts), "".join(html_parts), links, has_markup

    def _quote_block(self, node: _HtmlNode, *, kind: str, depth: int) -> dict[str, Any]:
        author = ""
        source_url = ""
        if kind == "reply":
            first_anchor = self._first_descendant(node, "a")
            if first_anchor is not None:
                candidate = _safe_http_url(first_anchor.attrs.get("href"), base_url=self.base_url)
                if _is_telegram_link(candidate):
                    source_url = candidate
                    author = clean_text(_visible_text(first_anchor)).rstrip("：:")
        if depth >= MAX_QUOTE_DEPTH - 1:
            text = clean_text(_visible_text(node))
            children: list[dict[str, Any]] = [{"type": "paragraph", "text": text}] if text else []
        else:
            children = self._parse_sequence(node.children, depth=depth + 1)
        if kind == "reply" and children and author:
            first = children[0]
            if first.get("type") == "paragraph":
                first_text = clean_text(str(first.get("text") or "")).rstrip("：:")
                if first_text == author:
                    children = children[1:]
        block: dict[str, Any] = {
            "type": "quote",
            "kind": kind,
            "children": children,
        }
        if kind == "reply":
            block["label"] = "回复上文"
        if author:
            block["author"] = author
        if source_url:
            block["source_url"] = source_url
        return block

    def _image_block(self, node: _HtmlNode) -> dict[str, Any] | None:
        if self._image_count >= MAX_IMAGES:
            return None
        url = _safe_http_url(
            node.attrs.get("src") or node.attrs.get("data-src") or node.attrs.get("data-original"),
            base_url=self.base_url,
        )
        if not url:
            return None
        self._image_count += 1
        return {
            "type": "image",
            "url": url,
            "alt": clean_text(node.attrs.get("alt") or ""),
            "caption": clean_text(node.attrs.get("title") or ""),
            "fallback_url": self.base_url,
        }

    def _finalize_level(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if blocks:
            last = blocks[-1]
            if last.get("type") == "paragraph" and last.get("_candidate_signature"):
                blocks.pop()
        for block in blocks:
            block.pop("_links", None)
            block.pop("_candidate_signature", None)
        return blocks

    def _remove_duplicate_title(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        expected = self._normalize_for_comparison(self.title)
        for index, block in enumerate(blocks):
            if block.get("type") != "paragraph":
                continue
            actual = self._normalize_for_comparison(str(block.get("text") or ""))
            if expected and actual == expected:
                return blocks[:index] + blocks[index + 1 :]
            break
        return blocks

    def _organize_top_level(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        replies = [b for b in blocks if b.get("type") == "quote" and b.get("kind") == "reply"]
        images = [b for b in blocks if b.get("type") == "image"]
        updates = [b for b in blocks if b.get("type") == "quote" and b.get("kind") == "update"]
        source_links: list[dict[str, str]] = []
        body: list[dict[str, Any]] = []
        for block in blocks:
            if block in replies or block in images or block in updates:
                continue
            if block.get("type") == "source_list":
                source_links.extend(block.get("links") or [])
            else:
                body.append(block)
        sources = (
            [{"type": "source_list", "links": self._dedupe_links(source_links)}]
            if source_links
            else []
        )
        return replies + images + body + sources + updates

    @staticmethod
    def _first_descendant(node: _HtmlNode, tag: str) -> _HtmlNode | None:
        for child in node.children:
            if not isinstance(child, _HtmlNode):
                continue
            if child.tag == tag:
                return child
            found = TelegramDescriptionParser._first_descendant(child, tag)
            if found is not None:
                return found
        return None

    @staticmethod
    def _normalize_for_comparison(value: str) -> str:
        return re.sub(r"[^\w一-鿿]", "", value or "").lower()

    @staticmethod
    def _dedupe_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in links:
            url = str(link.get("url") or "").strip()
            key = url.rstrip("/")
            if not url or key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "label": str(link.get("label") or link.get("host") or url).strip(),
                    "url": url,
                    "host": str(link.get("host") or _host(url)).strip(),
                }
            )
        return result

    @staticmethod
    def _looks_like_source_segment(text: str, links: list[dict[str, str]]) -> bool:
        if _SOURCE_PREFIX_RE.search(text):
            return True
        remainder = text
        for link in links:
            label = str(link.get("label") or "").strip()
            if label:
                remainder = remainder.replace(label, "", 1)
        remainder = re.sub(r"[\s|/、·，,;；:：—–\-]+", "", remainder)
        return not remainder

    @staticmethod
    def _looks_like_signature(text: str, links: list[dict[str, str]]) -> bool:
        if not links or len(text) > 100 or not all(_is_telegram_link(link["url"]) for link in links):
            return False
        return bool(re.search(r"频道|群|投稿|channel|chat|bot", text, re.IGNORECASE))

    @classmethod
    def _strip_signature_suffix(
        cls,
        text: str,
        html: str,
        links: list[dict[str, str]],
    ) -> tuple[str, str, list[dict[str, str]]]:
        """Remove a Telegram channel/chat/bot footer appended to real body text."""
        signature_start = len(links)
        while signature_start > 0 and _is_telegram_link(links[signature_start - 1]["url"]):
            signature_start -= 1
        signature_links = links[signature_start:]
        signature_text = " ".join(str(link.get("label") or "") for link in signature_links)
        if not signature_links or not cls._looks_like_signature(signature_text, signature_links):
            return text, html, links

        first_label = str(signature_links[0].get("label") or "").strip()
        text_index = text.rfind(first_label) if first_label else -1
        if text_index < 0:
            return text, html, links
        text = cls._trim_signature_leader(text[:text_index])

        first_url = html_module.escape(signature_links[0]["url"], quote=True)
        anchor_marker = f'<a href="{first_url}">'
        html_index = html.rfind(anchor_marker)
        if html_index >= 0:
            html = cls._trim_signature_leader(html[:html_index])
        else:
            # Avoid retaining hidden signature links when the markup shape is unexpected.
            html = ""
        return text, html, links[:signature_start]

    @staticmethod
    def _trim_signature_leader(value: str) -> str:
        value = value.rstrip()
        value = re.sub(
            r"(?:[·|｜•]\s*)?[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\s]+$",
            "",
            value,
        )
        return value.rstrip(" ·|｜•")

    @staticmethod
    def _count_blocks(blocks: list[dict[str, Any]]) -> int:
        total = 0
        for block in blocks:
            total += 1
            if block.get("type") == "quote":
                total += TelegramDescriptionParser._count_blocks(block.get("children") or [])
        return total

    def _limit_blocks(
        self, blocks: list[dict[str, Any]], remaining: list[int]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for block in blocks:
            if remaining[0] <= 0:
                break
            remaining[0] -= 1
            copied = dict(block)
            if copied.get("type") == "quote":
                copied["children"] = self._limit_blocks(copied.get("children") or [], remaining)
            result.append(copied)
        return result

    @staticmethod
    def _plain_paragraphs(blocks: list[dict[str, Any]]) -> list[str]:
        paragraphs: list[str] = []
        for block in blocks:
            block_type = block.get("type")
            if block_type in {"paragraph", "heading"}:
                text = clean_text(str(block.get("text") or ""))
                if text:
                    paragraphs.append(text)
            elif block_type == "source_list":
                links = block.get("links") or []
                if links:
                    paragraphs.append(
                        "文章来源：" + " | ".join(str(link.get("label") or link.get("host")) for link in links)
                    )
            elif block_type == "quote":
                prefix = {"reply": "回复上文", "update": "更新", "quote": "引用"}.get(
                    str(block.get("kind") or "quote"), "引用"
                )
                nested = TelegramDescriptionParser._plain_paragraphs(block.get("children") or [])
                if nested:
                    paragraphs.append(f"[{prefix}] " + "\n".join(nested))
        return paragraphs

    @staticmethod
    def _collect_images(blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
        images: list[dict[str, str]] = []
        for block in blocks:
            if block.get("type") == "image" and block.get("url"):
                image = {
                    "url": str(block["url"]),
                    "alt": str(block.get("alt") or ""),
                    "caption": str(block.get("caption") or ""),
                }
                fallback_url = str(block.get("fallback_url") or "")
                if fallback_url:
                    image["fallback_url"] = fallback_url
                images.append(image)
            elif block.get("type") == "quote":
                images.extend(TelegramDescriptionParser._collect_images(block.get("children") or []))
        return images


def parse_telegram_rss(
    xml_text: str,
    source: Source,
    *,
    rsshub_instance: str,
    limit: int | None = None,
) -> list[RawArticle]:
    root = ET.fromstring(_INVALID_XML_CHARS_RE.sub("", xml_text))
    entries = root.findall(".//item")
    if not entries:
        entries = [node for node in root.iter() if node.tag.split("}")[-1] == "entry"]
    if not entries:
        raise ValueError("response is not an RSS/Atom feed with entries")

    articles: list[RawArticle] = []
    for position, entry in enumerate(entries[:limit], start=1):
        title = _child_text(entry, ["title"])
        link = _entry_link(entry) or _child_text(entry, ["guid", "id"])
        description = (
            _child_raw_text(entry, ["description", "summary", "content"])
            or _child_raw_text(entry, ["encoded"])
        )
        if not title or not _safe_http_url(link):
            continue
        original = TelegramDescriptionParser(base_url=link, title=title).parse(description)
        published_raw = _child_text(entry, ["pubDate", "published", "updated"])
        metadata = {
            "source_type": "telegram_rss",
            "content_origin": "telegram_rss_description",
            "telegram_channel": str((source.config or {}).get("channel") or ""),
            "rsshub_instance": rsshub_instance,
            "feed_category": _child_text(entry, ["category"]),
            "feed_position": position,
            "rss_pubdate_missing": not bool(published_raw),
            "rss_title": title,
            **original,
        }
        articles.append(
            normalize_article(
                source=source,
                source_url=link,
                title=title,
                content=original["original_text"],
                author=_entry_author(entry),
                published_at=parse_datetime(
                    published_raw, assume_tz=(source.config or {}).get("pubdate_assume_tz")
                ),
                language=source.language,
                raw_score={},
                metadata=metadata,
            )
        )
    if not articles:
        raise ValueError("feed contained no valid Telegram items")
    return articles


class TelegramRSSCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        config = self.source.config or {}
        channel = str(config.get("channel") or "").strip()
        if not channel:
            path_parts = [part for part in urlsplit(self.source.url).path.split("/") if part]
            if len(path_parts) >= 3 and path_parts[-2] == "channel":
                channel = path_parts[-1]
        if not channel:
            raise ValueError(f"Telegram source {self.source.id} has no channel configured")

        configured_instances = config.get("rsshub_instances")
        instances = (
            tuple(str(value).rstrip("/") for value in configured_instances if str(value).strip())
            if isinstance(configured_instances, list)
            else DEFAULT_RSSHUB_INSTANCES
        )
        deadline = time.monotonic() + float(config.get("rsshub_failover_budget_seconds") or 90)
        errors: list[str] = []
        for instance in instances:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append("failover budget exhausted")
                break
            timeout = max(1, min(6, int(math.ceil(remaining))))
            feed_url = f"{instance.rstrip('/')}/telegram/channel/{quote(channel, safe='')}"
            try:
                xml_text = fetch_url_text(feed_url, timeout=timeout, max_attempts=1)
                return parse_telegram_rss(
                    xml_text,
                    self.source,
                    rsshub_instance=instance,
                    limit=limit,
                )
            except Exception as exc:
                errors.append(f"{instance}: {type(exc).__name__}: {str(exc)[:120]}")
        detail = "; ".join(errors[-8:])
        raise RuntimeError(f"all Telegram RSSHub instances failed for {channel}: {detail}")
