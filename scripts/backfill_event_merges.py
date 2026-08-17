"""Merge event clusters that the pre-gray-zone clustering left split apart.

Clustering used to require complete-linkage >= 0.90 with no band below it, so
one real event reported by several outlets over a few hours was filed as several
events - 2026-08-03「阿里发布 Qwen3.8-Max」became 8 separate ones, split across
6 pipeline runs. The band added to clustering_service/find_similar_recent_event
fixes new intake; this backfills what is already stored.

Deliberately merge-only: it never splits an existing event. Splitting is the
riskier direction and scripts/recluster_recent_events.py already covers it, so
keeping the two apart means neither can undo the other's work by accident.

Every merge goes through RadarRepository._merge_event_cluster, the same path
production reconciliation uses, so article membership, processed-article caches,
editorial overrides, historical report entries and redirects are all remapped
the way they already are elsewhere - this script does not rebuild cluster rows.

Without --apply nothing is written. Take a database backup before --apply;
redirects make the merge traceable but not conveniently reversible.

Usage:
    .venv/bin/python scripts/backfill_event_merges.py --since 2026-08-01 --until 2026-08-18
    .venv/bin/python scripts/backfill_event_merges.py --since 2026-08-01 --until 2026-08-18 --rollback
    .venv/bin/python scripts/backfill_event_merges.py --since 2026-08-01 --until 2026-08-18 --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db.models import (  # noqa: E402
    ArticleEmbeddingModel,
    EventClusterArticleModel,
    EventClusterModel,
    ProcessedArticleModel,
    RawArticleModel,
    SourceModel,
)
from app.models.domain import RawArticle  # noqa: E402
from app.repositories.radar_repository import (  # noqa: E402
    RadarRepository,
    _source_to_domain,
)
from app.services.clustering_service import cluster_articles  # noqa: E402


def _raw_article(model: RawArticleModel, source: SourceModel | None) -> RawArticle:
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


def plan_merges(
    session,
    *,
    since: datetime,
    until: datetime,
    threshold: float,
    window_hours: float,
    same_event_verifier: Callable[[dict[str, Any], dict[str, Any]], bool] | None,
) -> list[list[str]]:
    """Groups of currently-separate event ids that re-clustering puts together.

    The whole range is pooled in one pass rather than processed day by day:
    cluster_articles enforces the event time window internally, and pooling is
    what lets fragments from different pipeline runs meet at all.
    """
    rows = session.execute(
        select(RawArticleModel, SourceModel, EventClusterArticleModel.event_cluster_id)
        .join(SourceModel, SourceModel.id == RawArticleModel.source_id, isouter=True)
        .join(
            EventClusterArticleModel,
            EventClusterArticleModel.raw_article_id == RawArticleModel.id,
        )
        .where(RawArticleModel.published_at >= since)
        .where(RawArticleModel.published_at < until)
    ).all()
    if not rows:
        return []

    articles = [_raw_article(model, source) for model, source, _ in rows]
    old_cluster_of = {model.id: cluster_id for model, _, cluster_id in rows}
    sources_by_id = {
        model.source_id: _source_to_domain(source)
        for model, source, _ in rows
        if source is not None
    }
    article_ids = [article.id for article in articles]

    embeddings = {
        row.raw_article_id: list(row.content_vector)
        for row in session.scalars(
            select(ArticleEmbeddingModel).where(
                ArticleEmbeddingModel.raw_article_id.in_(article_ids)
            )
        ).all()
        if row.content_vector is not None
    }
    final_scores = {
        row.raw_article_id: row.final_score
        for row in session.scalars(
            select(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id.in_(article_ids)
            )
        ).all()
    }

    regrouped = cluster_articles(
        articles,
        embeddings,
        threshold=threshold,
        sources=sources_by_id,
        final_scores=final_scores,
        max_event_span_hours=window_hours,
        same_event_verifier=same_event_verifier,
    )

    groups: list[list[str]] = []
    for cluster in regrouped:
        old_ids = {
            old_cluster_of[article_id]
            for article_id in cluster.article_ids
            if article_id in old_cluster_of
        }
        if len(old_ids) > 1:
            groups.append(sorted(old_ids))
    return groups


def apply_merges(session, groups: list[list[str]], *, commit: bool) -> dict[str, Any]:
    """Fold each group into its highest-ranked member. Rolls back when
    commit is False so the full write path can be rehearsed."""
    repository = RadarRepository(session)
    redirects: dict[str, str] = {}
    merged_events = 0
    merged_groups = 0
    for old_ids in groups:
        live_ids = set()
        for event_id in old_ids:
            resolved = repository._follow_redirects(event_id, redirects)
            if session.get(EventClusterModel, resolved) is not None:
                live_ids.add(resolved)
        if len(live_ids) < 2:
            continue
        target_id = max(live_ids, key=repository._event_merge_rank)
        for source_id in sorted(live_ids - {target_id}):
            repository._merge_event_cluster(source_id, target_id, redirects)
            merged_events += 1
        merged_groups += 1
    session.flush()
    if commit:
        session.commit()
    else:
        session.rollback()
    return {
        "merged_groups": merged_groups,
        "merged_events": merged_events,
        "redirects": dict(redirects),
    }


def describe(session, groups: list[list[str]]) -> str:
    lines = [f"{len(groups)} group(s) would merge:"]
    for old_ids in sorted(groups, key=len, reverse=True):
        lines.append(f"\n=== {len(old_ids)} events -> 1")
        for event_id in old_ids:
            model = session.get(EventClusterModel, event_id)
            title = (model.event_title if model else "") or ""
            sources = model.source_count if model else 0
            lines.append(f"    {event_id}  [{sources} src]  {title[:56]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--since", required=True, help="inclusive published_at date")
    parser.add_argument("--until", required=True, help="exclusive published_at date")
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.90")),
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=float(os.getenv("CLUSTER_WINDOW_HOURS", "48")),
    )
    parser.add_argument("--apply", action="store_true", help="commit the merges")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="execute the full write path and roll the transaction back",
    )
    parser.add_argument(
        "--limit-merges",
        type=int,
        default=0,
        help="safety valve: stop after this many merge groups (0 = no limit)",
    )
    args = parser.parse_args()
    if args.apply and args.rollback:
        parser.error("--apply and --rollback are mutually exclusive")
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory

    since = datetime.combine(date.fromisoformat(args.since), time.min, tzinfo=timezone.utc)
    until = datetime.combine(date.fromisoformat(args.until), time.min, tzinfo=timezone.utc)

    from app.services.ai_service import build_same_event_verifier, provider_from_env

    same_event_verifier = build_same_event_verifier(provider_from_env())
    if same_event_verifier is None:
        # The band is the entire point of this backfill and it is verifier-only
        # by design; without one the pass would merge on vector similarity
        # alone, which measurably mis-merges (unrelated arXiv papers score
        # 0.86-0.93, above genuine same-event coverage).
        parser.error(
            "a real AI provider with same-event verification is required; "
            "fake/local mode is intentionally fail-closed"
        )

    # Deliberately not session_scope: it commits on clean exit, which would
    # make --rollback depend on "the transaction is already rolled back, so
    # that commit is empty". apply_merges owns the transaction outcome here.
    session_factory = build_session_factory(args.database_url)
    session = session_factory()
    try:
        groups = plan_merges(
            session,
            since=since,
            until=until,
            threshold=args.threshold,
            window_hours=args.window_hours,
            same_event_verifier=same_event_verifier,
        )
        if args.limit_merges > 0:
            dropped = max(0, len(groups) - args.limit_merges)
            if dropped:
                print(f"--limit-merges {args.limit_merges}: skipping {dropped} further group(s)")
            groups = groups[: args.limit_merges]
        if not groups:
            print("nothing to merge in this range")
            return 0
        if not (args.apply or args.rollback):
            print(describe(session, groups))
            print("\ndry run: nothing written. Back up the database, then re-run with --apply.")
            return 0
        result = apply_merges(session, groups, commit=args.apply)
        print(
            f"{'applied' if args.apply else 'rolled back'}: "
            f"{result['merged_events']} event(s) folded into "
            f"{result['merged_groups']} event(s)"
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
