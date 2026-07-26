from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.crawlers.base import normalize_article, stable_hash
from app.crawlers.article_content import content_extraction_version_for_url
from app.crawlers.github_readme import fetch_github_readme, repo_path_from_github_url
from app.models.domain import (
    DailyReport,
    PipelineResult,
    ProcessedArticle,
    RawArticle,
    ScoreDimensions,
    ScoringResult,
    Source,
)
from app.services.ai_service import FakeAIProvider, embedding_input
from app.services.clustering_service import cluster_articles
from app.services.daily_report_service import build_daily_json, render_daily_markdown
from app.services.scoring_service import select_processed_article
from app.services.source_policy import (
    FORCE_SELECTION_ALWAYS,
    FORCE_SELECTION_NEVER,
    forced_selection,
    is_trusted_curated_source,
    is_unfetchable_article_domain,
)

logger = logging.getLogger(__name__)

# Total translation budget per article. Real full-page content now commonly
# runs 3000-14000 chars (HF/bair/venturebeat observed up to ~14000), so this
# needs to comfortably cover a complete long-form article, not just a feed
# summary. There is deliberately no separate paragraph-count cap: capping at
# a fixed number of paragraphs (the old TRANSLATION_PARAGRAPH_LIMIT=12) cuts
# long articles off after a handful of headings, leaving the real body
# untranslated regardless of how much char budget remains.
TRANSLATION_CHAR_LIMIT = 20000
# Chinese output tokens roughly track input chars, so keep each provider call
# well under the smallest chat max_tokens (2048) to avoid truncated JSON.
TRANSLATION_CHUNK_CHAR_LIMIT = 1600

# The RSS crawler always writes these keys (even as empty list/string) when it
# parses the feed's own thin summary, so a plain `setdefault` never lets the
# cached (previously fully-extracted) value win. These need "use cached value
# only if this round's is falsy" instead of "use cached value only if absent".
_CACHED_CONTENT_STRUCTURE_KEYS = (
    "original_paragraphs",
    "original_blocks",
    "original_text",
    "original_images",
)


_SENTENCE_BOUNDARIES = ("。", "！", "？", ". ", "! ", "? ", "; ", "；")


def _split_long_paragraph(paragraph: str, limit: int) -> list[str]:
    pieces: list[str] = []
    remaining = paragraph
    while len(remaining) > limit:
        cut = max(
            remaining.rfind(boundary, limit // 2, limit) + len(boundary.rstrip())
            for boundary in _SENTENCE_BOUNDARIES
        )
        if cut <= 0:
            cut = limit
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _translate_in_chunks(
    translate: Any,
    paragraphs: list[str],
    *,
    chunk_char_limit: int = TRANSLATION_CHUNK_CHAR_LIMIT,
) -> list[str]:
    translated: list[str] = []
    chunk: list[str] = []
    chunk_chars = 0

    def translate_with_retry(batch: list[str]) -> list[str]:
        # long articles now split into many chunks; one transient provider
        # hiccup ("Chat response content is empty" and similar) should not
        # void translation of the entire article. Real-world evidence: 3
        # articles in one refresh all failed with the identical error,
        # which points to load/rate-limiting rather than a random one-off -
        # a bare immediate retry would likely hit the same limit window, so
        # back off briefly first.
        try:
            return translate(batch)
        except Exception:
            time.sleep(2.0)
            return translate(batch)

    def translate_with_fallback(batch: list[str]) -> list[str]:
        try:
            return translate_with_retry(batch)
        except Exception:
            # Some providers return a truncated/invalid JSON response even when
            # the request is below our normal chunk limit. Retrying the exact
            # same payload cannot repair a deterministic output-size failure,
            # so make one bounded fallback pass with half-sized requests while
            # preserving the one-output-per-input-paragraph contract.
            fallback_limit = max(1, chunk_char_limit // 2)
            can_subdivide = len(batch) > 1 or any(
                len(paragraph) > fallback_limit for paragraph in batch
            )
            if not can_subdivide:
                raise

            logger.warning(
                "translation chunk failed after retry; falling back to smaller requests"
            )
            recovered: list[str] = []
            for paragraph in batch:
                pieces = _split_long_paragraph(paragraph, fallback_limit)
                translated_pieces: list[str] = []
                for piece in pieces:
                    translated_pieces.extend(translate_with_retry([piece]))
                recovered.append("".join(translated_pieces))
            return recovered

    def flush() -> None:
        nonlocal chunk, chunk_chars
        if chunk:
            translated.extend(translate_with_fallback(chunk))
            chunk = []
            chunk_chars = 0

    for paragraph in paragraphs:
        if len(paragraph) > chunk_char_limit:
            # a single oversized paragraph cannot fit any batch: translate its
            # sentence slices separately and rejoin them as one paragraph
            flush()
            pieces = _split_long_paragraph(paragraph, chunk_char_limit)
            translated_pieces: list[str] = []
            for piece in pieces:
                translated_pieces.extend(translate_with_fallback([piece]))
            translated.append("".join(translated_pieces))
            continue
        if chunk and chunk_chars + len(paragraph) > chunk_char_limit:
            flush()
        chunk.append(paragraph)
        chunk_chars += len(paragraph)
    flush()
    return translated


def dedupe_articles(articles: list[RawArticle]) -> list[RawArticle]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[RawArticle] = []
    for article in articles:
        if article.url_hash in seen_urls or article.title_hash in seen_titles:
            continue
        seen_urls.add(article.url_hash)
        seen_titles.add(article.title_hash)
        deduped.append(article)
    return deduped


def _cached_scoring_result(cached: dict[str, Any] | None) -> ScoringResult | None:
    if not cached:
        return None
    scoring = cached.get("scoring")
    if not scoring:
        return None
    dimensions = scoring.get("dimensions") or {}
    try:
        return ScoringResult(
            dimensions=ScoreDimensions(
                ai_relevance=float(dimensions["ai_relevance"]),
                novelty=float(dimensions["novelty"]),
                impact=float(dimensions["impact"]),
                information_density=float(dimensions["information_density"]),
                actionability=float(dimensions["actionability"]),
                creator_value=float(dimensions["creator_value"]),
            ),
            category=str(scoring["category"]),
            tags=[str(tag) for tag in scoring.get("tags") or []],
            title_zh=str(scoring["title_zh"]),
            one_line_summary=str(scoring["one_line_summary"]),
            summary_zh=str(scoring["summary_zh"]),
            reason_zh=str(scoring["reason_zh"]),
            action_zh=str(scoring["action_zh"]),
            focus_category=(
                str(scoring["focus_category"])
                if scoring.get("focus_category")
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def source_recent_days(source: Source) -> int:
    """信源的抓取回溯天数(config.recent_days,默认 1 天=仅当天,2026-07-15
    从固定"仅当天"改为可配置;同日追加 0=不限日期的统一约定,取代原来
    单独的 config.ingest_all_dates 布尔开关):非法或负值一律回退到 1,
    保持改造前的默认行为不变。"""
    value = (source.config or {}).get("recent_days", 1)
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 1
    return days if days >= 0 else 1


def filter_articles_published_on(
    articles: list[RawArticle],
    report_date: date,
    *,
    exempt_source_ids: set[str] | frozenset = frozenset(),
    recent_days_by_source: dict[str, int] | None = None,
) -> list[RawArticle]:
    """只处理发布日期(上海时区)落在[报告日期 - (N-1)天, 报告日期]窗口内的
    文章(2026-07-12 深夜决策,2026-07-15 从固定"仅当天"改为按信源配置的
    最近 N 天):N 由 recent_days_by_source 按 source_id 提供,缺失时视为
    1(即仅当天,与改造前行为一致);N=0 表示不限日期,全部保留(2026-07-15
    起 AI HOT 的两个精选源用这个统一表达,取代原来专属的
    config.ingest_all_dates 开关)。feed 里超出窗口的陈年存量一概出局。
    published_at 为 None 的保留——GitHub Trending 这类聚合器条目本质上就
    是"当前"。exempt_source_ids 仍保留给其他"全量保留"场景(如
    attentionvc_x 的滚动趋势窗口)使用,与 recent_days=0 是两条并存的
    豁免路径;判重仍由 url_hash 兜底。"""
    from zoneinfo import ZoneInfo

    shanghai = ZoneInfo("Asia/Shanghai")
    recent_days_by_source = recent_days_by_source or {}
    kept: list[RawArticle] = []
    for article in articles:
        if article.source_id in exempt_source_ids:
            kept.append(article)
            continue
        if recent_days_by_source.get(article.source_id, 1) == 0:
            kept.append(article)
            continue
        published = article.published_at
        if published is None:
            kept.append(article)
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        published_date = published.astimezone(shanghai).date()
        window_start = report_date - timedelta(
            days=recent_days_by_source.get(article.source_id, 1) - 1
        )
        if window_start <= published_date <= report_date:
            kept.append(article)
    return kept


def _notify_article_processed(callback: Any, article: RawArticle, processed, embedding) -> None:
    """逐条即时落库回调(2026-07-12 深夜决策):每成功评分一条立即通知
    保存,数据库持续增长。best-effort——回调异常绝不炸整轮,最终整轮
    落库仍会补齐一切;跳过类结果不回调。"""
    if callback is None or processed is None:
        return
    try:
        callback(article, processed, embedding)
    except Exception:
        pass


def _process_candidate_article(
    *,
    article: RawArticle,
    source_by_id: dict[str, Source],
    ai_provider: Any,
    now: datetime,
    skip_prefilter: bool = False,
    cached: dict[str, Any] | None = None,
) -> tuple[ProcessedArticle | None, list[float] | None, str | None]:
    # 四步流程(2026-07-12 晚):已存在跳过 → feed 元数据预筛 → 通过后才
    # 拉正文 → 无正文拦截 → 评分。非 AI 文章零外站请求。
    source = source_by_id[article.source_id]
    trusted_curated = is_trusted_curated_source(source)
    cached_version = int(((cached or {}).get("metadata") or {}).get("content_extraction_version") or 0)
    required_extraction_version = content_extraction_version_for_url(article.source_url)
    cached_content_stale = (
        bool(cached)
        and article.metadata.get("body_fetch") == "deferred"
        and cached_version < required_extraction_version
    )
    if cached_content_stale:
        # The visible text can stay identical while the semantic block shape
        # changes (for example, arXiv v4 removed a cached byline but retained
        # the same abstract). A text-only translation hash would incorrectly
        # keep the old translated_blocks, so a content-extractor upgrade must
        # invalidate all translation artifacts together with scoring.
        for key in (
            "translated_paragraphs",
            "translated_blocks",
            "translated_text",
            "translation_source_hash",
            "translation_source_language",
            "translation_target_language",
            "translation_status",
            "translation_error",
        ):
            article.metadata.pop(key, None)
    # A source-profile upgrade means the previous AI fields were generated
    # from the wrong/partial body too. Reusing them after refreshing only the
    # raw HTML would leave a correct detail body paired with a stale title and
    # summary, so invalidate scoring together with the extracted content.
    scoring = None if cached_content_stale else _cached_scoring_result(cached)
    scoring_was_cached = scoring is not None
    # 库里已判非AI的文章(不入选、仅作跳过标记)直接跳过,不再花任何调用
    if scoring is None and cached and cached.get("skipped_reason") == "not_ai_related":
        article.status = "skipped"
        article.skipped_reason = "not_ai_related"
        return None, None, "not_ai_related"

    if scoring is None and not skip_prefilter and not trusted_curated:
        # 用 feed 提供的标题+摘要判断 AI 相关性;HN 外链帖此时只有标题,
        # 判断主题相关性足够
        prefilter = ai_provider.prefilter(f"{article.title}\n{article.content[:500]}")
        if not prefilter.is_ai_related:
            article.status = "skipped"
            article.skipped_reason = "not_ai_related"
            return None, None, "not_ai_related"

    # 通过预筛(或可信源/复用缓存)后,才为 deferred 文章拉取原文页
    if article.metadata.pop("body_fetch", None) == "deferred" and (
        scoring is None or cached_version < required_extraction_version
    ):
        aihot_permalink = article.metadata.get("aihot_permalink")
        if aihot_permalink:
            # AI HOT already extracted + translated this article themselves -
            # reuse their result instead of fetching the third-party original
            # and running our own translation pipeline on it
            from app.crawlers.aihot_content import fetch_aihot_item_content

            # article.source_url is already the third-party "阅读原文" target
            # (rss.py's _original_url_from_description overrides it before
            # normalize_article runs), not AI HOT's own permalink - if that
            # target is a known unscrapable host (WeChat), AI HOT's own
            # /items/{id} page can itself end up rendering a verification-
            # wall artifact instead of real content, so don't trust the
            # extracted payload at all; keep the RSS-stage aihot_summary_zh
            # and let the frontend fall back to a link-out-only display
            if is_unfetchable_article_domain(article.source_url):
                article.metadata["content_origin"] = "aihot_item_page_link_only"
            else:
                payload = fetch_aihot_item_content(aihot_permalink)
                if payload:
                    article.content = payload["content"]
                    article.metadata.update(payload["metadata"])
                    article.metadata["content_origin"] = "aihot_item_page"
                    # AI HOT sources are hardcoded language="zh" at
                    # ingestion, but the actually-extracted original can turn
                    # out to be English (or vice versa) - without this, the
                    # generic translation fallback below (gated on
                    # article.language) never fires for AI HOT articles whose
                    # own bundled translation is missing
                    if payload.get("language"):
                        article.language = payload["language"]
        else:
            from app.crawlers.page_content import prefer_full_page_content

            prefer_full_page_content(article)

    # 无正文门槛移到拉取之后:拉取失败仍是标题-only 的,绝不进入完整
    # 评分(LLM 对着一句标题也能编出高分),详情页也会是空的
    content = (article.content or "").strip()
    if scoring is None and (not content or content == (article.title or "").strip()):
        article.status = "skipped"
        article.skipped_reason = "no_content"
        return None, None, "no_content"

    if scoring is None:
        try:
            scoring = ai_provider.score_article(article.title, article.content)
        except Exception:
            if not trusted_curated:
                raise
            scoring = _trusted_curated_fallback_scoring(article)
            article.metadata["ai_fallback"] = "score_error"
    processed = select_processed_article(
        article=article,
        source=source,
        dimensions=scoring.dimensions,
        category=scoring.category,
        tags=scoring.tags,
        generated_fields={
            "title_zh": scoring.title_zh,
            "one_line_summary": scoring.one_line_summary,
            "summary_zh": scoring.summary_zh,
            "reason_zh": scoring.reason_zh,
            "action_zh": scoring.action_zh,
        },
        now=now,
        source_count=1,
        focus_category=scoring.focus_category,
    )
    forced = forced_selection(source)
    if forced == FORCE_SELECTION_ALWAYS:
        processed = replace(
            processed,
            selected=True,
            status="processed",
            rejection_reason=None,
            selection_origin="curated_source",
            selection_reason=f"force_selection:always:{source.id}",
        )
    elif forced == FORCE_SELECTION_NEVER:
        processed = replace(
            processed,
            selected=False,
            status="rejected",
            rejection_reason=f"force_selection:never:{source.id}",
            selection_origin="curated_source",
            selection_reason=None,
        )
    # AI HOT's own RSS description already IS a written-by-them summary -
    # use it verbatim instead of our own AI-generated one
    aihot_summary_zh = article.metadata.get("aihot_summary_zh")
    if aihot_summary_zh:
        processed = replace(processed, summary_zh=aihot_summary_zh)
    # Telegram RSS titles are editorial copy from the channel and are the
    # product-visible headline. AI still generates summary/reason/category,
    # but must never silently rewrite the RSS title (including its emoji and
    # reply/update markers).
    rss_title = article.metadata.get("rss_title")
    if article.metadata.get("source_type") == "telegram_rss" and rss_title:
        processed = replace(processed, title_zh=str(rss_title).strip())
    # 缓存文章直接复用库里的向量:重算既浪费 CPU,又会在内容有差异时
    # 用劣质向量覆盖全文向量
    cached_embedding = (cached or {}).get("embedding") if scoring_was_cached else None
    embedding_source_hash = stable_hash(embedding_input(article.title, article.content))
    cached_embedding_source_hash = (cached or {}).get("embedding_source_hash")
    cached_version = int(((cached or {}).get("metadata") or {}).get("content_extraction_version") or 0)
    if cached_embedding and (
        cached_embedding_source_hash == embedding_source_hash
        or (cached_embedding_source_hash is None and cached_version == 0)
    ):
        # 双保险转纯 float:上游任何 numpy 标量混进相似度/JSON 都会炸
        embedding = [float(value) for value in cached_embedding]
    else:
        try:
            embedding = ai_provider.embed_text(
                embedding_input(article.title, article.content)
            )
        except Exception:
            if not trusted_curated:
                raise
            embedding = None
            article.metadata["ai_fallback"] = "embedding_error"
    skipped_reason = None if processed.selected else "below_threshold"
    return processed, embedding, skipped_reason


def _trusted_curated_fallback_scoring(article: RawArticle) -> ScoringResult:
    category_map = {
        "AI 产品": "product_release",
        "模型发布": "model_release",
        "开源项目": "open_source",
        "论文": "research",
        "研究": "research",
        "技巧观点": "opinion",
        "行业动态": "industry",
    }
    feed_category = str(article.metadata.get("feed_category") or "").strip()
    summary = (article.content or article.title).strip()
    is_telegram = article.metadata.get("source_type") == "telegram_rss"
    source_tag = "Telegram" if is_telegram else "AI HOT"
    reason = (
        f"来自可信精选信源“{article.source_name}”，模型处理失败后保留原始信息。"
        if is_telegram
        else "来自 AI HOT 每日精编候选池，模型处理失败后保留原始信息。"
    )
    return ScoringResult(
        dimensions=ScoreDimensions(8, 5, 5, 5, 4, 4),
        category=category_map.get(feed_category, "industry"),
        tags=[tag for tag in [feed_category, source_tag] if tag],
        title_zh=article.title,
        one_line_summary=summary[:120],
        summary_zh=summary[:500],
        reason_zh=reason,
        action_zh="阅读原文并核对一手来源。",
        focus_category=None,
    )


def _safe_process_candidate_article(
    *,
    article: RawArticle,
    source_by_id: dict[str, Source],
    ai_provider: Any,
    now: datetime,
    skip_prefilter: bool = False,
    cached: dict[str, Any] | None = None,
) -> tuple[ProcessedArticle | None, list[float] | None, str | None]:
    try:
        return _process_candidate_article(
            article=article,
            source_by_id=source_by_id,
            ai_provider=ai_provider,
            now=now,
            skip_prefilter=skip_prefilter,
            cached=cached,
        )
    except Exception as exc:  # one flaky AI response must not kill the whole run
        article.status = "skipped"
        article.skipped_reason = "ai_error"
        article.metadata["ai_error"] = str(exc)[:200]
        return None, None, "ai_error"


def translation_source_hash(paragraphs: list[str]) -> str:
    from app.crawlers.base import stable_hash

    return stable_hash("\n".join(paragraphs))[:16]


def _translation_paragraphs_for(article: RawArticle) -> list[str]:
    text_blocks = _text_blocks_for_translation(article)
    paragraphs: list[str] = []
    used_chars = 0
    for block in text_blocks:
        paragraph = str(block.get("text") or "").strip()
        if not paragraph:
            continue
        if used_chars + len(paragraph) > TRANSLATION_CHAR_LIMIT:
            remaining = TRANSLATION_CHAR_LIMIT - used_chars
            if remaining <= 0:
                break
            paragraph = paragraph[:remaining].strip()
        paragraphs.append(paragraph)
        used_chars += len(paragraph)
    return paragraphs


def _text_blocks_for_translation(article: RawArticle) -> list[dict[str, Any]]:
    blocks = article.metadata.get("original_blocks") if article.metadata else None
    if isinstance(blocks, list):
        translate_code_blocks = article.source_id != "google_ai_blog"

        def collect(values: list[Any]) -> list[dict[str, Any]]:
            collected: list[dict[str, Any]] = []
            for block in values:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if (
                    block_type in ("paragraph", "heading")
                    or (block_type == "code" and translate_code_blocks)
                ) and str(
                    block.get("text") or ""
                ).strip():
                    collected.append(block)
                elif block_type in {"quote", "callout"} and isinstance(block.get("children"), list):
                    collected.extend(collect(block["children"]))
                elif block_type == "list":
                    collected.extend(
                        {"type": "paragraph", "text": str(item.get("text") or "")}
                        for item in block.get("items") or [] if isinstance(item, dict)
                    )
                elif block_type == "table":
                    rows = [block.get("headers") or [], *(block.get("rows") or [])]
                    collected.extend(
                        {"type": "paragraph", "text": str(cell.get("text") or "")}
                        for row in rows for cell in row if isinstance(cell, dict)
                    )
            return collected

        text_blocks = collect(blocks)
        if text_blocks:
            return text_blocks
    paragraphs = article.metadata.get("original_paragraphs") if article.metadata else None
    if isinstance(paragraphs, list):
        text_blocks = [
            {"type": "paragraph", "text": str(paragraph).strip()}
            for paragraph in paragraphs
            if str(paragraph).strip()
        ]
        if text_blocks:
            return text_blocks
    if article.content.strip():
        return [{"type": "paragraph", "text": article.content.strip()}]
    return []


def _translated_blocks_for(article: RawArticle, translated_paragraphs: list[str]) -> list[dict[str, Any]]:
    source_blocks = article.metadata.get("original_blocks") if article.metadata else None
    if isinstance(source_blocks, list) and source_blocks:
        paragraph_index = [0]

        def next_text() -> str | None:
            if paragraph_index[0] >= len(translated_paragraphs):
                return None
            value = translated_paragraphs[paragraph_index[0]]
            paragraph_index[0] += 1
            return value

        def translate(values: list[Any]) -> list[dict[str, Any]]:
            translated: list[dict[str, Any]] = []
            for block in values:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type in ("paragraph", "heading"):
                    text = next_text()
                    if text is None:
                        continue
                    translated_block: dict[str, Any] = {
                        "type": block_type,
                        "text": text,
                    }
                    if block_type == "heading":
                        level = block.get("level")
                        translated_block["level"] = (
                            level if isinstance(level, int) and 1 <= level <= 6 else 2
                        )
                    translated.append(translated_block)
                elif block_type == "image":
                    url = str(block.get("url") or "").strip()
                    if url:
                        translated.append(
                            {
                                key: value
                                for key, value in block.items()
                                if key in {"type", "url", "alt", "caption", "fallback_url", "width", "height", "role"}
                            }
                        )
                elif block_type == "video":
                    url = str(block.get("url") or "").strip()
                    if url:
                        translated.append(
                            {
                                key: value
                                for key, value in block.items()
                                if key
                                in {
                                    "type",
                                    "provider",
                                    "url",
                                    "title",
                                    "caption",
                                    "mime_type",
                                    "poster_url",
                                    "width",
                                    "height",
                                    "autoplay",
                                    "loop",
                                    "muted",
                                }
                            }
                        )
                elif block_type == "social_embed":
                    url = str(block.get("url") or "").strip()
                    if url:
                        translated.append(
                            {
                                key: value
                                for key, value in block.items()
                                if key
                                in {
                                    "type",
                                    "provider",
                                    "url",
                                    "author_name",
                                    "username",
                                    "avatar_url",
                                    "text",
                                    "published_at",
                                    "video_url",
                                    "video_mime_type",
                                    "poster_url",
                                    "reply_count",
                                    "repost_count",
                                    "like_count",
                                    "view_count",
                                }
                            }
                        )
                elif block_type == "byline" or block_type == "divider":
                    translated.append(dict(block))
                elif block_type == "source_list":
                    translated.append(dict(block))
                elif block_type in {"quote", "callout"}:
                    translated_quote = {
                        key: value
                        for key, value in block.items()
                        if key in {"type", "kind", "label", "author", "source_url"}
                    }
                    translated_quote["children"] = translate(block.get("children") or [])
                    translated.append(translated_quote)
                elif block_type == "list":
                    items = []
                    for item in block.get("items") or []:
                        text = next_text()
                        if text is not None:
                            items.append({"text": text})
                    if items:
                        translated.append({"type": "list", "ordered": bool(block.get("ordered")), "items": items})
                elif block_type == "code":
                    if article.source_id == "google_ai_blog":
                        text = str(block.get("text") or "").strip()
                    else:
                        text = next_text()
                    if text is None or not text:
                        continue
                    translated_code = {"type": "code", "text": text}
                    if block.get("language"):
                        translated_code["language"] = block["language"]
                    translated.append(translated_code)
                elif block_type == "table":
                    def translated_cells(values: list[Any]) -> list[dict[str, str]]:
                        cells = []
                        for _ in values:
                            text = next_text()
                            if text is not None:
                                cells.append({"text": text})
                        return cells
                    headers = translated_cells(block.get("headers") or [])
                    rows = [translated_cells(row) for row in block.get("rows") or []]
                    translated.append({"type": "table", "headers": headers, "rows": rows})
            return translated

        translated_blocks = translate(source_blocks)
        if translated_blocks:
            return translated_blocks
    return [{"type": "paragraph", "text": paragraph} for paragraph in translated_paragraphs]


def _is_github_trending_article(article: RawArticle) -> bool:
    return (
        article.metadata.get("source_type") == "github_trending"
        or article.source_id == "github_trending_ai"
        # any source (HN, RSS, etc.) can link directly to a GitHub repo;
        # README enrichment shouldn't depend on which crawler discovered it
        or bool(repo_path_from_github_url(article.source_url))
    )


def _attach_github_readmes(
    *,
    articles: list[RawArticle],
) -> None:
    """Enrich every processed GitHub trending article with its README.

    Below-threshold articles are still browsable through /all and the
    event detail API, so README enrichment must not depend on daily
    report selection.
    """
    for article in articles:
        if not _is_github_trending_article(article):
            continue
        if article.metadata.get("readme_status") == "ok" and (
            # zh_probe 为 ok/none 才是终态；failed（限流/网络中断）和
            # 缺字段（修复前的老数据）都要重试，让中文优先自愈
            article.metadata.get("readme_zh_probe") in ("ok", "none")
        ):
            continue

        repo_path = str(article.metadata.get("repo") or "").strip()
        if not repo_path:
            repo_path = repo_path_from_github_url(article.source_url)
        readme_payload = fetch_github_readme(repo_path)
        if readme_payload.get("readme_status") == "ok":
            article.metadata.setdefault("repo_description", article.content)
            article.metadata.update(readme_payload)
        else:
            article.metadata.update(readme_payload)


def _embedding_model_name(ai_provider: Any) -> str:
    return getattr(ai_provider, "model_name", None) or getattr(ai_provider, "embedding_model", None) or "unknown"


def _translate_one_article(article: RawArticle, translate: Any) -> None:
    if not article.language.lower().startswith("en"):
        return
    if str(article.metadata.get("readme_language") or "").lower() == "zh":
        return
    if _is_github_trending_article(article) and str(article.metadata.get("original_markdown") or "").strip():
        return

    paragraphs = _translation_paragraphs_for(article)
    if not paragraphs:
        return

    source_hash = translation_source_hash(paragraphs)
    has_translation = bool(
        article.metadata.get("translated_blocks")
        or article.metadata.get("translated_paragraphs")
    )
    # a cached translation is only valid for the exact source text it was
    # made from; content upgrades (e.g. full-page fetch replacing a thin
    # feed summary) must trigger retranslation
    if has_translation and article.metadata.get("translation_source_hash") == source_hash:
        # The source-text hash deliberately ignores media so replacing an
        # expired proxy URL with the canonical image URL does not spend
        # another AI translation call.  The structured translation must
        # still be rebuilt from the latest original blocks, though; otherwise
        # cached translated_blocks keep stale image/video URLs even while the
        # original view has already moved to the repaired media.
        cached_paragraphs = [
            str(paragraph)
            for paragraph in article.metadata.get("translated_paragraphs") or []
            if str(paragraph).strip()
        ]
        if cached_paragraphs:
            article.metadata["translated_blocks"] = _translated_blocks_for(
                article,
                cached_paragraphs,
            )
        return

    try:
        translated_paragraphs = _translate_in_chunks(translate, paragraphs)
    except Exception as exc:
        article.metadata["translation_status"] = "failed"
        article.metadata["translation_error"] = str(exc)[:200]
        # silent otherwise: has_translation stays False so this article is
        # simply retried on the next pipeline run - this log is only so
        # operators can see *why* a given refresh left some articles without
        # a 原文/译文 toggle, not a behavior change
        logger.warning(
            "translation failed for article id=%s source_url=%s: %s",
            article.id,
            article.source_url,
            exc,
        )
        return
    if not translated_paragraphs:
        return

    article.metadata["translated_paragraphs"] = translated_paragraphs
    article.metadata["translated_blocks"] = _translated_blocks_for(article, translated_paragraphs)
    article.metadata["translation_source_language"] = article.language
    article.metadata["translation_target_language"] = "zh"
    article.metadata["translation_source_hash"] = source_hash


def _translate_processed_english_articles(
    *,
    articles: list[RawArticle],
    ai_provider: Any,
    ai_concurrency: int = 1,
) -> None:
    """Translate every processed English article, not only report-selected
    cluster mains: below-threshold articles stay browsable through /all and
    the event detail page, where the 原文/译文 toggle needs a translation.

    Each article's translation is independent (own metadata dict, own AI
    calls), so this mirrors the scoring phase's ThreadPoolExecutor pattern -
    translating every processed article sequentially was the dominant cost
    once every article (not just the report's top N) needed full-length
    translation."""
    translate = getattr(ai_provider, "translate_paragraphs", None)
    if not callable(translate):
        return

    max_workers = max(1, ai_concurrency)
    if max_workers == 1:
        for article in articles:
            _translate_one_article(article, translate)
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_translate_one_article, article, translate) for article in articles]
        for future in as_completed(futures):
            future.result()


def _hydrate_article_from_cache(article: RawArticle, cached: dict[str, Any]) -> None:
    """Reuse persisted identity, full content, and expensive derived metadata.

    Shared by the full pipeline and manual per-source sync so both paths make
    the same cache decision before scoring and translation.
    """
    persisted_id = str(cached.get("raw_article_id") or "").strip()
    if persisted_id:
        article.id = persisted_id
    cached_language = str(cached.get("language") or "").strip()
    if cached_language:
        article.language = cached_language
    cached_metadata = cached.get("metadata") or {}
    for key, value in cached_metadata.items():
        if key in _CACHED_CONTENT_STRUCTURE_KEYS:
            continue
        article.metadata.setdefault(key, value)
    cached_extraction_version = int(cached_metadata.get("content_extraction_version") or 0)
    incoming_extraction_version = int(
        article.metadata.get("content_extraction_version") or 0
    )
    needs_deferred_fetch = article.metadata.get("body_fetch") == "deferred"
    required_extraction_version = content_extraction_version_for_url(article.source_url)
    reuse_cached_content = cached_extraction_version >= required_extraction_version or (
        not needs_deferred_fetch
        and incoming_extraction_version < required_extraction_version
    )
    if reuse_cached_content:
        for key in _CACHED_CONTENT_STRUCTURE_KEYS:
            if not article.metadata.get(key) and cached_metadata.get(key):
                article.metadata[key] = cached_metadata[key]
    cached_content = cached.get("content") or ""
    if reuse_cached_content and len(cached_content) > len(article.content or ""):
        article.content = cached_content


def run_pipeline(
    *,
    sources: list[Source],
    raw_items_by_source: dict[str, list[dict]],
    ai_provider: FakeAIProvider,
    now: datetime,
    report_date: date,
    top_n: int | None = None,
    ai_concurrency: int = 1,
    skip_prefilter: bool = False,
    cached_results: dict[str, dict[str, Any]] | None = None,
    cluster_similarity_threshold: float = 0.85,
    on_article_processed: Any = None,
) -> PipelineResult:
    source_by_id = {source.id: source for source in sources}
    cached_results = cached_results or {}
    raw_articles: list[RawArticle] = []
    skipped = Counter()

    for source_id, raw_items in raw_items_by_source.items():
        source = source_by_id[source_id]
        for item in raw_items:
            article = normalize_article(source=source, **item)
            cached = cached_results.get(article.url_hash)
            if cached:
                _hydrate_article_from_cache(article, cached)
            raw_articles.append(article)

    # 只处理最近 N 天发布(2026-07-12 深夜决策,2026-07-15 从固定"仅当天"
    # 改为按信源 config.recent_days 配置):feed 的陈年存量在这里出局,
    # 不入库、不进统计;总量由日期窗口天然约束,不再依赖每源条数配置
    raw_articles = filter_articles_published_on(
        raw_articles,
        report_date,
        exempt_source_ids={
            source.id
            for source in sources
            if (source.config or {}).get("ingest_all_dates")
        },
        recent_days_by_source={source.id: source_recent_days(source) for source in sources},
    )
    raw_articles = dedupe_articles(raw_articles)
    candidate_articles = list(raw_articles)
    skipped_reason_by_raw_id: dict[str, str] = {}

    processed_articles: list[ProcessedArticle] = []
    embeddings: dict[str, list[float]] = {}
    stage_timings: dict[str, float] = {}
    stage_started = time.perf_counter()

    max_workers = max(1, ai_concurrency)
    candidate_results: list[
        tuple[int, RawArticle, ProcessedArticle | None, list[float] | None, str | None]
    ] = []
    if max_workers == 1:
        for index, article in enumerate(candidate_articles):
            processed, embedding, skipped_reason = _safe_process_candidate_article(
                article=article,
                source_by_id=source_by_id,
                ai_provider=ai_provider,
                now=now,
                skip_prefilter=skip_prefilter,
                cached=cached_results.get(article.url_hash),
            )
            candidate_results.append((index, article, processed, embedding, skipped_reason))
            _notify_article_processed(on_article_processed, article, processed, embedding)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _safe_process_candidate_article,
                    article=article,
                    source_by_id=source_by_id,
                    ai_provider=ai_provider,
                    now=now,
                    skip_prefilter=skip_prefilter,
                    cached=cached_results.get(article.url_hash),
                ): (index, article)
                for index, article in enumerate(candidate_articles)
            }
            for future in as_completed(futures):
                index, article = futures[future]
                processed, embedding, skipped_reason = future.result()
                candidate_results.append((index, article, processed, embedding, skipped_reason))
                # 主线程串行通知,回调内的 DB 会话无并发问题
                _notify_article_processed(on_article_processed, article, processed, embedding)

    for _, article, processed, embedding, skipped_reason in sorted(
        candidate_results,
        key=lambda item: item[0],
    ):
        if skipped_reason:
            skipped[skipped_reason] += 1
            skipped_reason_by_raw_id[article.id] = skipped_reason
        if processed is None:
            continue
        processed_articles.append(processed)
        if embedding is not None:
            embeddings[article.id] = embedding

    stage_timings["ai_candidates"] = round(time.perf_counter() - stage_started, 3)
    stage_started = time.perf_counter()

    final_scores = {
        processed.raw_article_id: processed.final_score for processed in processed_articles
    }
    # Cluster every genuinely selected article. There is no fixed report size
    # and no low-score fill path: the event graph is the selection boundary.
    processed_ids = {processed.raw_article_id for processed in processed_articles}
    # Cluster all scored articles so a trusted-curated member can select an
    # event whose preferred main article is an official/original source.
    clusterable_articles = [article for article in raw_articles if article.id in processed_ids]
    clusters = cluster_articles(
        clusterable_articles,
        embeddings,
        threshold=cluster_similarity_threshold,
        sources=source_by_id,
        final_scores=final_scores,
    )

    processed_by_article = {processed.raw_article_id: processed for processed in processed_articles}
    for cluster in clusters:
        main_processed = processed_by_article[cluster.main_article_id]
        cluster.category = main_processed.category
        cluster.tags = main_processed.tags
        cluster.final_score = max(final_scores[article_id] for article_id in cluster.article_ids)
        cluster.event_title = main_processed.title_zh
        cluster.event_summary = main_processed.summary_zh
        for article_id in cluster.article_ids:
            processed_by_article[article_id] = replace(
                processed_by_article[article_id],
                event_cluster_id=cluster.id,
            )

    processed_articles = list(processed_by_article.values())
    stage_timings["clustering"] = round(time.perf_counter() - stage_started, 3)
    stage_started = time.perf_counter()

    articles_by_id = {article.id: article for article in raw_articles}
    displayable_articles = [
        articles_by_id[processed.raw_article_id]
        for processed in processed_articles
        if processed.raw_article_id in articles_by_id
    ]
    _attach_github_readmes(articles=displayable_articles)
    stage_timings["readme"] = round(time.perf_counter() - stage_started, 3)
    stage_started = time.perf_counter()

    _translate_processed_english_articles(
        articles=displayable_articles,
        ai_provider=ai_provider,
        ai_concurrency=ai_concurrency,
    )
    stage_timings["translation"] = round(time.perf_counter() - stage_started, 3)
    stage_started = time.perf_counter()

    markdown = render_daily_markdown(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=source_by_id,
        generated_at=now,
    )
    json_data = build_daily_json(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=source_by_id,
        generated_at=now,
    )
    report = DailyReport(
        report_date=report_date,
        markdown=markdown,
        json_data=json_data,
        article_count=json_data["article_count"],
    )
    stage_timings["report"] = round(time.perf_counter() - stage_started, 3)
    return PipelineResult(
        raw_articles=raw_articles,
        processed_articles=processed_articles,
        event_clusters=clusters,
        daily_report=report,
        skipped_reasons=dict(skipped),
        embeddings=embeddings,
        embedding_model=_embedding_model_name(ai_provider),
        skipped_reason_by_raw_id=skipped_reason_by_raw_id,
        stage_timings=stage_timings,
    )
