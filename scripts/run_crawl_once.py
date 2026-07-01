#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.crawlers.run import crawl_sources
from app.data.default_sources import default_sources
from app.storage.json_store import load_sources, save_articles, save_sources, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one crawl pass and save raw articles.")
    parser.add_argument("--sources", default="data/sources.json")
    parser.add_argument("--output", default="data/raw_articles.json")
    parser.add_argument("--report", default="data/crawl_report.json")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    sources_path = ROOT / args.sources
    if not sources_path.exists():
        save_sources(sources_path, default_sources())
    sources = load_sources(sources_path)
    articles, report = crawl_sources(sources, limit=args.limit)

    output = ROOT / args.output
    save_articles(output, articles)
    report_path = ROOT / args.report
    write_json(report_path, report)
    for source_id, source_report in report["per_source"].items():
        if source_report["status"] == "skipped":
            print(f"SKIPPED {source_id}: {source_report['error']}")
    print(
        f"Crawled {len(articles)} articles to {output}; "
        f"report={report_path}; skipped={report['skipped_reasons']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
