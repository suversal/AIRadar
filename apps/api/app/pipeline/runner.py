from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, datetime

from app.crawlers.base import normalize_article
from app.models.domain import DailyReport, PipelineResult, ProcessedArticle, RawArticle, Source
from app.services.ai_service import FakeAIProvider
from app.services.clustering_service import cluster_articles
from app.services.daily_report_service import build_daily_json, render_daily_markdown
from app.services.scoring_service import select_processed_article


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


def run_pipeline(
    *,
    sources: list[Source],
    raw_items_by_source: dict[str, list[dict]],
    ai_provider: FakeAIProvider,
    now: datetime,
    report_date: date,
    candidate_limit: int = 100,
    top_n: int = 12,
) -> PipelineResult:
    source_by_id = {source.id: source for source in sources}
    raw_articles: list[RawArticle] = []
    skipped = Counter()

    for source_id, raw_items in raw_items_by_source.items():
        source = source_by_id[source_id]
        for item in raw_items:
            raw_articles.append(normalize_article(source=source, **item))

    raw_articles = dedupe_articles(raw_articles)
    candidate_articles = raw_articles[:candidate_limit]
    if len(raw_articles) > candidate_limit:
        skipped["candidate_limit"] += len(raw_articles) - candidate_limit

    processed_articles: list[ProcessedArticle] = []
    embeddings: dict[str, list[float]] = {}

    for article in candidate_articles:
        prefilter = ai_provider.prefilter(f"{article.title}\n{article.content[:500]}")
        if not prefilter.is_ai_related:
            article.status = "skipped"
            article.skipped_reason = "not_ai_related"
            skipped["not_ai_related"] += 1
            continue
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
        if processed.selected:
            processed_articles.append(processed)
            embeddings[article.id] = ai_provider.embed_text(f"{article.title}\n{article.content}")
        else:
            skipped["below_threshold"] += 1

    selected_article_ids = {processed.raw_article_id for processed in processed_articles}
    selected_articles = [article for article in raw_articles if article.id in selected_article_ids]
    final_scores = {
        processed.raw_article_id: processed.final_score for processed in processed_articles
    }
    clusters = cluster_articles(
        selected_articles,
        embeddings,
        threshold=0.85,
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
    markdown = render_daily_markdown(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=source_by_id,
        top_n=top_n,
    )
    json_data = build_daily_json(
        report_date=report_date,
        clusters=clusters,
        processed_by_article=processed_by_article,
        articles_by_id=articles_by_id,
        sources_by_id=source_by_id,
        top_n=top_n,
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
    )

