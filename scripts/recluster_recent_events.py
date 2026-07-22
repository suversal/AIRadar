"""Dry-run simulation (default) or live rewrite (--apply) of event clustering
for a recent time window, using the complete-linkage matching fix and the
title-weighted embedding_input() from the 2026-07-22 clustering remediation.

Without --apply this touches no data: it recomputes embeddings for the
affected articles in memory and re-runs cluster_articles() to show exactly
which article would move relative to the current, persisted grouping -
review the diff before deciding whether to --apply it.

Scope: every event_cluster whose last_seen_at falls within --since-hours,
plus every existing member of those clusters (even ones outside the window -
an older bridge article, like the Cursor Slack post that got pulled into the
Anthropic mega-cluster, has to be included so re-clustering can correctly
decide whether it still belongs).

--apply behavior: every affected article's embedding is recomputed and
persisted with the new title-weighted input (regardless of whether its
grouping changes). Only the event_clusters/event_cluster_articles rows for
clusters whose grouping actually changed are deleted and rebuilt via the
same upsert_event_clusters() the live pipeline uses - unaffected clusters
keep their existing rows and joined_at history untouched. No
EventClusterRedirectModel entries are written: stable_cluster_id() is a
hash of main_article_id, and the sub-group that keeps the original main
article (guaranteed to still win choose_main_article, since it was already
the best pick over the full superset) always keeps the same event_id -
this is a pure split, never a merge, so nothing old_id-shaped goes away.

Usage:
    .venv/bin/python scripts/recluster_recent_events.py \
        --database-url postgresql+psycopg://radar:radar@localhost:5432/radar \
        --since-hours 48

    .venv/bin/python scripts/recluster_recent_events.py --since-hours 48 --apply
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
    SourceModel,
)
from app.models.domain import RawArticle  # noqa: E402
from app.repositories.radar_repository import RadarRepository, _source_to_domain  # noqa: E402
from app.services.ai_service import embedding_input  # noqa: E402
from app.services.clustering_service import cluster_articles  # noqa: E402


def _raw_article_from_model(model: RawArticleModel, source: SourceModel) -> RawArticle:
    return RawArticle(
        id=model.id,
        source_id=model.source_id,
        source_name=source.name if source else model.source_id,
        source_role=source.source_role if source else "signal",
        source_tier=source.tier if source else "T3",
        source_url=model.source_url,
        title=model.title,
        content=model.content,
        author=model.author,
        published_at=model.published_at,
        language=model.language,
        raw_score={},
        metadata=dict(model.raw_metadata or {}),
        title_hash=model.title_hash,
        url_hash=model.url_hash,
    )


def gather_recent_pool(session, *, since) -> tuple[dict[str, set[str]], set[str]]:
    """(old_membership_by_cluster_id, all_affected_article_ids)."""
    recent_cluster_ids = set(
        session.scalars(
            select(EventClusterModel.id).where(EventClusterModel.last_seen_at >= since)
        ).all()
    )
    old_membership: dict[str, set[str]] = {}
    all_ids: set[str] = set()
    for cluster_id in recent_cluster_ids:
        members = set(
            session.scalars(
                select(EventClusterArticleModel.raw_article_id).where(
                    EventClusterArticleModel.event_cluster_id == cluster_id
                )
            ).all()
        )
        old_membership[cluster_id] = members
        all_ids.update(members)
    return old_membership, all_ids


def recompute(session, *, since, embedder, threshold: float, persist_embeddings: bool) -> dict:
    """Shared computation for both --dry-run reporting and --apply. When
    persist_embeddings is True, writes the recomputed vector/source_hash for
    every affected article (does not commit - caller controls the
    transaction)."""
    old_membership, article_ids = gather_recent_pool(session, since=since)
    if not article_ids:
        return {"old_membership": {}, "new_clusters": [], "embeddings_updated": 0}

    raw_rows = session.execute(
        select(RawArticleModel, SourceModel)
        .join(SourceModel, SourceModel.id == RawArticleModel.source_id)
        .where(RawArticleModel.id.in_(article_ids))
    ).all()
    sources_by_id = {model.source_id: _source_to_domain(source) for model, source in raw_rows}
    articles = [_raw_article_from_model(model, source) for model, source in raw_rows]

    final_scores = {
        row.raw_article_id: row.final_score
        for row in session.scalars(
            select(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id.in_(article_ids)
            )
        ).all()
    }

    embeddings: dict[str, list[float]] = {}
    embeddings_updated = 0
    for article in articles:
        text = embedding_input(article.title, article.content)
        vector = embedder.embed_text(text)
        embeddings[article.id] = vector
        if persist_embeddings:
            embedding_row = session.scalar(
                select(ArticleEmbeddingModel).where(
                    ArticleEmbeddingModel.raw_article_id == article.id
                )
            )
            if embedding_row is not None:
                embedding_row.content_vector = vector
                embedding_row.embedding_model = embedder.model_name
                embedding_row.source_hash = stable_hash(text)
                embeddings_updated += 1

    new_clusters = cluster_articles(
        articles, embeddings, threshold=threshold, sources=sources_by_id, final_scores=final_scores
    )
    return {
        "old_membership": old_membership,
        "new_clusters": new_clusters,
        "embeddings_updated": embeddings_updated,
    }


def _changed_old_clusters(old_membership, new_clusters) -> tuple[set[str], set[str]]:
    """(old cluster ids whose grouping changed, new cluster ids they map to)."""
    new_group_of: dict[str, str] = {}
    for cluster in new_clusters:
        for article_id in cluster.article_ids:
            new_group_of[article_id] = cluster.id

    changed_old_ids: set[str] = set()
    changed_new_ids: set[str] = set()
    for cluster_id, members in old_membership.items():
        new_groups = {new_group_of.get(a) for a in members}
        if len(new_groups) > 1:
            changed_old_ids.add(cluster_id)
            changed_new_ids.update(new_groups)
    return changed_old_ids, changed_new_ids


def _title(session, article_id: str) -> str:
    row = session.get(RawArticleModel, article_id)
    return row.title if row else article_id


def print_report(session, computed: dict) -> None:
    old_membership = computed["old_membership"]
    new_clusters = computed["new_clusters"]
    print(f"scanned {len(old_membership)} event(s) with recent activity")
    if not old_membership:
        return
    changed_old_ids, _ = _changed_old_clusters(old_membership, new_clusters)
    if not changed_old_ids:
        print("no differences: every affected event regroups the same way under the new logic")
        return
    new_group_of: dict[str, str] = {}
    for cluster in new_clusters:
        for article_id in cluster.article_ids:
            new_group_of[article_id] = cluster.id
    print(f"\n{len(changed_old_ids)} event(s) would change:\n")
    for cluster_id in changed_old_ids:
        members = old_membership[cluster_id]
        print(f"=== old event {cluster_id} ({len(members)} members) ===")
        for article_id in members:
            new_id = new_group_of.get(article_id)
            marker = "same group" if new_id == cluster_id else f"-> {new_id}"
            print(f"  [{marker:14s}] {_title(session, article_id)[:60]}")
        print()


def apply(session, computed: dict, *, threshold: float) -> dict:
    old_membership = computed["old_membership"]
    new_clusters = computed["new_clusters"]
    if not old_membership:
        return {"changed_clusters": 0, "embeddings_updated": computed["embeddings_updated"]}

    changed_old_ids, changed_new_ids = _changed_old_clusters(old_membership, new_clusters)
    if not changed_old_ids:
        session.commit()
        return {"changed_clusters": 0, "embeddings_updated": computed["embeddings_updated"]}

    new_group_of: dict[str, str] = {}
    for cluster in new_clusters:
        for article_id in cluster.article_ids:
            new_group_of[article_id] = cluster.id

    for cluster_id in changed_old_ids:
        memberships = session.scalars(
            select(EventClusterArticleModel).where(
                EventClusterArticleModel.event_cluster_id == cluster_id
            )
        ).all()
        for membership in memberships:
            # processed_articles.event_cluster_id is a read cache with an FK
            # to event_clusters - it must stop pointing at this row before the
            # row can be deleted, and gets re-pointed at the new grouping
            # right after the upsert below
            processed = session.scalar(
                select(ProcessedArticleModel).where(
                    ProcessedArticleModel.raw_article_id == membership.raw_article_id
                )
            )
            if processed is not None:
                processed.event_cluster_id = None
            session.delete(membership)
        model = session.get(EventClusterModel, cluster_id)
        if model is not None:
            session.delete(model)
    session.flush()

    new_by_id = {c.id: c for c in new_clusters}
    replacement_clusters = [new_by_id[cid] for cid in changed_new_ids if cid in new_by_id]
    repository = RadarRepository(session)
    write_result = repository.upsert_event_clusters(replacement_clusters, similarity_threshold=threshold)

    for cluster_id in changed_old_ids:
        for article_id in old_membership[cluster_id]:
            processed = session.scalar(
                select(ProcessedArticleModel).where(
                    ProcessedArticleModel.raw_article_id == article_id
                )
            )
            if processed is not None:
                processed.event_cluster_id = new_group_of.get(article_id)
    session.commit()
    return {
        "changed_clusters": len(changed_old_ids),
        "new_groups": len(replacement_clusters),
        "embeddings_updated": computed["embeddings_updated"],
        "inserted": write_result.inserted,
        "updated": write_result.updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--since-hours", type=float, default=48.0)
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.90")),
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the recomputed grouping/embeddings to the database"
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from datetime import datetime, timedelta, timezone

    from app.db.session import build_session_factory, session_scope
    from app.services.ai_service import LocalEmbeddingProvider

    since = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    session_factory = build_session_factory(args.database_url)
    embedder = LocalEmbeddingProvider()

    with session_scope(session_factory) as session:
        computed = recompute(
            session,
            since=since,
            embedder=embedder,
            threshold=args.threshold,
            persist_embeddings=args.apply,
        )
        if args.apply:
            result = apply(session, computed, threshold=args.threshold)
            print(
                f"applied: {result['changed_clusters']} old event(s) rebuilt into "
                f"{result.get('new_groups', 0)} new group(s), "
                f"{result['embeddings_updated']} embedding(s) refreshed "
                f"(inserted={result.get('inserted', 0)}, updated={result.get('updated', 0)})"
            )
        else:
            print_report(session, computed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
