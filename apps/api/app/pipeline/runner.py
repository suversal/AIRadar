from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from app.crawlers.base import normalize_article
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

    def flush() -> None:
        nonlocal chunk, chunk_chars
        if chunk:
            translated.extend(translate_with_retry(chunk))
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
                translated_pieces.extend(translate_with_retry([piece]))
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
        )
    except (KeyError, TypeError, ValueError):
        return None


def _process_candidate_article(
    *,
    article: RawArticle,
    source_by_id: dict[str, Source],
    ai_provider: Any,
    now: datetime,
    skip_prefilter: bool = False,
    cached: dict[str, Any] | None = None,
) -> tuple[ProcessedArticle | None, list[float] | None, str | None]:
    scoring = _cached_scoring_result(cached)
    if scoring is None and cached and cached.get("skipped_reason") == "not_ai_related":
        article.status = "skipped"
        article.skipped_reason = "not_ai_related"
        return None, None, "not_ai_related"

    if scoring is None and not skip_prefilter:
        prefilter = ai_provider.prefilter(f"{article.title}\n{article.content[:500]}")
        if not prefilter.is_ai_related:
            article.status = "skipped"
            article.skipped_reason = "not_ai_related"
            return None, None, "not_ai_related"

    if scoring is None:
        scoring = ai_provider.score_article(article.title, article.content)
    source = source_by_id[article.source_id]
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
    )
    embedding = ai_provider.embed_text(embedding_input(article.title, article.content))
    skipped_reason = None if processed.selected else "below_threshold"
    return processed, embedding, skipped_reason


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
        text_blocks = [
            block
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "paragraph"
            and str(block.get("text") or "").strip()
        ]
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
    paragraph_index = 0
    if isinstance(source_blocks, list) and source_blocks:
        translated_blocks = []
        for block in source_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "paragraph":
                if paragraph_index >= len(translated_paragraphs):
                    continue
                translated_blocks.append(
                    {"type": "paragraph", "text": translated_paragraphs[paragraph_index]}
                )
                paragraph_index += 1
            elif block.get("type") == "image":
                url = str(block.get("url") or "").strip()
                if url:
                    translated_blocks.append(
                        {
                            "type": "image",
                            "url": url,
                            "alt": str(block.get("alt") or "").strip(),
                            "caption": str(block.get("caption") or "").strip(),
                        }
                    )
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
        return

    try:
        translated_paragraphs = _translate_in_chunks(translate, paragraphs)
    except Exception as exc:
        article.metadata["translation_status"] = "failed"
        article.metadata["translation_error"] = str(exc)[:200]
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


def run_pipeline(
    *,
    sources: list[Source],
    raw_items_by_source: dict[str, list[dict]],
    ai_provider: FakeAIProvider,
    now: datetime,
    report_date: date,
    candidate_limit: int = 100,
    top_n: int = 12,
    ai_concurrency: int = 1,
    skip_prefilter: bool = False,
    cached_results: dict[str, dict[str, Any]] | None = None,
    cluster_similarity_threshold: float = 0.85,
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
                # reuse expensive AI artifacts (translations, README selection)
                # from earlier runs; freshly crawled metadata still wins
                for key, value in (cached.get("metadata") or {}).items():
                    article.metadata.setdefault(key, value)
            raw_articles.append(article)

    raw_articles = dedupe_articles(raw_articles)
    candidate_articles = raw_articles[:candidate_limit]
    if len(raw_articles) > candidate_limit:
        skipped["candidate_limit"] += len(raw_articles) - candidate_limit

    processed_articles: list[ProcessedArticle] = []
    embeddings: dict[str, list[float]] = {}

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

    for _, article, processed, embedding, skipped_reason in sorted(
        candidate_results,
        key=lambda item: item[0],
    ):
        if skipped_reason:
            skipped[skipped_reason] += 1
        if processed is None:
            continue
        processed_articles.append(processed)
        if embedding is not None:
            embeddings[article.id] = embedding

    final_scores = {
        processed.raw_article_id: processed.final_score for processed in processed_articles
    }
    # cluster EVERY selected article, not just the report candidates: the
    # event table is the full rolling event graph (product decision
    # 2026-07-11), and the daily report picks its top_n at the EVENT level
    # inside build_daily_json - so merged coverage can no longer shrink the
    # masthead below target
    selected_ids = {
        processed.raw_article_id for processed in processed_articles if processed.selected
    }
    # weak news days keep their long-standing fill behavior: the best
    # below-threshold candidates (up to top_n) still enter the event graph
    # so the report is never blank just because nothing crossed the bar
    fill_ids = {
        processed.raw_article_id
        for processed in sorted(
            processed_articles,
            key=lambda item: (item.selected, item.final_score),
            reverse=True,
        )[:top_n]
    }
    clusterable_ids = selected_ids | fill_ids
    clusterable_articles = [article for article in raw_articles if article.id in clusterable_ids]
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
    articles_by_id = {article.id: article for article in raw_articles}
    displayable_articles = [
        articles_by_id[processed.raw_article_id]
        for processed in processed_articles
        if processed.raw_article_id in articles_by_id
    ]
    _attach_github_readmes(articles=displayable_articles)
    _translate_processed_english_articles(
        articles=displayable_articles,
        ai_provider=ai_provider,
        ai_concurrency=ai_concurrency,
    )
    markdown = render_daily_markdown(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=source_by_id,
        top_n=top_n,
        generated_at=now,
    )
    json_data = build_daily_json(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=source_by_id,
        top_n=top_n,
        generated_at=now,
    )
    report = DailyReport(
        report_date=report_date,
        markdown=markdown,
        json_data=json_data,
        article_count=json_data["article_count"],
    )
    return PipelineResult(
        raw_articles=raw_articles,
        processed_articles=processed_articles,
        event_clusters=clusters,
        daily_report=report,
        skipped_reasons=dict(skipped),
        embeddings=embeddings,
        embedding_model=_embedding_model_name(ai_provider),
    )
