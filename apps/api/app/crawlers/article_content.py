from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from app.crawlers.base import clean_text

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
SKIP_TAGS = {"script", "style", "noscript"}
MAX_BLOCKS = 120
MAX_IMAGES = 30


class ArticleContentParser(HTMLParser):
    def __init__(self, *, base_url: str | None = None):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.blocks: list[dict[str, Any]] = []
        self.paragraphs: list[str] = []
        self.images: list[dict[str, str]] = []
        self._active_block: str | None = None
        self._text_chunks: list[str] = []
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
            return
        if tag == "img":
            self._add_image(dict(attrs))

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

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._active_block:
            self._text_chunks.append(data)

    def close(self) -> None:
        super().close()
        self._flush_text_block()

    def _flush_text_block(self) -> None:
        text = clean_text("".join(self._text_chunks))
        self._text_chunks = []
        if not text or len(self.blocks) >= MAX_BLOCKS:
            return
        block = {"type": "paragraph", "text": text}
        self.blocks.append(block)
        self.paragraphs.append(text)

    def _add_image(self, attrs: dict[str, str | None]) -> None:
        src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-original")
        if not src:
            return
        url = urljoin(self.base_url or "", src)
        if not url or url in self._seen_images or len(self.images) >= MAX_IMAGES:
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


def extract_article_content(html_text: str | None, *, base_url: str | None = None) -> dict[str, Any]:
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
    return {
        "original_text": "\n\n".join(parser.paragraphs),
        "original_paragraphs": parser.paragraphs,
        "original_images": parser.images,
        "original_blocks": parser.blocks,
    }
