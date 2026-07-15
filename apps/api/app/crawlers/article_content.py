from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from app.crawlers.base import clean_text

CONTENT_EXTRACTION_VERSION = 2
MAX_BLOCKS = 120
MAX_IMAGES = 30
MAX_QUOTE_DEPTH = 4
MAX_TABLE_ROWS = 100
MAX_TABLE_COLUMNS = 20

SAFE_HREF_SCHEMES = ("http://", "https://")
INLINE_TAGS = {"a", "strong", "b", "em", "i", "code", "del", "s", "sup", "sub", "mark"}
SKIP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed", "form", "nav", "aside", "footer"}

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$"
)
_NAMED_COLORS = {
    "red", "orange", "yellow", "green", "blue", "purple", "black", "white",
    "gray", "grey", "pink", "brown", "cyan", "magenta", "gold", "navy", "teal",
    "maroon", "olive", "silver", "crimson", "indigo", "violet", "coral", "salmon",
    "khaki", "orchid", "tomato", "chocolate", "tan",
}
_STYLE_COLOR_RE = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.IGNORECASE)
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_AVATAR_RE = re.compile(r"(?:avatar|author[-_ ]?(?:image|photo)|profile[-_ ]?(?:image|photo))", re.I)
_LOGO_ICON_RE = re.compile(r"(?:logo|icon|qrcode|qr-code|wechat)", re.I)
_BOILERPLATE_RE = re.compile(
    r"转载|版权所有|寻求报道|如需转载|合作请联系|未经授权|未经许可|免责声明|原创出品|本文图片来自|"
    r"加入我们|商务合作|扫码关注|all rights reserved|阅读原文|查看原文|点击查看原文",
    re.I,
)
_GENERIC_EXCLUDE_SELECTORS = (
    ".related", ".recommend", ".recommended", ".comments", ".comment", ".share",
    ".sharing", ".subscribe", ".newsletter", ".tags", ".tag-list", ".post-tags",
    ".author-posts", ".more-posts", ".popular-posts", ".hot-posts", ".person_box",
    "[class*='related-']", "[class*='recommend-']", "[class*='comment-']",
    "[class*='share-']", "[class*='subscribe-']",
)


@dataclass(frozen=True)
class ContentProfile:
    name: str
    hosts: tuple[str, ...]
    root_selectors: tuple[str, ...] = ()
    byline_selectors: tuple[str, ...] = ()
    lead_selectors: tuple[str, ...] = ()
    exclude_selectors: tuple[str, ...] = ()


CONTENT_PROFILES = (
    ContentProfile(
        name="qbitai-v1",
        hosts=("qbitai.com", "www.qbitai.com"),
        root_selectors=(".article",),
        byline_selectors=(".article_info",),
        lead_selectors=(".zhaiyao",),
        exclude_selectors=(".copyright", ".article-copyright", ".post-copyright"),
    ),
    ContentProfile(
        name="ithome-v2",
        hosts=("ithome.com", "www.ithome.com"),
        root_selectors=("#paragraph", ".post_content"),
        byline_selectors=(".info.clearfix",),
        exclude_selectors=(".ad-tips",),
    ),
)


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"[^\w一-鿿]", "", text or "").lower()


def _detect_body_language(text: str) -> str | None:
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if cjk >= 50 or (cjk > 0 and cjk * 4 >= latin):
        return "zh"
    if latin >= 200 and cjk < 10:
        return "en"
    return None


def profile_for_url(base_url: str | None) -> ContentProfile | None:
    host = urlparse(base_url or "").netloc.lower().split(":", 1)[0]
    return next((profile for profile in CONTENT_PROFILES if host in profile.hosts), None)


def content_extraction_version_for_url(base_url: str | None) -> int:
    """Return a source-aware cache version without invalidating every source."""
    parsed = urlparse(base_url or "")
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "blog.google":
        return 4
    source_specific_v3 = host == "blogs.nvidia.com" or (
        host in {"anthropic.com", "www.anthropic.com"}
        and parsed.path.startswith("/news/")
    )
    return 3 if source_specific_v3 else CONTENT_EXTRACTION_VERSION


def _safe_url(value: str | None, base_url: str | None) -> str | None:
    if not value:
        return None
    resolved = urljoin(base_url or "", value.strip())
    return resolved if resolved.lower().startswith(SAFE_HREF_SCHEMES) else None


def _safe_color(value: str | None) -> str | None:
    candidate = (value or "").strip().strip(";").strip()
    if _HEX_COLOR_RE.fullmatch(candidate):
        return candidate.lower()
    if _RGB_COLOR_RE.fullmatch(candidate):
        return candidate
    return candidate.lower() if candidate.lower() in _NAMED_COLORS else None


def _inline_parts(node: Tag | NavigableString, *, base_url: str | None) -> tuple[str, str, bool]:
    if isinstance(node, NavigableString):
        value = str(node)
        return value, html_module.escape(value, quote=False), False
    if not isinstance(node, Tag) or node.name in SKIP_TAGS:
        return "", "", False
    text_parts: list[str] = []
    html_parts: list[str] = []
    has_markup = False
    for child in node.children:
        text, safe_html, child_markup = _inline_parts(child, base_url=base_url)
        text_parts.append(text)
        html_parts.append(safe_html)
        has_markup = has_markup or child_markup
    inner_text = "".join(text_parts)
    inner_html = "".join(html_parts)
    tag = node.name.lower()
    if tag == "br":
        return " ", " ", False
    if tag not in INLINE_TAGS and tag not in {"span", "font"}:
        return inner_text, inner_html, has_markup
    canonical = {"b": "strong", "i": "em", "s": "del", "font": "span"}.get(tag, tag)
    attrs = ""
    if canonical == "a":
        href = _safe_url(node.get("href"), base_url)
        if not href:
            return inner_text, inner_html, has_markup
        attrs = f' href="{html_module.escape(href, quote=True)}"'
    elif canonical == "span":
        raw_color = node.get("color") if tag == "font" else None
        if not raw_color:
            match = _STYLE_COLOR_RE.search(str(node.get("style") or ""))
            raw_color = match.group(1) if match else None
        color = _safe_color(raw_color)
        if not color:
            return inner_text, inner_html, has_markup
        attrs = f' style="color: {html_module.escape(color, quote=True)}"'
    return inner_text, f"<{canonical}{attrs}>{inner_html}</{canonical}>", True


def _inline_content(node: Tag, *, base_url: str | None) -> dict[str, str] | None:
    text_raw, inline_html_raw, has_markup = _inline_parts(node, base_url=base_url)
    text = clean_text(text_raw)
    if not text:
        return None
    result = {"text": text}
    inline_html = clean_text(inline_html_raw)
    if has_markup and inline_html and inline_html != text:
        result["html"] = inline_html
    return result


def _int_attr(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    number = int(match.group(0))
    return number if 0 < number <= 10000 else None


def _image_source(node: Tag) -> str | None:
    """Prefer real lazy-loaded assets over transparent/thumbnail placeholders.

    All returned values still pass through _safe_url, so protocol-relative and
    path-relative image addresses are resolved against the article URL before
    they reach storage or the frontend image proxy.
    """
    lazy_attributes = (
        "data-original",
        "data-src",
        "data-lazy-src",
        "data-actualsrc",
        "data-echo",
        "data-url",
    )
    for attribute in lazy_attributes:
        value = node.get(attribute)
        if value:
            return str(value).strip()
    picture = node.find_parent("picture")
    if picture:
        source = picture.find("source")
        if source:
            for attribute in ("data-srcset", "srcset"):
                value = source.get(attribute)
                if value:
                    candidates = [part.strip().split()[0] for part in str(value).split(",") if part.strip()]
                    if candidates:
                        return candidates[-1]
    return str(node.get("src") or "").strip() or None


def _is_noncontent_image(node: Tag, url: str) -> bool:
    tokens = " ".join(
        [url, str(node.get("class") or ""), str(node.get("id") or ""),
         str(node.parent.get("class") if isinstance(node.parent, Tag) else "")]
    )
    return bool(_AVATAR_RE.search(tokens) or _LOGO_ICON_RE.search(tokens))


def _first_selected(root: Tag, selectors: Iterable[str]) -> Tag | None:
    for selector in selectors:
        selected = root.select_one(selector)
        if selected:
            return selected
    return None


def _byline_from_dom(root: Tag, profile: ContentProfile | None, base_url: str | None) -> dict[str, Any] | None:
    container = _first_selected(root, profile.byline_selectors if profile else ())
    if not container:
        return None
    author_node = container.select_one(".author, #author_baidu strong")
    author_link = author_node.select_one("a[href]") if author_node else container.select_one("[rel='author']")
    author_name = clean_text((author_link or author_node or container).get_text(" ", strip=True))
    if not author_name:
        return None
    author: dict[str, Any] = {"name": author_name}
    if author_link:
        author_url = _safe_url(author_link.get("href"), base_url)
        if author_url:
            author["url"] = author_url
    avatar = author_node.select_one("img") if author_node else None
    if avatar:
        avatar_url = _safe_url(avatar.get("src") or avatar.get("data-src"), base_url)
        if avatar_url:
            author["avatar_url"] = avatar_url
    result: dict[str, Any] = {"type": "byline", "author": author}
    date_node = container.select_one(".date, time[datetime], #pubtime_baidu")
    time_node = container.select_one(".time")
    published = " ".join(
        part for part in [
            str(date_node.get("datetime") or "") if date_node and date_node.has_attr("datetime") else clean_text(date_node.get_text(" ", strip=True)) if date_node else "",
            clean_text(time_node.get_text(" ", strip=True)) if time_node else "",
        ] if part
    )
    if published:
        result["published_at"] = published
    source_node = container.select_one(".from, #source_baidu")
    if source_node:
        source_link = source_node.select_one("a[href]")
        source_name = clean_text((source_link or source_node).get_text(" ", strip=True)).removeprefix("来源：").strip()
        if source_name:
            source: dict[str, str] = {"name": source_name}
            source_url = _safe_url(source_link.get("href"), base_url) if source_link else None
            if source_url:
                source["url"] = source_url
            result["source"] = source
    return result


def extract_page_byline(html_text: str, *, base_url: str | None = None) -> dict[str, Any] | None:
    """Best-effort page-level fallback after the visible profile byline.
    JSON-LD wins over meta because it can carry author URLs and images."""
    soup = BeautifulSoup(html_text, "html.parser")
    profile = profile_for_url(base_url)
    visible_byline = _byline_from_dom(soup, profile, base_url)
    if visible_byline:
        return visible_byline
    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text() or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        values = payload.get("@graph", []) if isinstance(payload, dict) and isinstance(payload.get("@graph"), list) else [payload]
        for value in values:
            if not isinstance(value, dict):
                continue
            kind = value.get("@type")
            kinds = set(kind if isinstance(kind, list) else [kind])
            if not kinds.intersection({"Article", "NewsArticle", "BlogPosting", "Report"}):
                continue
            author_value = value.get("author")
            if isinstance(author_value, list):
                author_value = next((item for item in author_value if isinstance(item, (dict, str))), None)
            if isinstance(author_value, str):
                author_value = {"name": author_value}
            if not isinstance(author_value, dict):
                continue
            name = clean_text(str(author_value.get("name") or ""))
            if not name:
                continue
            author: dict[str, str] = {"name": name}
            author_url = _safe_url(author_value.get("url"), base_url)
            if author_url:
                author["url"] = author_url
            image_value = author_value.get("image")
            if isinstance(image_value, dict):
                image_value = image_value.get("url")
            avatar_url = _safe_url(image_value, base_url)
            if avatar_url:
                author["avatar_url"] = avatar_url
            result: dict[str, Any] = {"type": "byline", "author": author}
            if value.get("datePublished"):
                result["published_at"] = str(value["datePublished"])
            publisher = value.get("publisher")
            if isinstance(publisher, dict) and publisher.get("name"):
                result["source"] = {"name": clean_text(str(publisher["name"]))}
            return result
    author_meta = soup.select_one("meta[name='author'], meta[property='article:author']")
    author_name = clean_text(str(author_meta.get("content") or "")) if author_meta else ""
    if not author_name:
        return None
    result = {"type": "byline", "author": {"name": author_name}}
    published_meta = soup.select_one("meta[property='article:published_time'], meta[name='date']")
    if published_meta and published_meta.get("content"):
        result["published_at"] = str(published_meta["content"])
    site_meta = soup.select_one("meta[property='og:site_name']")
    if site_meta and site_meta.get("content"):
        result["source"] = {"name": clean_text(str(site_meta["content"]))}
    return result


class DOMBlockExtractor:
    def __init__(self, *, base_url: str | None, title: str | None):
        self.base_url = base_url
        self.title = title or ""
        self.blocks: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.seen_images: set[str] = set()
        self.filtered_blocks = 0

    def add(self, block: dict[str, Any] | None) -> None:
        if block and len(self.blocks) < MAX_BLOCKS:
            self.blocks.append(block)

    def parse_children(self, root: Tag, *, depth: int = 0) -> list[dict[str, Any]]:
        previous = self.blocks
        local: list[dict[str, Any]] = []
        self.blocks = local
        for child in root.children:
            if isinstance(child, Tag):
                self.parse_node(child, depth=depth)
        self.blocks = previous
        return local

    def parse_node(self, node: Tag, *, depth: int = 0) -> None:
        if len(self.blocks) >= MAX_BLOCKS or node.name in SKIP_TAGS:
            return
        tag = node.name.lower()
        if tag == "uni-code-block" and urlparse(self.base_url or "").netloc.lower() == "blog.google":
            # Google Blog renders code through a custom element whose source
            # lives entirely in attributes, so it has no child <pre>/<code>
            # nodes for the generic DOM walker to discover.
            text = str(node.get("code") or "").strip()
            if text:
                block: dict[str, Any] = {"type": "code", "text": text}
                language = str(node.get("lang") or "").strip()
                if language:
                    block["language"] = language[:40]
                self.add(block)
            return
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            direct_images = node.find_all("img", recursive=False)
            if direct_images and not clean_text(node.get_text(" ", strip=True)):
                for image in direct_images:
                    self.add_image(image)
                return
            inline = _inline_content(node, base_url=self.base_url)
            if not inline:
                return
            if self.title and _normalize_for_comparison(inline["text"]) == _normalize_for_comparison(self.title):
                return
            if tag.startswith("h"):
                self.add({"type": "heading", "level": int(tag[1]), **inline})
            else:
                self.add({"type": "paragraph", **inline})
            for image in node.find_all("img"):
                self.add_image(image)
            return
        if tag == "img":
            self.add_image(node)
            return
        if tag == "figure":
            caption_node = node.find("figcaption")
            caption = clean_text(caption_node.get_text(" ", strip=True)) if caption_node else ""
            for image in node.find_all("img"):
                self.add_image(image, caption=caption)
            return
        if tag == "blockquote":
            if depth >= MAX_QUOTE_DEPTH:
                return
            children = self.parse_children(node, depth=depth + 1)
            if not children:
                inline = _inline_content(node, base_url=self.base_url)
                children = [{"type": "paragraph", **inline}] if inline else []
            self.add({"type": "quote", "kind": "quote", "children": children} if children else None)
            return
        if tag in {"ul", "ol"}:
            items = []
            for item in node.find_all("li", recursive=False):
                inline = _inline_content(item, base_url=self.base_url)
                if inline:
                    items.append(inline)
            self.add({"type": "list", "ordered": tag == "ol", "items": items} if items else None)
            return
        if tag == "pre":
            text = node.get_text("\n", strip=False).strip()
            if text:
                code = node.find("code")
                language = None
                if code:
                    classes = " ".join(code.get("class") or [])
                    match = re.search(r"(?:language-|lang-)([\w+-]+)", classes)
                    language = match.group(1) if match else None
                block: dict[str, Any] = {"type": "code", "text": text}
                if language:
                    block["language"] = language
                self.add(block)
            return
        if tag == "table":
            rows = []
            headers = []
            for row in node.find_all("tr")[:MAX_TABLE_ROWS]:
                cells = row.find_all(["th", "td"], recursive=False)[:MAX_TABLE_COLUMNS]
                parsed = [value for cell in cells if (value := _inline_content(cell, base_url=self.base_url))]
                if not parsed:
                    continue
                if not headers and row.find("th"):
                    headers = parsed
                else:
                    rows.append(parsed)
            self.add({"type": "table", "headers": headers, "rows": rows} if headers or rows else None)
            return
        if tag == "hr":
            self.add({"type": "divider"})
            return
        for child in node.children:
            if isinstance(child, Tag):
                self.parse_node(child, depth=depth)

    def add_image(self, node: Tag, *, caption: str = "") -> None:
        if len(self.images) >= MAX_IMAGES:
            return
        src = _image_source(node)
        url = _safe_url(src, self.base_url)
        if not url or url in self.seen_images or _is_noncontent_image(node, url):
            return
        width = _int_attr(node.get("width"))
        height = _int_attr(node.get("height"))
        image: dict[str, Any] = {
            "url": url,
            "alt": clean_text(str(node.get("alt") or "")),
            "caption": caption or clean_text(str(node.get("title") or "")),
        }
        if width:
            image["width"] = width
        if height:
            image["height"] = height
        if width or height:
            image["role"] = "hero" if not self.images and (not width or width >= 720) else "content"
        self.seen_images.add(url)
        self.images.append(image)
        self.add({"type": "image", **image})


def _block_text(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    if block_type in {"paragraph", "heading", "code"}:
        return [str(block.get("text") or "").strip()]
    if block_type in {"callout", "quote"}:
        return [text for child in block.get("children") or [] for text in _block_text(child)]
    if block_type == "list":
        return [str(item.get("text") or "").strip() for item in block.get("items") or []]
    if block_type == "table":
        cells = list(block.get("headers") or []) + [cell for row in block.get("rows") or [] for cell in row]
        return [str(cell.get("text") or "").strip() for cell in cells]
    return []


def _block_image_urls(block: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    if block.get("type") == "image" and block.get("url"):
        urls.add(str(block["url"]))
    for child in block.get("children") or []:
        if isinstance(child, dict):
            urls.update(_block_image_urls(child))
    return urls


def _strip_trailing_boilerplate(blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    cutoff = len(blocks)
    for index in range(len(blocks) - 1, max(-1, len(blocks) - 12), -1):
        block = blocks[index]
        if block.get("type") == "image":
            continue
        text = " ".join(_block_text(block))
        if text and (_BOILERPLATE_RE.search(text) or re.fullmatch(r"关于.{0,12}", text)):
            cutoff = index
            continue
        break
    if cutoff == len(blocks):
        return blocks, set()
    return blocks[:cutoff], {str(block.get("url")) for block in blocks[cutoff:] if block.get("type") == "image"}


def _strip_source_specific_blocks(
    blocks: list[dict[str, Any]], *, base_url: str | None
) -> list[dict[str, Any]]:
    parsed = urlparse(base_url or "")
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "aws.amazon.com" and parsed.path.startswith("/blogs/machine-learning/"):
        # AWS ML posts currently end with this standalone heading while the
        # author cards themselves are outside the extracted article structure.
        # Remove only that exact line; keep Conclusion, Related resources, etc.
        return [
            block
            for block in blocks
            if _normalize_for_comparison(" ".join(_block_text(block)))
            != "abouttheauthors"
        ]

    if host == "blogs.nvidia.com":
        # NVIDIA appends taxonomy navigation to the article body. Depending on
        # the post, Categories and Tags are either one list or separate lists.
        # Cut from the first exact taxonomy label near the tail so category/tag
        # values cannot leak into either the original body or its translation.
        taxonomy_labels = {"category", "categories", "tag", "tags"}
        tail_start = max(0, len(blocks) - 6)
        for index in range(tail_start, len(blocks)):
            texts = _block_text(blocks[index])
            if texts and _normalize_for_comparison(texts[0]) in taxonomy_labels:
                return blocks[:index]

    if host in {"anthropic.com", "www.anthropic.com"} and parsed.path.startswith(
        "/news/"
    ):
        # Anthropic News pages append a Related content card collection inside
        # the same semantic region as the article. The recommendation titles
        # and descriptions are navigation, not part of the article body.
        tail_start = max(0, len(blocks) - 10)
        for index in range(tail_start, len(blocks)):
            text = _normalize_for_comparison(" ".join(_block_text(blocks[index])))
            if text == "relatedcontent":
                return blocks[:index]

    if host == "blog.google":
        # Google Blog places its audio-player header inside the article region:
        # duplicate title/date/deck, presenter artwork and the HTML audio
        # fallback all precede the real written article. Preserve structured
        # byline metadata, then begin the body after the exact fallback line.
        audio_fallback = "yourbrowserdoesnotsupporttheaudioelement"
        for index, block in enumerate(blocks[:20]):
            text = _normalize_for_comparison(" ".join(_block_text(block)))
            if text == audio_fallback:
                bylines = [
                    candidate
                    for candidate in blocks[:index]
                    if candidate.get("type") == "byline"
                ]
                return [*bylines, *blocks[index + 1 :]]

    return blocks


def extract_article_content(
    html_text: str | None, *, base_url: str | None = None, title: str | None = None
) -> dict[str, Any]:
    empty = {
        "original_text": "", "original_paragraphs": [], "original_images": [],
        "original_blocks": [], "content_profile": "generic-v2", "filtered_blocks": 0,
    }
    if not html_text:
        return empty
    soup = BeautifulSoup(html_text, "html.parser")
    profile = profile_for_url(base_url)
    root: Tag = soup
    if profile:
        selected = _first_selected(soup, profile.root_selectors)
        if selected:
            root = selected
    filtered_nodes = 0
    for selector in (*_GENERIC_EXCLUDE_SELECTORS, *(profile.exclude_selectors if profile else ())):
        for node in root.select(selector):
            filtered_nodes += 1
            node.decompose()
    extractor = DOMBlockExtractor(base_url=base_url, title=title)
    blocks: list[dict[str, Any]] = []
    byline = _byline_from_dom(root, profile, base_url)
    if byline:
        blocks.append(byline)
    lead_nodes: list[Tag] = []
    if profile:
        for selector in profile.lead_selectors:
            lead_nodes.extend(root.select(selector))
    for lead in lead_nodes:
        children = extractor.parse_children(lead)
        if not children:
            inline = _inline_content(lead, base_url=base_url)
            children = [{"type": "paragraph", **inline}] if inline else []
        if children:
            blocks.append({"type": "callout", "kind": "lead", "children": children})
    skip_nodes = set(lead_nodes)
    if profile:
        for selector in profile.byline_selectors:
            skip_nodes.update(root.select(selector))
    for child in root.children:
        if isinstance(child, Tag) and child not in skip_nodes:
            extractor.parse_node(child)
    blocks.extend(extractor.blocks)
    blocks, dropped_images = _strip_trailing_boilerplate(blocks)
    source_blocks = blocks
    blocks = _strip_source_specific_blocks(blocks, base_url=base_url)
    source_specific_cleanup = blocks != source_blocks
    retained_image_urls = {
        url for block in blocks for url in _block_image_urls(block)
    }
    images = [
        image
        for image in extractor.images
        if image["url"] not in dropped_images
        and (not source_specific_cleanup or image["url"] in retained_image_urls)
    ]
    paragraphs = [text for block in blocks if block.get("type") != "byline" for text in _block_text(block) if text]
    return {
        "original_text": "\n\n".join(paragraphs),
        "original_paragraphs": paragraphs,
        "original_images": images,
        "original_blocks": blocks[:MAX_BLOCKS],
        "content_profile": profile.name if profile else "generic-v2",
        "filtered_blocks": filtered_nodes + extractor.filtered_blocks,
        "author_detected": bool(byline),
    }
