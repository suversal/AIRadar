from __future__ import annotations

import html as html_module
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag


ALLOWED_NODE_TYPES = {
    "doc", "paragraph", "text", "heading", "bulletList", "orderedList", "listItem",
    "blockquote", "codeBlock", "horizontalRule", "image", "table", "tableRow",
    "tableHeader", "tableCell", "hardBreak",
}
ALLOWED_MARK_TYPES = {
    "bold", "italic", "strike", "code", "link", "textStyle", "highlight",
    "underline", "subscript", "superscript",
}
ALLOWED_TEXT_ALIGNMENTS = {"left", "center", "right", "justify"}
ALLOWED_FONT_SIZES = {"12px", "14px", "16px", "18px", "20px", "24px", "28px", "32px"}
SAFE_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?")
HTML_TAGS = {
    "a", "article", "b", "blockquote", "br", "code", "del", "div", "em",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
    "img", "li", "mark", "ol", "p", "pre", "s", "section", "span", "strike",
    "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    "u", "ul",
}
DROP_HTML_TAGS = {"button", "embed", "form", "iframe", "input", "link", "meta", "object", "script", "style", "svg"}
SAFE_STYLE_PROPERTIES = {
    "background-color", "color", "font-size", "font-style", "font-weight",
    "font-family", "letter-spacing", "line-height", "text-align", "text-decoration",
    "text-indent", "vertical-align", "white-space",
}


class RichTextValidationError(ValueError):
    pass


def _safe_style(value: Any) -> str:
    declarations = []
    for part in str(value or "").split(";"):
        name, separator, raw_value = part.partition(":")
        name = name.strip().lower()
        cleaned = raw_value.strip()
        if not separator or name not in SAFE_STYLE_PROPERTIES or not cleaned:
            continue
        lowered = cleaned.lower()
        if any(token in lowered for token in ("url(", "expression", "javascript:", "@import")):
            continue
        if len(cleaned) > 80:
            continue
        declarations.append(f"{name}: {cleaned}")
    return "; ".join(declarations)


def _clean_html_document(value: Any) -> BeautifulSoup:
    if not isinstance(value, str) or len(value) > 1_000_000:
        raise RichTextValidationError("editor HTML is invalid or too large")
    soup = BeautifulSoup(value, "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.name == "font":
            legacy_style = "; ".join(
                value
                for value in (
                    f"color: {tag.attrs.get('color')}" if tag.attrs.get("color") else "",
                    f"font-family: {tag.attrs.get('face')}" if tag.attrs.get("face") else "",
                )
                if value
            )
            tag.name = "span"
            tag.attrs["style"] = "; ".join(
                value for value in (str(tag.attrs.get("style") or ""), legacy_style) if value
            )
        if tag.name in DROP_HTML_TAGS:
            tag.decompose()
            continue
        if tag.name not in HTML_TAGS:
            tag.unwrap()
            continue
        allowed: dict[str, str] = {}
        style = _safe_style(tag.attrs.get("style"))
        if style:
            allowed["style"] = style
        alignment = str(tag.attrs.get("align") or "").lower()
        if alignment in ALLOWED_TEXT_ALIGNMENTS:
            allowed["align"] = alignment
        if tag.name == "a" and tag.attrs.get("href"):
            try:
                allowed["href"] = _web_url(tag.attrs.get("href"))
                allowed["target"] = "_blank"
                allowed["rel"] = "noopener noreferrer"
            except RichTextValidationError:
                pass
        elif tag.name == "img":
            source = next(
                (
                    str(tag.attrs.get(key) or "").strip()
                    for key in (
                        "data-original", "data-original-src", "data-actualsrc",
                        "data-src", "data-lazy-src", "data-lazy", "data-url",
                        "data-echo", "data-fallback-src", "src",
                    )
                    if str(tag.attrs.get(key) or "").strip()
                ),
                "",
            )
            if source.startswith("//"):
                source = f"https:{source}"
            try:
                allowed["src"] = _web_url(source)
            except RichTextValidationError:
                tag.decompose()
                continue
            for key in ("alt", "title", "width", "height"):
                if tag.attrs.get(key):
                    allowed[key] = str(tag.attrs[key])[:500]
            allowed["referrerpolicy"] = "no-referrer"
            allowed["loading"] = "lazy"
        tag.attrs = allowed
    return soup


def _element_alignment(element: Tag) -> str | None:
    alignment = str(element.attrs.get("align") or "").lower()
    if alignment in ALLOWED_TEXT_ALIGNMENTS:
        return alignment
    style = _safe_style(element.attrs.get("style"))
    match = re.search(r"(?:^|;)\s*text-align:\s*(left|center|right|justify)", style)
    return match.group(1) if match else None


def _html_inline(element: Tag) -> dict[str, str]:
    clone_soup = BeautifulSoup(str(element), "html.parser")
    clone = clone_soup.find(element.name)
    if clone is None:
        return {"text": ""}
    for image in clone.find_all("img"):
        image.decompose()
    text = clone.get_text(" ", strip=True)
    html = clone.decode_contents().strip()
    own_style = _safe_style(element.attrs.get("style"))
    inline_style = "; ".join(
        part for part in own_style.split("; ") if not part.startswith("text-align:")
    )
    if inline_style and html:
        html = f'<span style="{html_module.escape(inline_style, quote=True)}">{html}</span>'
    result = {"text": text}
    if html and html != text:
        result["html"] = html
    return result


def _html_document_to_blocks(document: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    soup = _clean_html_document(document.get("html"))
    root = soup.body or soup

    def convert(element: Tag) -> list[dict[str, Any]]:
        name = element.name
        if name in {"article", "section", "div"} and element.find(
            ["p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote", "pre", "table", "figure", "img", "hr"],
            recursive=False,
        ):
            return [
                block
                for child in element.children
                if isinstance(child, Tag)
                for block in convert(child)
            ]
        if name in {"p", "div", "section", "article"}:
            item = _html_inline(element)
            blocks = []
            if item["text"]:
                block: dict[str, Any] = {"type": "paragraph", **item}
                alignment = _element_alignment(element)
                if alignment:
                    block["align"] = alignment
                blocks.append(block)
            blocks.extend(convert(image) for image in element.find_all("img"))
            return [block for group in blocks for block in (group if isinstance(group, list) else [group])]
        if name in {"span", "strong", "b", "em", "i", "u", "s", "strike", "del", "mark", "code", "sub", "sup", "a"}:
            item = _html_inline(element)
            return [{"type": "paragraph", **item}] if item["text"] else []
        if name and re.fullmatch(r"h[1-6]", name):
            item = _html_inline(element)
            block = {"type": "heading", "level": int(name[1]), **item}
            alignment = _element_alignment(element)
            if alignment:
                block["align"] = alignment
            return [block] if item["text"] else []
        if name == "img":
            source = _web_url(element.attrs.get("src"))
            block = {"type": "image", "url": source}
            if element.attrs.get("alt"):
                block["alt"] = str(element.attrs["alt"])
            if element.attrs.get("title"):
                block["caption"] = str(element.attrs["title"])
            for key in ("width", "height"):
                raw = str(element.attrs.get(key) or "").replace("px", "").strip()
                if raw.isdigit():
                    block[key] = int(raw)
            return [block]
        if name == "figure":
            caption = element.find("figcaption")
            blocks = []
            for image in element.find_all("img"):
                image_blocks = convert(image)
                if caption and image_blocks:
                    image_blocks[0]["caption"] = caption.get_text(" ", strip=True)[:500]
                blocks.extend(image_blocks)
            return blocks
        if name in {"ul", "ol"}:
            items = [
                _html_inline(item)
                for item in element.find_all("li", recursive=False)
                if item.get_text(" ", strip=True)
            ]
            return [{"type": "list", "ordered": name == "ol", "items": items}] if items else []
        if name == "blockquote":
            children = []
            for child in element.children:
                if isinstance(child, Tag):
                    children.extend(convert(child))
            if not children:
                item = _html_inline(element)
                if item["text"]:
                    children = [{"type": "paragraph", **item}]
            return [{"type": "quote", "kind": "quote", "children": children}] if children else []
        if name == "pre":
            text = element.get_text("\n", strip=False).strip()
            return [{"type": "code", "text": text}] if text else []
        if name == "hr":
            return [{"type": "divider"}]
        if name == "table":
            rows = []
            headers = []
            for row in element.find_all("tr"):
                cells = [_html_inline(cell) for cell in row.find_all(["th", "td"], recursive=False)]
                if not cells:
                    continue
                if not headers and row.find("th", recursive=False):
                    headers = cells
                else:
                    rows.append(cells)
            return [{"type": "table", "headers": headers, "rows": rows}]
        return []

    blocks: list[dict[str, Any]] = []
    for child in root.children:
        if isinstance(child, NavigableString):
            value = str(child).strip()
            if value:
                blocks.append({"type": "paragraph", "text": value})
        elif isinstance(child, Tag):
            blocks.extend(convert(child))
    plain = "\n\n".join(
        block.get("text", "")
        for block in blocks
        if block.get("type") in {"paragraph", "heading", "code"} and block.get("text")
    )
    for block in blocks:
        if block.get("type") == "list":
            plain += "\n" + "\n".join(item.get("text", "") for item in block["items"])
    cleaned = {"type": "html", "html": root.decode_contents().strip()}
    return cleaned, blocks, re.sub(r"\n{3,}", "\n\n", plain).strip()


def _web_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RichTextValidationError("image and link URLs must use HTTP or HTTPS")
    return url


def _safe_color(value: Any) -> str:
    color = str(value or "").strip()
    if not SAFE_COLOR_RE.fullmatch(color):
        raise RichTextValidationError("text colors must use a 6 or 8 digit hex value")
    return color.lower()


def _block_alignment(node: dict[str, Any]) -> str | None:
    alignment = str((node.get("attrs") or {}).get("textAlign") or "").strip()
    if not alignment:
        return None
    if alignment not in ALLOWED_TEXT_ALIGNMENTS:
        raise RichTextValidationError("unsupported text alignment")
    return alignment


def _inline(node: dict[str, Any]) -> tuple[str, str | None]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    marked = False
    for child in node.get("content") or []:
        child_type = child.get("type")
        if child_type == "hardBreak":
            text_parts.append("\n")
            html_parts.append("<br>")
            marked = True
            continue
        if child_type != "text":
            continue
        value = str(child.get("text") or "")
        rendered = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for mark in child.get("marks") or []:
            mark_type = mark.get("type")
            if mark_type not in ALLOWED_MARK_TYPES:
                raise RichTextValidationError(f"unsupported mark: {mark_type}")
            if mark_type == "bold":
                rendered = f"<strong>{rendered}</strong>"
            elif mark_type == "italic":
                rendered = f"<em>{rendered}</em>"
            elif mark_type == "strike":
                rendered = f"<del>{rendered}</del>"
            elif mark_type == "code":
                rendered = f"<code>{rendered}</code>"
            elif mark_type == "link":
                href = html_module.escape(
                    _web_url((mark.get("attrs") or {}).get("href")), quote=True
                )
                rendered = f'<a href="{href}">{rendered}</a>'
            elif mark_type == "textStyle":
                attrs = mark.get("attrs") or {}
                styles = []
                if attrs.get("color"):
                    styles.append(f"color: {_safe_color(attrs['color'])}")
                if attrs.get("fontSize"):
                    font_size = str(attrs["fontSize"]).strip()
                    if font_size not in ALLOWED_FONT_SIZES:
                        raise RichTextValidationError("unsupported font size")
                    styles.append(f"font-size: {font_size}")
                if styles:
                    rendered = f'<span style="{"; ".join(styles)}">{rendered}</span>'
            elif mark_type == "highlight":
                color = _safe_color((mark.get("attrs") or {}).get("color"))
                rendered = f'<mark style="background-color: {color}">{rendered}</mark>'
            elif mark_type == "underline":
                rendered = f"<u>{rendered}</u>"
            elif mark_type == "subscript":
                rendered = f"<sub>{rendered}</sub>"
            elif mark_type == "superscript":
                rendered = f"<sup>{rendered}</sup>"
            marked = True
        text_parts.append(value)
        html_parts.append(rendered)
    text = "".join(text_parts).strip()
    return text, "".join(html_parts) if marked else None


def _inline_dict(node: dict[str, Any]) -> dict[str, str]:
    text, html = _inline(node)
    result = {"text": text}
    if html:
        result["html"] = html
    return result


def _validate_tree(node: dict[str, Any], *, depth: int = 0, count: list[int] | None = None) -> None:
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > 2000:
        raise RichTextValidationError("document contains too many nodes")
    if depth > 20:
        raise RichTextValidationError("document is nested too deeply")
    node_type = node.get("type")
    if node_type not in ALLOWED_NODE_TYPES:
        raise RichTextValidationError(f"unsupported node: {node_type}")
    for child in node.get("content") or []:
        if not isinstance(child, dict):
            raise RichTextValidationError("document content must contain objects")
        _validate_tree(child, depth=depth + 1, count=count)


def document_to_blocks(document: dict[str, Any] | None) -> tuple[list[dict[str, Any]], str]:
    if not document:
        return [], ""
    if not isinstance(document, dict):
        raise RichTextValidationError("editor document must be an object")
    if document.get("type") == "html":
        _cleaned, blocks, plain = _html_document_to_blocks(document)
        return blocks, plain
    if document.get("type") != "doc":
        raise RichTextValidationError("unsupported editor document format")
    _validate_tree(document)
    blocks: list[dict[str, Any]] = []

    def convert(node: dict[str, Any]) -> list[dict[str, Any]]:
        node_type = node.get("type")
        if node_type == "paragraph":
            item = _inline_dict(node)
            alignment = _block_alignment(node)
            block = {"type": "paragraph", **item}
            if alignment:
                block["align"] = alignment
            return [block] if item["text"] else []
        if node_type == "heading":
            item = _inline_dict(node)
            level = max(1, min(6, int((node.get("attrs") or {}).get("level") or 2)))
            block = {"type": "heading", "level": level, **item}
            alignment = _block_alignment(node)
            if alignment:
                block["align"] = alignment
            return [block] if item["text"] else []
        if node_type in {"bulletList", "orderedList"}:
            items = []
            for list_item in node.get("content") or []:
                paragraphs = [c for c in list_item.get("content") or [] if c.get("type") == "paragraph"]
                if paragraphs:
                    item = _inline_dict(paragraphs[0])
                    if item["text"]:
                        items.append(item)
            return [{"type": "list", "ordered": node_type == "orderedList", "items": items}] if items else []
        if node_type == "blockquote":
            children = [block for child in node.get("content") or [] for block in convert(child)]
            return [{"type": "quote", "kind": "quote", "children": children}] if children else []
        if node_type == "codeBlock":
            text = "".join(str(child.get("text") or "") for child in node.get("content") or [])
            language = str((node.get("attrs") or {}).get("language") or "").strip()
            block: dict[str, Any] = {"type": "code", "text": text}
            if language:
                block["language"] = language
            return [block] if text else []
        if node_type == "horizontalRule":
            return [{"type": "divider"}]
        if node_type == "image":
            attrs = node.get("attrs") or {}
            block = {"type": "image", "url": _web_url(attrs.get("src"))}
            for source, target in (("alt", "alt"), ("title", "caption")):
                if attrs.get(source):
                    block[target] = str(attrs[source])[:500]
            return [block]
        if node_type == "table":
            rows = []
            header: list[dict[str, str]] = []
            for row_index, row in enumerate(node.get("content") or []):
                cells = []
                all_headers = True
                for cell in row.get("content") or []:
                    all_headers = all_headers and cell.get("type") == "tableHeader"
                    paragraphs = [c for c in cell.get("content") or [] if c.get("type") == "paragraph"]
                    cells.append(_inline_dict(paragraphs[0]) if paragraphs else {"text": ""})
                if row_index == 0 and all_headers:
                    header = cells
                else:
                    rows.append(cells)
            return [{"type": "table", "headers": header, "rows": rows}]
        return []

    for child in document.get("content") or []:
        blocks.extend(convert(child))
    plain_parts: list[str] = []
    for block in blocks:
        if block["type"] in {"paragraph", "heading", "code"}:
            plain_parts.append(str(block.get("text") or ""))
        elif block["type"] == "list":
            plain_parts.extend(str(item.get("text") or "") for item in block["items"])
        elif block["type"] == "quote":
            plain_parts.extend(str(item.get("text") or "") for item in block["children"])
        elif block["type"] == "table":
            plain_parts.extend(cell.get("text", "") for row in [block["headers"], *block["rows"]] for cell in row)
    plain = re.sub(r"\n{3,}", "\n\n", "\n\n".join(part for part in plain_parts if part)).strip()
    return blocks, plain


def normalize_editor_document(
    document: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if not document:
        return {}, [], ""
    if not isinstance(document, dict):
        raise RichTextValidationError("editor document must be an object")
    if document.get("type") == "html":
        return _html_document_to_blocks(document)
    blocks, plain = document_to_blocks(document)
    return document, blocks, plain
