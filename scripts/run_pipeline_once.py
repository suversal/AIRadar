#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.data.default_sources import default_sources
from app.core.config import load_env_file
from app.pipeline.persistence import persist_pipeline_result_to_database
from app.pipeline.runner import run_pipeline
from app.services.ai_service import provider_from_env as build_provider_from_env
from app.storage.json_store import (
    article_to_dict,
    cluster_to_dict,
    load_articles,
    load_sources,
    processed_to_dict,
    report_to_dict,
    save_sources,
    write_json,
)


def persist_result_if_requested(
    args: argparse.Namespace,
    *,
    sources,
    result,
    persister=persist_pipeline_result_to_database,
):
    if not args.persist_db:
        return None
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("database url is required when --persist-db is enabled")
    return persister(database_url, sources, result)


def provider_from_env(fake_ai: bool):
    return build_provider_from_env(fake_ai=fake_ai)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> int:
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run one processing pass from raw articles.")
    parser.add_argument("--sources", default="data/sources.json")
    parser.add_argument("--raw", default="data/raw_articles.json")
    parser.add_argument("--output-dir", default="data/pipeline")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--ai-concurrency", type=int, default=env_int("AI_PIPELINE_CONCURRENCY", 1))
    parser.add_argument("--fake-ai", action="store_true")
    parser.add_argument(
        "--skip-prefilter",
        action="store_true",
        help="Score every candidate instead of dropping items during the AI-related prefilter.",
    )
    parser.add_argument("--persist-db", action="store_true")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Reprocess every article with AI even when cached results exist in the database.",
    )
    args = parser.parse_args()

    sources_path = ROOT / args.sources
    if not sources_path.exists():
        save_sources(sources_path, default_sources())
    sources = load_sources(sources_path)
    raw_articles = load_articles(ROOT / args.raw)
    raw_items_by_source = {}
    for article in raw_articles:
        raw_items_by_source.setdefault(article.source_id, []).append(
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

    cached_results = {}
    if args.database_url and not args.no_cache:
        from app.pipeline.persistence import load_cached_results_from_database

        cached_results = load_cached_results_from_database(
            args.database_url, [article.url_hash for article in raw_articles]
        )
    if cached_results:
        print(f"Loaded {len(cached_results)} cached article results from database")

    result = run_pipeline(
        sources=sources,
        raw_items_by_source=raw_items_by_source,
        ai_provider=provider_from_env(args.fake_ai),
        now=datetime.now(timezone.utc),
        report_date=date.fromisoformat(args.date),
        candidate_limit=args.limit,
        top_n=args.top_n,
        ai_concurrency=args.ai_concurrency,
        skip_prefilter=args.skip_prefilter,
        cached_results=cached_results,
    )

    output_dir = ROOT / args.output_dir
    write_json(output_dir / "raw_articles.json", [article_to_dict(item) for item in result.raw_articles])
    write_json(
        output_dir / "processed_articles.json",
        [processed_to_dict(item) for item in result.processed_articles],
    )
    write_json(
        output_dir / "event_clusters.json",
        [cluster_to_dict(item) for item in result.event_clusters],
    )
    write_json(output_dir / "daily_report.json", report_to_dict(result.daily_report))
    reports_dir = ROOT / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{args.date}.md").write_text(result.daily_report.markdown, encoding="utf-8")
    write_json(reports_dir / f"{args.date}.json", result.daily_report.json_data)
    persistence_summary = persist_result_if_requested(args, sources=sources, result=result)
    print(
        "Processed "
        f"{len(result.raw_articles)} raw, {len(result.processed_articles)} selected, "
        f"{len(result.event_clusters)} clusters; skipped={result.skipped_reasons}"
    )
    if persistence_summary is not None:
        print(
            "Persisted DB "
            f"sources={persistence_summary.sources.inserted}+{persistence_summary.sources.updated}, "
            f"raw_inserted={persistence_summary.raw_articles.inserted}, "
            f"raw_skipped={persistence_summary.raw_articles.skipped}, "
            f"daily_inserted={persistence_summary.daily_report.inserted}, "
            f"daily_updated={persistence_summary.daily_report.updated}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
