from __future__ import annotations

import html as html_module
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from app.crawlers.base import clean_text

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
SKIP_TAGS = {"script", "style", "noscript"}
# inline markup preserved in the block's optional html payload
INLINE_TAGS = {"a", "strong", "b", "em", "i", "code"}
_INLINE_CANONICAL = {"b": "strong", "i": "em"}
SAFE_HREF_SCHEMES = ("http://", "https://")
MAX_BLOCKS = 120
MAX_IMAGES = 30
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


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"[^\w一-鿿]", "", text or "").lower()


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
        if self._active_block and tag in INLINE_TAGS:
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

    def _flush_text_block(self) -> None:
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
        block: dict[str, Any] = {"type": "paragraph", "text": text}
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
        and blocks[0]["type"] == "paragraph"
        and _normalize_for_comparison(blocks[0]["text"]) == _normalize_for_comparison(title)
    ):
        blocks = blocks[1:]
        paragraphs = paragraphs[1:]
    return {
        "original_text": "\n\n".join(paragraphs),
        "original_paragraphs": paragraphs,
        "original_images": parser.images,
        "original_blocks": blocks,
    }
