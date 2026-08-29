from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.models.domain import EventCluster, RawArticle, Source
from app.services.taxonomy import (
    category_label,
    display_category,
    focus_category_label,
    resolve_focus_category,
)
from app.services.x_tweet_articles import display_source_name, display_source_profile



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
        for key in ("width", "height"):
            value = image.get(key)
            if isinstance(value, int) and 0 < value <= 10000:
                cleaned_image[key] = value
        role = str(image.get("role") or "")
        if role in {"hero", "content"}:
            cleaned_image["role"] = role
        fallback_url = str(image.get("fallback_url") or "").strip()
        if _safe_content_url(fallback_url):
            cleaned_image["fallback_url"] = fallback_url
        cleaned.append(cleaned_image)
    return cleaned


def _safe_content_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _safe_youtube_embed_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "www.youtube-nocookie.com"
        and re.fullmatch(r"/embed/[A-Za-z0-9_-]{6,20}", parsed.path) is not None
        and not parsed.query
        and not parsed.fragment
    )


def _safe_x_status_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme.lower() == "https"
        and (parsed.hostname or "").lower() == "x.com"
        and re.fullmatch(
            r"/[A-Za-z0-9_]{1,30}/status/\d+", parsed.path
        )
        is not None
        and not parsed.query
        and not parsed.fragment
    )


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


def _clean_alignment(block: dict[str, Any]) -> dict[str, str]:
    """透传对齐方式。这层是白名单式净化器——**逐字段重建块，没抄的字段就丢了**，
    所以提取器新增字段时这里必须同步，否则数据在库里是对的、接口出来却没有
    （2026-08-07 踩过：加了 align 与微信视频，库里 50 块，接口只出 43 块）。

    只放行 center / right：left 是默认值，justify 前端刻意不支持。
    """
    align = str(block.get("align") or "").strip().lower()
    return {"align": align} if align in {"center", "right"} else {}


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
                cleaned_block.update(_clean_alignment(block))
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
                cleaned_heading.update(_clean_alignment(block))
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
                for key in ("width", "height"):
                    value = block.get(key)
                    if isinstance(value, int) and 0 < value <= 10000:
                        cleaned_image[key] = value
                role = str(block.get("role") or "")
                if role in {"hero", "content"}:
                    cleaned_image["role"] = role
                cleaned.append(cleaned_image)
        elif block_type == "video":
            provider = str(block.get("provider") or "").strip()
            url = str(block.get("url") or "").strip()
            if provider == "youtube":
                if not _safe_youtube_embed_url(url):
                    continue
                cleaned_video: dict[str, Any] = {
                    "type": "video",
                    "provider": "youtube",
                    "url": url,
                }
            elif provider == "file":
                parsed_url = urlsplit(url)
                mime_type = str(block.get("mime_type") or "").strip().lower()
                if (
                    parsed_url.scheme.lower() != "https"
                    or not parsed_url.netloc
                    or mime_type not in {"video/mp4", "video/webm", "video/ogg"}
                ):
                    continue
                cleaned_video = {
                    "type": "video",
                    "provider": "file",
                    "url": url,
                    "mime_type": mime_type,
                }
                poster_url = str(block.get("poster_url") or "").strip()
                if (
                    _safe_content_url(poster_url)
                    and urlsplit(poster_url).scheme.lower() == "https"
                ):
                    cleaned_video["poster_url"] = poster_url
                for key in ("autoplay", "loop", "muted"):
                    if block.get(key) is True:
                        cleaned_video[key] = True
            elif provider == "link":
                # 只有封面可展示、播放要跳原文（微信内嵌视频的直链带签名会过期，
                # 所以不存直链）。这里不放行 mime_type/autoplay 之类——它压根
                # 不是一个能内联播放的源。
                if not _safe_content_url(url):
                    continue
                cleaned_video = {"type": "video", "provider": "link", "url": url}
                poster_url = str(block.get("poster_url") or "").strip()
                if _safe_content_url(poster_url):
                    cleaned_video["poster_url"] = poster_url
            else:
                continue
            for key in ("title", "caption"):
                value = str(block.get(key) or "").strip()
                if value:
                    cleaned_video[key] = value
            for key in ("width", "height"):
                value = block.get(key)
                if isinstance(value, int) and 0 < value <= 10000:
                    cleaned_video[key] = value
            cleaned.append(cleaned_video)
        elif block_type == "social_embed":
            provider = str(block.get("provider") or "").strip()
            url = str(block.get("url") or "").strip()
            if provider != "x" or not _safe_x_status_url(url):
                continue
            cleaned_embed: dict[str, Any] = {
                "type": "social_embed",
                "provider": "x",
                "url": url,
            }
            for key in (
                "author_name",
                "username",
                "text",
                "published_at",
            ):
                value = str(block.get(key) or "").strip()
                if value:
                    cleaned_embed[key] = value
            for key in ("avatar_url", "poster_url"):
                value = str(block.get(key) or "").strip()
                if (
                    _safe_content_url(value)
                    and urlsplit(value).scheme.lower() == "https"
                ):
                    cleaned_embed[key] = value
            video_url = str(block.get("video_url") or "").strip()
            if (
                _safe_content_url(video_url)
                and urlsplit(video_url).scheme.lower() == "https"
                and str(block.get("video_mime_type") or "") == "video/mp4"
            ):
                cleaned_embed["video_url"] = video_url
                cleaned_embed["video_mime_type"] = "video/mp4"
            for key in (
                "reply_count",
                "repost_count",
                "like_count",
                "view_count",
            ):
                value = block.get(key)
                if isinstance(value, int) and 0 <= value <= 10**12:
                    cleaned_embed[key] = value
            cleaned.append(cleaned_embed)
        elif block_type == "byline":
            author_value = block.get("author")
            if not isinstance(author_value, dict):
                continue
            name = str(author_value.get("name") or "").strip()
            if not name:
                continue
            author: dict[str, str] = {"name": name}
            for key in ("url", "avatar_url"):
                value = str(author_value.get(key) or "").strip()
                if _safe_content_url(value):
                    author[key] = value
            cleaned_byline: dict[str, Any] = {"type": "byline", "author": author}
            published_at = str(block.get("published_at") or "").strip()
            if published_at:
                cleaned_byline["published_at"] = published_at
            source_value = block.get("source")
            if isinstance(source_value, dict):
                source_name = str(source_value.get("name") or "").strip()
                if source_name:
                    source: dict[str, str] = {"name": source_name}
                    source_url = str(source_value.get("url") or "").strip()
                    if _safe_content_url(source_url):
                        source["url"] = source_url
                    cleaned_byline["source"] = source
            cleaned.append(cleaned_byline)
        elif block_type == "callout":
            kind = str(block.get("kind") or "note")
            if kind not in {"lead", "note"}:
                kind = "note"
            children = _clean_original_blocks(
                block.get("children"), depth=depth + 1,
                strip_telegram_signatures=strip_telegram_signatures,
            )
            if children:
                cleaned.append({"type": "callout", "kind": kind, "children": children})
        elif block_type == "list":
            values = block.get("items")
            items = []
            if isinstance(values, list):
                for value in values[:100]:
                    if not isinstance(value, dict):
                        continue
                    text = str(value.get("text") or "").strip()
                    if not text:
                        continue
                    item = {"text": text}
                    html = str(value.get("html") or "").strip()
                    if html:
                        item["html"] = html
                    items.append(item)
            if items:
                cleaned.append({"type": "list", "ordered": bool(block.get("ordered")), "items": items})
        elif block_type == "code":
            text = str(block.get("text") or "").strip()
            if text:
                cleaned_code = {"type": "code", "text": text}
                language = str(block.get("language") or "").strip()
                if language:
                    cleaned_code["language"] = language[:40]
                cleaned.append(cleaned_code)
        elif block_type == "table":
            def clean_cells(values: Any) -> list[dict[str, str]]:
                result = []
                if not isinstance(values, list):
                    return result
                for value in values[:20]:
                    if not isinstance(value, dict):
                        continue
                    text = str(value.get("text") or "").strip()
                    if not text:
                        continue
                    cell = {"text": text}
                    html = str(value.get("html") or "").strip()
                    if html:
                        cell["html"] = html
                    result.append(cell)
                return result
            headers = clean_cells(block.get("headers"))
            rows = [clean_cells(row) for row in (block.get("rows") or [])[:100]] if isinstance(block.get("rows"), list) else []
            rows = [row for row in rows if row]
            if headers or rows:
                cleaned.append({"type": "table", "headers": headers, "rows": rows})
        elif block_type == "divider":
            cleaned.append({"type": "divider"})
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
        elif block_type == "callout":
            paragraphs.extend(_plain_paragraphs_from_blocks(block.get("children") or []))
        elif block_type == "list":
            paragraphs.extend(
                str(item.get("text") or "").strip()
                for item in block.get("items") or []
                if str(item.get("text") or "").strip()
            )
        elif block_type == "code":
            text = str(block.get("text") or "").strip()
            if text:
                paragraphs.append(text)
        elif block_type == "table":
            for row in [block.get("headers") or [], *(block.get("rows") or [])]:
                text = " | ".join(
                    str(cell.get("text") or "").strip() for cell in row
                    if str(cell.get("text") or "").strip()
                )
                if text:
                    paragraphs.append(text)
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
        focus = resolve_focus_category(
            processed.focus_category,
            processed.category,
            text=" ".join(
                [
                    str(processed.title_zh or article.title or ""),
                    str(processed.one_line_summary or ""),
                    str(processed.summary_zh or ""),
                    " ".join(str(tag) for tag in processed.tags or []),
                ]
            ),
        )
        items.append(
            {
                "event_id": cluster.id,
                "raw_article_id": article.id,
                "title": processed.title_zh,
                "category": display_category(processed.category),
                "category_label": category_label(processed.category),
                "focus_category": focus,
                "focus_category_label": focus_category_label(focus),
                "scoring_category": processed.category,
                "tags": processed.tags,
                "final_score": cluster.final_score,
                "source_count": cluster.source_count,
                "main_source": {
                    "id": source.id,
                    "name": display_source_name(source.name, article.metadata),
                    "url": article.source_url,
                    "tier": source.tier,
                    "category": source.category,
                    **display_source_profile(article.metadata),
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
        sections.setdefault(item["focus_category"], []).append(item)
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
        lines.append(f"## {focus_category_label(category)}")
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
