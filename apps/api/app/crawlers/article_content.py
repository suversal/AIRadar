from __future__ import annotations

import html as html_module
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from app.crawlers.base import clean_text

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "noscript"}
# inline markup preserved in the block's optional html payload
INLINE_TAGS = {"a", "strong", "b", "em", "i", "code"}
# span/font carry inline color, handled separately from INLINE_TAGS because
# they need attribute parsing (style="color: ...") rather than a fixed tag
# name - see _open_color_tag
COLOR_INLINE_TAGS = {"span", "font"}
_INLINE_CANONICAL = {"b": "strong", "i": "em", "font": "span"}
SAFE_HREF_SCHEMES = ("http://", "https://")
MAX_BLOCKS = 120
MAX_IMAGES = 30

# Only a tightly-scoped color value is ever forwarded to the browser - this
# guards against style-based injection (url(), expression(), embedded `;`
# smuggling extra declarations) since the frontend renders it as an actual
# inline `style` attribute.
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$"
)
_NAMED_COLORS = {
    "red", "orange", "yellow", "green", "blue", "purple", "black", "white",
    "gray", "grey", "pink", "brown", "cyan", "magenta", "gold", "navy",
    "teal", "maroon", "olive", "silver", "crimson", "indigo", "violet",
    "coral", "salmon", "khaki", "orchid", "tomato", "chocolate", "tan",
}
_STYLE_COLOR_RE = re.compile(r"color\s*:\s*([^;]+)", re.IGNORECASE)
# User-avatar widgets (upvoters, commenters, byline author photo) sit inside
# the same <article>/<main> region as the real post on some sites (e.g.
# HuggingFace's "who liked this" avatar stack, the-decoder.com's byline) -
# these are never article content regardless of which site hosts them.
_AVATAR_HOST_MARKERS = (
    "cdn-avatars.",
    "avatars.githubusercontent.com",
    "gravatar.com",
    "/avatars/",
)
# "avatar" as a path/filename token (not just a specific host) - real cases:
# the-decoder.com's own-origin /resources/images/avatar_matthias_bastian.jpg,
# a WordPress theme's blank-avatar.png. Broad but low-risk: profile-picture
# filenames reliably carry this word; genuine content images essentially
# never do.
_AVATAR_FILENAME_RE = re.compile(r"avatar", re.IGNORECASE)

# Trailing site furniture (copyright notices, "seeking tips" CTAs, image
# credit lines) that sites like qbitai/36kr render inside the same content
# container as the real article body, with no markup boundary to separate
# them. Only checked against the last few blocks (see
# _TRAILING_BOILERPLATE_SCAN_DEPTH) so a legitimate paragraph that happens to
# mention "版权" mid-article is never touched.
_TRAILING_BOILERPLATE_RE = re.compile(
    r"转载|版权所有|寻求报道|本文图片来自|如需转载|合作请联系|未经授权|未经许可|免责声明|原创出品|"
    r"加入我们|商务合作|扫码关注|Subscribe to|all rights reserved",
    re.IGNORECASE,
)
# a bare "关于量子位"/"关于我们"/"关于36氪" site-info line - the exact site
# name varies per source, so this can't be a fixed keyword; short length
# guards against matching real prose like "关于这个问题的讨论仍在继续"
_TRAILING_ABOUT_LINE_RE = re.compile(r"^关于.{0,8}$")
# a short paragraph whose only content is a link's anchor text (e.g. a bare
# "寻求报道" CTA) - real prose this short essentially never stands alone
_TRAILING_SHORT_LINK_MAX_CHARS = 15
# real qbitai footers run: 关于X / 加入我们 / 寻求报道 / 商务合作 / 扫码关注X
# / qrcode image - deep enough to cover that plus a couple of copyright lines
_TRAILING_BOILERPLATE_SCAN_DEPTH = 10


def _looks_like_trailing_boilerplate(block: dict[str, Any]) -> bool:
    if block.get("type") != "paragraph":
        return False
    text = str(block.get("text") or "").strip()
    if _TRAILING_BOILERPLATE_RE.search(text) or _TRAILING_ABOUT_LINE_RE.match(text):
        return True
    html = str(block.get("html") or "")
    if html and len(text) <= _TRAILING_SHORT_LINK_MAX_CHARS:
        stripped = re.sub(r"</?a[^>]*>", "", html)
        if stripped.strip() == text.strip():
            return True
    return False


def _strip_trailing_boilerplate(
    blocks: list[dict[str, Any]], paragraphs: list[str]
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """Drop trailing paragraph blocks that are site furniture, not article
    body. Scans backward from the end and stops at the first block that
    doesn't match, so a legitimate paragraph earlier in the article (that
    happens to mention "版权" or similar) is never removed. Trailing images
    (a footer qrcode/logo, real case: qbitai) are skipped over rather than
    treated as a stop condition, so the scan can still reach the boilerplate
    paragraphs sitting right before them - but only actually dropped if the
    scan finds a matching paragraph further back to anchor the cutoff on.
    Returns the dropped image URLs too, so the caller can also filter them
    out of the flat `original_images` list."""
    cutoff = len(blocks)
    scan_start = max(0, len(blocks) - _TRAILING_BOILERPLATE_SCAN_DEPTH)
    for index in range(len(blocks) - 1, scan_start - 1, -1):
        if blocks[index].get("type") == "image":
            continue
        if not _looks_like_trailing_boilerplate(blocks[index]):
            break
        cutoff = index
    if cutoff == len(blocks):
        return blocks, paragraphs, set()
    # `paragraphs` only ever grows via the same append that adds a paragraph
    # block, in the same order - so the tail of `paragraphs` lines up with
    # the tail paragraph-type blocks being dropped here. Trim by count, not
    # by text match, so a duplicate legitimate paragraph earlier in the
    # article is never accidentally removed too.
    dropped_paragraph_count = sum(
        1 for block in blocks[cutoff:] if block.get("type") == "paragraph"
    )
    kept_paragraphs = (
        paragraphs[:-dropped_paragraph_count] if dropped_paragraph_count else paragraphs
    )
    dropped_image_urls = {
        block["url"] for block in blocks[cutoff:] if block.get("type") == "image"
    }
    return blocks[:cutoff], kept_paragraphs, dropped_image_urls


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"[^\w一-鿿]", "", text or "").lower()


def _safe_color_value(value: str) -> str | None:
    candidate = value.strip().strip(";").strip()
    if not candidate:
        return None
    if _HEX_COLOR_RE.match(candidate):
        return candidate.lower()
    if _RGB_COLOR_RE.match(candidate.replace(" ", "")):
        return candidate
    if candidate.lower() in _NAMED_COLORS:
        return candidate.lower()
    return None


def _color_from_attrs(tag: str, attrs: dict[str, str | None]) -> str | None:
    if tag == "font":
        raw = attrs.get("color")
    else:
        style = attrs.get("style") or ""
        match = _STYLE_COLOR_RE.search(style)
        raw = match.group(1) if match else None
    if not raw:
        return None
    return _safe_color_value(raw)


class ArticleContentParser(HTMLParser):
    def __init__(self, *, base_url: str | None = None):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.blocks: list[dict[str, Any]] = []
        self.paragraphs: list[str] = []
        self.images: list[dict[str, str]] = []
        self._active_block: str | None = None
        self._text_chunks: list[str] = []
        self._html_chunks: list[str] = []
        self._has_inline_markup = False
        self._open_inline: list[str] = []
        self._skip_depth = 0
        self._seen_images: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS:
            self._flush_text_block()
            self._active_block = tag
            return
        if tag == "br":
            self._text_chunks.append(" ")
            self._html_chunks.append(" ")
            return
        if tag == "img":
            self._add_image(dict(attrs))
            return
        if self._active_block and tag in INLINE_TAGS:
            self._open_inline_tag(tag, dict(attrs))
            return
        if self._active_block and tag in COLOR_INLINE_TAGS:
            self._open_color_tag(tag, dict(attrs))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS and self._active_block == tag:
            self._flush_text_block()
            self._active_block = None
            return
        if self._active_block and (tag in INLINE_TAGS or tag in COLOR_INLINE_TAGS):
            canonical = _INLINE_CANONICAL.get(tag, tag)
            if canonical in self._open_inline:
                # close everything up to and including the tag to stay well-formed
                while self._open_inline:
                    open_tag = self._open_inline.pop()
                    self._html_chunks.append(f"</{open_tag}>")
                    if open_tag == canonical:
                        break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._active_block:
            self._text_chunks.append(data)
            self._html_chunks.append(html_module.escape(data, quote=False))

    def close(self) -> None:
        super().close()
        self._flush_text_block()

    def _open_inline_tag(self, tag: str, attrs: dict[str, str | None]) -> None:
        canonical = _INLINE_CANONICAL.get(tag, tag)
        if canonical == "a":
            href = urljoin(self.base_url or "", (attrs.get("href") or "").strip())
            if not href.lower().startswith(SAFE_HREF_SCHEMES):
                return  # unsafe or empty link: keep its text, drop the markup
            escaped = html_module.escape(href, quote=True)
            self._html_chunks.append(f'<a href="{escaped}">')
        else:
            self._html_chunks.append(f"<{canonical}>")
        self._open_inline.append(canonical)
        self._has_inline_markup = True

    def _open_color_tag(self, tag: str, attrs: dict[str, str | None]) -> None:
        color = _color_from_attrs(tag, attrs)
        if not color:
            return  # no safe color found: keep the text, drop the wrapper
        self._html_chunks.append(f'<span style="color: {color}">')
        self._open_inline.append("span")
        self._has_inline_markup = True

    def _flush_text_block(self) -> None:
        active_tag = self._active_block
        while self._open_inline:
            self._html_chunks.append(f"</{self._open_inline.pop()}>")
        text = clean_text("".join(self._text_chunks))
        inline_html = clean_text("".join(self._html_chunks))
        has_markup = self._has_inline_markup
        self._text_chunks = []
        self._html_chunks = []
        self._has_inline_markup = False
        if not text or len(self.blocks) >= MAX_BLOCKS:
            return
        if active_tag in HEADING_TAGS:
            block: dict[str, Any] = {"type": "heading", "level": int(active_tag[1]), "text": text}
        else:
            block = {"type": "paragraph", "text": text}
        if has_markup and inline_html != text:
            block["html"] = inline_html
        self.blocks.append(block)
        self.paragraphs.append(text)

    def _add_image(self, attrs: dict[str, str | None]) -> None:
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-original")
        if not src:
            return
        url = urljoin(self.base_url or "", src)
        if not url or url in self._seen_images or len(self.images) >= MAX_IMAGES:
            return
        if any(marker in url for marker in _AVATAR_HOST_MARKERS):
            return
        if _AVATAR_FILENAME_RE.search(url):
            return
        self._flush_text_block()
        image = {
            "url": url,
            "alt": clean_text(attrs.get("alt") or ""),
            "caption": clean_text(attrs.get("title") or ""),
        }
        self._seen_images.add(url)
        self.images.append(image)
        if len(self.blocks) < MAX_BLOCKS:
            self.blocks.append({"type": "image", **image})


def extract_article_content(
    html_text: str | None, *, base_url: str | None = None, title: str | None = None
) -> dict[str, Any]:
    if not html_text:
        return {
            "original_text": "",
            "original_paragraphs": [],
            "original_images": [],
            "original_blocks": [],
        }
    parser = ArticleContentParser(base_url=base_url)
    parser.feed(html_text)
    parser.close()
    blocks, paragraphs = parser.blocks, parser.paragraphs
    # some sites render the <h1> headline inside the same content region as
    # the body (the-decoder.com among others, ~40 articles affected on real
    # data) - that duplicates the title as the article's own first paragraph
    if (
        title
        and blocks
        and blocks[0]["type"] in ("paragraph", "heading")
        and _normalize_for_comparison(blocks[0]["text"]) == _normalize_for_comparison(title)
    ):
        blocks = blocks[1:]
        paragraphs = paragraphs[1:]
    blocks, paragraphs, dropped_image_urls = _strip_trailing_boilerplate(blocks, paragraphs)
    images = (
        [image for image in parser.images if image["url"] not in dropped_image_urls]
        if dropped_image_urls
        else parser.images
    )
    return {
        "original_text": "\n\n".join(paragraphs),
        "original_paragraphs": paragraphs,
        "original_images": images,
        "original_blocks": blocks,
    }
