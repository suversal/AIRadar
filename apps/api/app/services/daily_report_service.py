from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.models.domain import EventCluster, RawArticle, Source

CATEGORY_LABELS = {
    "model_release": "模型发布/更新",
    "product_release": "产品发布/更新",
    "open_source": "开源项目",
    "research": "论文研究",
    "industry": "行业动态",
    "funding": "融资并购",
    "opinion": "观点",
    "tutorial": "技巧教程",
    "uncategorized": "其他",
}


def selected_clusters(
    clusters: list[EventCluster],
    *,
    top_n: int = 12,
) -> list[EventCluster]:
    return sorted(clusters, key=lambda item: item.final_score, reverse=True)[:top_n]


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
        cleaned.append(
            {
                "url": url,
                "alt": str(image.get("alt") or "").strip(),
                "caption": str(image.get("caption") or "").strip(),
            }
        )
    return cleaned


def _clean_original_blocks(blocks: Any) -> list[dict[str, Any]]:
    if not isinstance(blocks, list):
        return []
    cleaned = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "paragraph":
            text = str(block.get("text") or "").strip()
            if text:
                cleaned.append({"type": "paragraph", "text": text})
        elif block_type == "image":
            url = str(block.get("url") or "").strip()
            if url:
                cleaned.append(
                    {
                        "type": "image",
                        "url": url,
                        "alt": str(block.get("alt") or "").strip(),
                        "caption": str(block.get("caption") or "").strip(),
                    }
                )
    return cleaned


def _original_article_payload(article: RawArticle) -> dict[str, Any]:
    metadata = article.metadata or {}
    raw_paragraphs = metadata.get("original_paragraphs")
    if not isinstance(raw_paragraphs, list):
        raw_paragraphs = []
    paragraphs = [
        str(paragraph).strip()
        for paragraph in raw_paragraphs
        if str(paragraph).strip()
    ]
    if not paragraphs and article.content:
        paragraphs = [article.content]
    images = _clean_original_images(metadata.get("original_images"))
    blocks = _clean_original_blocks(metadata.get("original_blocks"))
    if not blocks:
        blocks = [{"type": "paragraph", "text": paragraph} for paragraph in paragraphs]
        blocks.extend({"type": "image", **image} for image in images)
    original_text = str(metadata.get("original_text") or "").strip()
    if not original_text:
        original_text = "\n\n".join(paragraphs)
    return {
        "original_url": article.source_url,
        "original_content": original_text,
        "original_paragraphs": paragraphs,
        "original_images": images,
        "original_blocks": blocks,
    }


def build_daily_json(
    *,
    report_date: date,
    clusters: list[EventCluster],
    processed_by_article: dict[str, Any],
    articles_by_id: dict[str, RawArticle],
    sources_by_id: dict[str, Source],
    top_n: int = 12,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    items = []
    for cluster in selected_clusters(clusters, top_n=top_n):
        article = articles_by_id[cluster.main_article_id]
        processed = processed_by_article[cluster.main_article_id]
        source = sources_by_id[article.source_id]
        original_payload = _original_article_payload(article)
        items.append(
            {
                "event_id": cluster.id,
                "title": processed.title_zh,
                "category": processed.category,
                "category_label": CATEGORY_LABELS.get(processed.category, processed.category),
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
    top_n: int = 12,
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
        lines.append(f"## {CATEGORY_LABELS.get(category, category)}")
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
