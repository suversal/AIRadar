#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.crawlers.registry import crawler_for_source
from app.data.default_sources import default_sources
from app.storage.json_store import load_sources, save_articles, save_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one crawl pass and save raw articles.")
    parser.add_argument("--sources", default="data/sources.json")
    parser.add_argument("--output", default="data/raw_articles.json")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    sources_path = ROOT / args.sources
    if not sources_path.exists():
        save_sources(sources_path, default_sources())
    sources = [source for source in load_sources(sources_path) if source.is_active]

    articles = []
    skipped = Counter()
    per_source_limit = max(1, args.limit // max(1, len(sources)))
    for source in sources:
        try:
            fetched = crawler_for_source(source).fetch(limit=per_source_limit)
        except Exception as exc:  # keep one source failure from blocking the full pass
            skipped[f"{source.id}:fetch_failed"] += 1
            print(f"SKIPPED {source.id}: {exc}")
            continue
        articles.extend(fetched)
        if len(articles) >= args.limit:
            articles = articles[: args.limit]
            break

    output = ROOT / args.output
    save_articles(output, articles)
    print(f"Crawled {len(articles)} articles to {output}; skipped={dict(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

