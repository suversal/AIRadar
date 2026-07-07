from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.crawlers.run import crawl_sources
from app.data.default_sources import default_sources
from app.models.domain import RawArticle, Source
from app.pipeline.persistence import persist_pipeline_result_to_database
from app.pipeline.runner import run_pipeline
from app.services.ai_service import FakeAIProvider
from app.storage.json_store import (
    article_to_dict,
    cluster_to_dict,
    load_sources,
    processed_to_dict,
    report_to_dict,
    save_articles,
    save_sources,
    write_json,
)


def _raw_items_by_source(raw_articles: list[RawArticle]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for article in raw_articles:
        grouped.setdefault(article.source_id, []).append(
            {
                "source_url": article.source_url,
                "title": article.title,
                "content": article.content,
                "author": article.author,
                "published_at": article.published_at,
                "language": article.language,
                "raw_score": article.raw_score,
                "metadata": article.metadata,
            }
        )
    return grouped


def _load_or_seed_sources(sources_path: Path) -> list[Source]:
    if not sources_path.exists():
        save_sources(sources_path, default_sources())
    return load_sources(sources_path)


def refresh_latest_report(
    *,
    data_dir: Path,
    database_url: str | None,
    limit: int = 100,
    top_n: int = 12,
    report_date: date | None = None,
) -> dict[str, Any]:
    resolved_date = report_date or date.today()
    sources_path = data_dir / "sources.json"
    sources = _load_or_seed_sources(sources_path)

    raw_articles, crawl_report = crawl_sources(sources, limit=limit)
    crawl_dir = data_dir / "crawl_checks"
    raw_path = crawl_dir / f"{resolved_date.isoformat()}-refresh-raw.json"
    crawl_report_path = crawl_dir / f"{resolved_date.isoformat()}-refresh-crawl-report.json"
    save_articles(raw_path, raw_articles)
    write_json(crawl_report_path, crawl_report)

    result = run_pipeline(
        sources=sources,
        raw_items_by_source=_raw_items_by_source(raw_articles),
        ai_provider=FakeAIProvider(),
        now=datetime.now(timezone.utc),
        report_date=resolved_date,
        candidate_limit=limit,
        top_n=top_n,
    )

    pipeline_dir = data_dir / "crawl_checks" / f"{resolved_date.isoformat()}-refresh-pipeline"
    write_json(pipeline_dir / "raw_articles.json", [article_to_dict(item) for item in result.raw_articles])
    write_json(
        pipeline_dir / "processed_articles.json",
        [processed_to_dict(item) for item in result.processed_articles],
    )
    write_json(pipeline_dir / "event_clusters.json", [cluster_to_dict(item) for item in result.event_clusters])
    write_json(pipeline_dir / "daily_report.json", report_to_dict(result.daily_report))

    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{resolved_date.isoformat()}.md").write_text(
        result.daily_report.markdown,
        encoding="utf-8",
    )
    write_json(reports_dir / f"{resolved_date.isoformat()}.json", result.daily_report.json_data)

    persistence_summary = None
    if database_url:
        persistence_summary = persist_pipeline_result_to_database(database_url, sources, result)

    return {
        "status": "ok",
        "report_date": resolved_date.isoformat(),
        "crawled_count": len(raw_articles),
        "selected_count": len(result.processed_articles),
        "cluster_count": len(result.event_clusters),
        "article_count": result.daily_report.article_count,
        "skipped_reasons": result.skipped_reasons,
        "crawl_skipped_reasons": crawl_report.get("skipped_reasons", {}),
        "persisted": persistence_summary is not None,
        "raw_path": str(raw_path),
        "crawl_report_path": str(crawl_report_path),
    }
