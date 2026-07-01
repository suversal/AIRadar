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
from app.pipeline.runner import run_pipeline
from app.services.ai_service import FakeAIProvider, OpenAIProvider
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


def provider_from_env(fake_ai: bool):
    api_key = os.getenv("OPENAI_API_KEY")
    if fake_ai or not api_key:
        return FakeAIProvider()
    return OpenAIProvider(
        api_key,
        scoring_model=os.getenv("DEFAULT_SCORING_MODEL", "gpt-4.1-mini"),
        embedding_model=os.getenv("DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one processing pass from raw articles.")
    parser.add_argument("--sources", default="data/sources.json")
    parser.add_argument("--raw", default="data/raw_articles.json")
    parser.add_argument("--output-dir", default="data/pipeline")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--fake-ai", action="store_true")
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

    result = run_pipeline(
        sources=sources,
        raw_items_by_source=raw_items_by_source,
        ai_provider=provider_from_env(args.fake_ai),
        now=datetime.now(timezone.utc),
        report_date=date.fromisoformat(args.date),
        candidate_limit=args.limit,
        top_n=args.top_n,
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
    print(
        "Processed "
        f"{len(result.raw_articles)} raw, {len(result.processed_articles)} selected, "
        f"{len(result.event_clusters)} clusters; skipped={result.skipped_reasons}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

