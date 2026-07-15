from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.models.domain import EventCluster, RawArticle, Source
from app.services.taxonomy import category_label, display_category



def selected_clusters(
    clusters: list[EventCluster],
    *,
    processed_by_article: dict[str, Any] | None = None,
    report_date: date | None = None,
    top_n: int | None = None,
) -> list[EventCluster]:
    selected = clusters
    if processed_by_article is not None:
        selected = [
            cluster
            for cluster in selected
            if any(
                bool(getattr(processed_by_article.get(article_id), "selected", False))
                for article_id in cluster.article_ids
            )
        ]
    if report_date is not None:
        shanghai = ZoneInfo("Asia/Shanghai")
        selected = [
            cluster
            for cluster in selected
            if cluster.last_seen_at.astimezone(shanghai).date() == report_date
        ]
    # top_n is intentionally ignored as a temporary call-site compatibility
    # shim. Selection is dynamic; pagination belongs to read APIs, not reports.
    return sorted(
        selected,
        key=lambda item: (item.final_score, item.source_count, item.last_seen_at),
        reverse=True,
    )


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _clean_original_images(images: Any) -> list[dict[str, str]]:
    if not isinstance(images, list):
        return []
    cleaned = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = str(image.get("url") or "").strip()
        if not url:
            continue
        cleaned_image = {
            "url": url,
            "alt": str(image.get("alt") or "").strip(),
            "caption": str(image.get("caption") or "").strip(),
        }
        fallback_url = str(image.get("fallback_url") or "").strip()
        if _safe_content_url(fallback_url):
            cleaned_image["fallback_url"] = fallback_url
        cleaned.append(cleaned_image)
    return cleaned


def _safe_content_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _clean_content_links(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        url = str(value.get("url") or "").strip()
        if not _safe_content_url(url) or url in seen:
            continue
        seen.add(url)
        cleaned.append(
            {
                "label": str(value.get("label") or value.get("host") or url).strip(),
                "url": url,
                "host": str(value.get("host") or urlsplit(url).hostname or "").strip(),
            }
        )
    return cleaned


_LEGACY_TELEGRAM_SIGNATURE_RE = re.compile(
    r"\s*(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]\s*|[·|｜•]\s*)"
    r"[^。！？\n]{0,40}(?:频道|channel)[^。！？\n]{0,120}"
    r"(?:投稿(?:通道|机器人)?|(?:交流群|讨论群|水群)|\b(?:chat|bot)\b).*$",
    re.IGNORECASE,
)


def _strip_legacy_telegram_signature(value: str) -> str:
    return _LEGACY_TELEGRAM_SIGNATURE_RE.sub("", value).rstrip(" ·|｜•")


def _clean_original_blocks(
    blocks: Any,
    *,
    depth: int = 0,
    strip_telegram_signatures: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(blocks, list):
        return []
    if depth > 4:
        return []
    cleaned = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "paragraph":
            text = str(block.get("text") or "").strip()
            original_text = text
            if strip_telegram_signatures:
                text = _strip_legacy_telegram_signature(text)
            if text:
                cleaned_block: dict[str, Any] = {"type": "paragraph", "text": text}
                html = str(block.get("html") or "").strip()
                if html and text == original_text:
                    cleaned_block["html"] = html
                cleaned.append(cleaned_block)
        elif block_type == "heading":
            text = str(block.get("text") or "").strip()
            if text:
                level = block.get("level")
                level = level if isinstance(level, int) and 1 <= level <= 6 else 2
                cleaned_heading: dict[str, Any] = {"type": "heading", "level": level, "text": text}
                html = str(block.get("html") or "").strip()
                if html:
                    cleaned_heading["html"] = html
                cleaned.append(cleaned_heading)
        elif block_type == "image":
            url = str(block.get("url") or "").strip()
            if _safe_content_url(url):
                cleaned_image: dict[str, Any] = {
                    "type": "image",
                    "url": url,
                    "alt": str(block.get("alt") or "").strip(),
                    "caption": str(block.get("caption") or "").strip(),
                }
                fallback_url = str(block.get("fallback_url") or "").strip()
                if _safe_content_url(fallback_url):
                    cleaned_image["fallback_url"] = fallback_url
                cleaned.append(cleaned_image)
        elif block_type == "source_list":
            links = _clean_content_links(block.get("links"))
            if links:
                cleaned.append({"type": "source_list", "links": links})
        elif block_type == "quote":
            kind = str(block.get("kind") or "quote")
            if kind not in {"reply", "update", "quote"}:
                kind = "quote"
            cleaned_quote: dict[str, Any] = {
                "type": "quote",
                "kind": kind,
                "children": _clean_original_blocks(
                    block.get("children"),
                    depth=depth + 1,
                    strip_telegram_signatures=strip_telegram_signatures,
                ),
            }
            for key in ("label", "author"):
                value = str(block.get(key) or "").strip()
                if value:
                    cleaned_quote[key] = value
            source_url = str(block.get("source_url") or "").strip()
            if _safe_content_url(source_url):
                cleaned_quote["source_url"] = source_url
            if cleaned_quote["children"] or cleaned_quote.get("source_url"):
                cleaned.append(cleaned_quote)
    return cleaned


def _plain_paragraphs_from_blocks(blocks: list[dict[str, Any]]) -> list[str]:
    paragraphs: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type in {"paragraph", "heading"}:
            text = str(block.get("text") or "").strip()
            if text:
                paragraphs.append(text)
        elif block_type == "source_list":
            links = block.get("links") or []
            if links:
                paragraphs.append(
                    "文章来源："
                    + " | ".join(str(link.get("label") or link.get("host")) for link in links)
                )
        elif block_type == "quote":
            prefix = {"reply": "回复上文", "update": "更新", "quote": "引用"}.get(
                str(block.get("kind") or "quote"), "引用"
            )
            nested = _plain_paragraphs_from_blocks(block.get("children") or [])
            if nested:
                paragraphs.append(f"[{prefix}] " + "\n".join(nested))
    return paragraphs


def _clean_text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _original_article_payload(article: RawArticle) -> dict[str, Any]:
    metadata = article.metadata or {}
    content_origin = str(metadata.get("content_origin") or "").strip()
    is_telegram_rss = content_origin == "telegram_rss_description"
    raw_paragraphs = metadata.get("original_paragraphs")
    if not isinstance(raw_paragraphs, list):
        raw_paragraphs = []
    paragraphs = [
        str(paragraph).strip()
        for paragraph in raw_paragraphs
        if str(paragraph).strip()
    ]
    if is_telegram_rss:
        paragraphs = [
            cleaned
            for paragraph in paragraphs
            if (cleaned := _strip_legacy_telegram_signature(paragraph))
        ]
    if not paragraphs and article.content:
        paragraphs = [article.content]
    images = _clean_original_images(metadata.get("original_images"))
    blocks = _clean_original_blocks(
        metadata.get("original_blocks"),
        strip_telegram_signatures=is_telegram_rss,
    )
    if not blocks:
        blocks = [{"type": "paragraph", "text": paragraph} for paragraph in paragraphs]
        blocks.extend({"type": "image", **image} for image in images)
    if is_telegram_rss and blocks:
        paragraphs = _plain_paragraphs_from_blocks(blocks)
    original_text = str(metadata.get("original_text") or "").strip()
    if is_telegram_rss and blocks:
        original_text = "\n\n".join(paragraphs)
    if not original_text:
        original_text = "\n\n".join(paragraphs)
    payload = {
        "source_language": article.language,
        "original_url": article.source_url,
        "original_content": original_text,
        "original_paragraphs": paragraphs,
        "original_images": images,
        "original_blocks": blocks,
    }
    original_markdown = str(metadata.get("original_markdown") or "").strip()
    if original_markdown:
        payload["original_markdown"] = original_markdown
    if content_origin:
        payload["content_origin"] = content_origin
    for key in ("readme_name", "readme_language", "readme_selection"):
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[key] = value
    translated_paragraphs = _clean_text_list(metadata.get("translated_paragraphs"))
    translated_blocks = _clean_original_blocks(metadata.get("translated_blocks"))
    if translated_paragraphs:
        payload["translated_paragraphs"] = translated_paragraphs
        payload["translated_content"] = "\n\n".join(translated_paragraphs)
    if translated_blocks:
        payload["translated_blocks"] = translated_blocks
    for key in ("translation_status", "translation_error"):
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[key] = value
    return payload


def build_daily_json(
    *,
    report_date: date,
    clusters: list[EventCluster],
    processed_by_article: dict[str, Any],
    articles_by_id: dict[str, RawArticle],
    sources_by_id: dict[str, Source],
    top_n: int | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    items = []
    for cluster in selected_clusters(
        clusters,
        processed_by_article=processed_by_article,
        report_date=report_date,
        top_n=top_n,
    ):
        article = articles_by_id[cluster.main_article_id]
        processed = processed_by_article[cluster.main_article_id]
        source = sources_by_id[article.source_id]
        original_payload = _original_article_payload(article)
        items.append(
            {
                "event_id": cluster.id,
                "raw_article_id": article.id,
                "title": processed.title_zh,
                "category": display_category(processed.category),
                "category_label": category_label(processed.category),
                "scoring_category": processed.category,
                "tags": processed.tags,
                "final_score": cluster.final_score,
                "source_count": cluster.source_count,
                "main_source": {
                    "name": source.name,
                    "url": article.source_url,
                    "tier": source.tier,
                },
                "one_line_summary": processed.one_line_summary,
                "summary": processed.summary_zh,
                "reason": processed.reason_zh,
                "action": processed.action_zh,
                "published_at": article.published_at.astimezone(timezone.utc).isoformat(),
                **original_payload,
            }
        )
    latest_published_at = max((item["published_at"] for item in items), default=None)
    updated_at = _iso_utc(generated_at) if generated_at else latest_published_at
    sections: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        sections.setdefault(item["category"], []).append(item)
    return {
        "report_date": report_date.isoformat(),
        "title": f"Suversal AI Radar 日报 - {report_date.isoformat()}",
        "summary": f"精选 {len(items)} 条 AI 情报。",
        "updated_at": updated_at,
        "generated_at": updated_at,
        "latest_published_at": latest_published_at,
        "items": items,
        "sections": sections,
        "article_count": len(items),
    }


def render_daily_markdown(
    *,
    report_date: date,
    clusters: list[EventCluster],
    processed_by_article: dict[str, Any],
    articles_by_id: dict[str, RawArticle],
    sources_by_id: dict[str, Source],
    top_n: int | None = None,
    generated_at: datetime | None = None,
) -> str:
    daily = build_daily_json(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=sources_by_id,
        top_n=top_n,
        generated_at=generated_at,
    )
    lines = [
        f"# {daily['title']}",
        "",
        f"> {daily['summary']}风格：少而精，只保留值得进一步阅读的事件。",
        "",
    ]
    for category, items in daily["sections"].items():
        lines.append(f"## {category_label(category)}")
        lines.append("")
        for index, item in enumerate(items, start=1):
            tags = " ".join(f"`{tag}`" for tag in item["tags"])
            lines.extend(
                [
                    f"### {index}. {item['title']} ({item['final_score']:.1f})",
                    "",
                    f"- 摘要：{item['one_line_summary']}",
                    f"- 核心总结：{item['summary']}",
                    f"- 为什么重要：{item['reason']}",
                    f"- 下一步：{item['action']}",
                    (
                        f"- 来源：[{item['main_source']['name']}]"
                        f"({item['main_source']['url']})，"
                        f"{item['main_source']['tier']}，相关来源 {item['source_count']} 个"
                    ),
                    f"- 标签：{tags}",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"
