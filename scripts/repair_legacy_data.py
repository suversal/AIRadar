"""One-shot, idempotent repair of legacy rows written before the 2026-07-11
data-quality fixes. Safe to re-run: every step only touches rows that are
still in the legacy shape.

- processed_articles.event_cluster_id cache column: re-derived from the
  membership table (is_main event first, else the most recently joined).
- article_embeddings with embedding_model='unknown': re-embedded with the
  real local model, writing the true model name and a fresh source_hash.
- event_clusters.source_count: recounted from the membership table.
- pipeline_runs.finished_at is deliberately NOT touched: there is no
  trustworthy source for historical finish times, and faking them would be
  worse than NULL.

Usage:
    .venv/bin/python scripts/repair_legacy_data.py \
        --database-url postgresql+psycopg://radar:radar@localhost:5432/radar
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.crawlers.base import stable_hash  # noqa: E402
from app.db.models import (  # noqa: E402
    ArticleEmbeddingModel,
    EventClusterArticleModel,
    EventClusterModel,
    ProcessedArticleModel,
    RawArticleModel,
)
from app.services.ai_service import embedding_input  # noqa: E402


def repair_event_links(session) -> int:
    """Point the processed_articles cache column back at the membership
    table's truth. is_main membership wins; otherwise the latest joined."""
    fixed = 0
    processed_rows = session.scalars(select(ProcessedArticleModel)).all()
    for processed in processed_rows:
        memberships = session.scalars(
            select(EventClusterArticleModel).where(
                EventClusterArticleModel.raw_article_id == processed.raw_article_id
            )
        ).all()
        if not memberships:
            continue
        main = next((m for m in memberships if m.is_main), None)
        chosen = main or max(memberships, key=lambda m: (m.joined_at, m.id))
        if processed.event_cluster_id != chosen.event_cluster_id:
            processed.event_cluster_id = chosen.event_cluster_id
            fixed += 1
    return fixed


def reembed_unknown(session, *, embedder) -> int:
    """Recompute every 'unknown' embedding with the real local model so the
    row carries the true model name and a hash of the actual input."""
    fixed = 0
    rows = session.scalars(
        select(ArticleEmbeddingModel).where(ArticleEmbeddingModel.embedding_model == "unknown")
    ).all()
    for row in rows:
        article = session.get(RawArticleModel, row.raw_article_id)
        if article is None:
            continue
        text = embedding_input(article.title, article.content)
        row.content_vector = embedder.embed_text(text)
        row.embedding_model = embedder.model_name
        row.source_hash = stable_hash(text)
        fixed += 1
    return fixed


def recount_source_counts(session) -> int:
    """Recount distinct sources per event from the membership table."""
    fixed = 0
    for cluster in session.scalars(select(EventClusterModel)).all():
        count = len(
            session.execute(
                select(RawArticleModel.source_id)
                .join(
                    EventClusterArticleModel,
                    EventClusterArticleModel.raw_article_id == RawArticleModel.id,
                )
                .where(EventClusterArticleModel.event_cluster_id == cluster.id)
                .distinct()
            ).all()
        )
        if count and cluster.source_count != count:
            cluster.source_count = count
            fixed += 1
    return fixed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="skip the re-embedding step (no local model download needed)",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory, session_scope

    session_factory = build_session_factory(args.database_url)
    with session_scope(session_factory) as session:
        links = repair_event_links(session)
        embeddings = 0
        if not args.skip_embeddings:
            from app.services.ai_service import LocalEmbeddingProvider

            embeddings = reembed_unknown(session, embedder=LocalEmbeddingProvider())
        counts = recount_source_counts(session)

    print(
        f"repaired: event links={links}, unknown embeddings={embeddings}, "
        f"source counts={counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
