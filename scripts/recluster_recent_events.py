"""Dry-run, rollback rehearsal, or live rewrite of recent event clustering.

Without --apply this touches no data: it recomputes embeddings for the
affected articles in memory and re-runs cluster_articles() to show exactly
which article would move relative to the current, persisted grouping -
review the diff before deciding whether to --apply it.

By default the scope is every multi-source event whose last_seen_at falls
within --since-hours, including all of each event's older members. Supplying a
--review-plan limits the rewrite to the explicitly reviewed event ids and
keeps all article comparison local. Without a review plan, a configured real
AI provider supplies the fail-closed same-event verifier.

--apply behavior: every affected article's embedding is recomputed and
persisted with the new title-weighted input (regardless of whether its
grouping changes). Only the event_clusters/event_cluster_articles rows for
clusters whose grouping actually changed are rebuilt. The subgroup containing
the current main article preserves the public event id; stale redirects are
detached and safely restored or removed when a formerly merged event is
recreated. Processed-article caches and report entries are remapped in the
same transaction. --rollback executes this full write path and rolls it back.

Usage:
    .venv/bin/python scripts/recluster_recent_events.py \
        --database-url postgresql+psycopg://radar:radar@localhost:5432/radar \
        --since-hours 48

    .venv/bin/python scripts/recluster_recent_events.py \
        --since-hours 48 --review-plan reviewed.json --rollback

    .venv/bin/python scripts/recluster_recent_events.py \
        --since-hours 48 --review-plan reviewed.json --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.crawlers.base import stable_hash  # noqa: E402
from app.db.models import (  # noqa: E402
    ArticleEmbeddingModel,
    DailyReportEntryModel,
    EventClusterArticleModel,
    EventClusterModel,
    EventClusterRedirectModel,
    PeriodReportModel,
    ProcessedArticleModel,
    RawArticleModel,
    SourceModel,
)
from app.models.domain import RawArticle  # noqa: E402
from app.repositories.radar_repository import RadarRepository, _source_to_domain  # noqa: E402
from app.services.ai_service import (  # noqa: E402
    build_same_event_verifier,
    embedding_input,
    provider_from_env,
)
from app.services.clustering_service import cluster_articles  # noqa: E402


def load_review_plan(path: str):
    """Build a deterministic verifier from a human-reviewed split manifest."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    events = payload.get("events")
    if not isinstance(events, dict):
        raise ValueError("review plan must contain an events object")
    group_by_article: dict[str, str] = {}
    reviewed_members_by_event: dict[str, set[str]] = {}
    for event_id, groups in events.items():
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"review plan event {event_id} has no groups")
        for index, group in enumerate(groups):
            if not isinstance(group, list) or not group:
                raise ValueError(f"review plan event {event_id} group {index} is empty")
            label = f"{event_id}:{index}"
            for article_id in group:
                article_id = str(article_id)
                if article_id in group_by_article:
                    raise ValueError(
                        f"review plan article {article_id} appears more than once"
                    )
                group_by_article[article_id] = label
                reviewed_members_by_event.setdefault(str(event_id), set()).add(
                    article_id
                )

    def verify(left, right):
        left_label = group_by_article.get(str(left.get("id") or ""))
        right_label = group_by_article.get(str(right.get("id") or ""))
        if left_label is None and right_label is None:
            return True
        return left_label is not None and left_label == right_label

    return verify, reviewed_members_by_event


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


def gather_recent_pool(
    session,
    *,
    since,
    min_source_count: int,
    event_ids: set[str] | None = None,
) -> tuple[dict[str, set[str]], set[str]]:
    """(old_membership_by_cluster_id, all_affected_article_ids)."""
    statement = (
        select(EventClusterModel.id)
        .where(EventClusterModel.last_seen_at >= since)
        .where(EventClusterModel.source_count >= min_source_count)
    )
    if event_ids is not None:
        statement = statement.where(EventClusterModel.id.in_(event_ids))
    recent_cluster_ids = set(session.scalars(statement).all())
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


def recompute(
    session,
    *,
    since,
    embedder,
    threshold: float,
    max_event_span_hours: float,
    min_source_count: int,
    event_ids: set[str] | None,
    reviewed_members_by_event: dict[str, set[str]] | None,
    same_event_verifier,
    persist_embeddings: bool,
) -> dict:
    """Shared computation for both --dry-run reporting and --apply. When
    persist_embeddings is True, writes the recomputed vector/source_hash for
    every affected article (does not commit - caller controls the
    transaction)."""
    old_membership, article_ids = gather_recent_pool(
        session,
        since=since,
        min_source_count=min_source_count,
        event_ids=event_ids,
    )
    if not article_ids:
        return {"old_membership": {}, "new_clusters": [], "embeddings_updated": 0}
    if reviewed_members_by_event is not None:
        for event_id, reviewed_members in reviewed_members_by_event.items():
            current_members = old_membership.get(event_id)
            if current_members != reviewed_members:
                raise ValueError(
                    f"review plan for {event_id} is stale: "
                    f"expected {sorted(reviewed_members)}, "
                    f"found {sorted(current_members or set())}"
                )

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

    articles_by_id = {article.id: article for article in articles}
    new_clusters = []
    # Repair is deliberately split-only: re-evaluate every existing event in
    # isolation. A historical cleanup must never merge two previously separate
    # events merely because they happened to be in the same 48-hour audit pool.
    for old_cluster_id, member_ids in old_membership.items():
        old_model = session.get(EventClusterModel, old_cluster_id)
        member_articles = [
            articles_by_id[article_id]
            for article_id in member_ids
            if article_id in articles_by_id
        ]
        regrouped = cluster_articles(
            member_articles,
            embeddings,
            threshold=threshold,
            sources=sources_by_id,
            final_scores=final_scores,
            max_event_span_hours=max_event_span_hours,
            same_event_verifier=same_event_verifier,
        )
        # Preserve the public URL for the subgroup containing the old event's
        # current main article. Other subgroups receive deterministic IDs.
        if old_model is not None:
            preserved = None
            for cluster in regrouped:
                if old_model.main_article_id in cluster.article_ids:
                    cluster.id = old_cluster_id
                    preserved = cluster
                    break
            # The old id is content-derived and may naturally belong to a
            # different subgroup than the event's current main article. Keep
            # ids unique while preserving the current public event URL.
            for cluster in regrouped:
                if cluster is not preserved and cluster.id == old_cluster_id:
                    cluster.id = f"e{stable_hash(f'split:{old_cluster_id}:{cluster.main_article_id}')[:12]}"
        new_clusters.extend(regrouped)
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


def apply(
    session,
    computed: dict,
    *,
    threshold: float,
    cluster_window_hours: int,
    same_event_verifier,
    commit: bool = True,
) -> dict:
    old_membership = computed["old_membership"]
    new_clusters = computed["new_clusters"]
    if not old_membership:
        return {
            "changed_clusters": 0,
            "embeddings_updated": computed["embeddings_updated"],
        }

    changed_old_ids, changed_new_ids = _changed_old_clusters(
        old_membership, new_clusters
    )
    if not changed_old_ids:
        if commit:
            session.commit()
        else:
            session.rollback()
        return {
            "changed_clusters": 0,
            "embeddings_updated": computed["embeddings_updated"],
        }

    new_group_of: dict[str, str] = {}
    for cluster in new_clusters:
        for article_id in cluster.article_ids:
            new_group_of[article_id] = cluster.id

    # Redirect targets carry an immediate FK to event_clusters. Temporarily
    # detach aliases pointing at rows that will be rebuilt, then restore them
    # after the replacement clusters exist again.
    redirects_to_restore = [
        (redirect.source_event_id, redirect.target_event_id)
        for redirect in session.scalars(
            select(EventClusterRedirectModel).where(
                EventClusterRedirectModel.target_event_id.in_(changed_old_ids)
            )
        ).all()
    ]
    for source_event_id, _target_event_id in redirects_to_restore:
        redirect = session.get(EventClusterRedirectModel, source_event_id)
        if redirect is not None:
            session.delete(redirect)
    session.flush()

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
    replacement_clusters = [
        new_by_id[cid] for cid in changed_new_ids if cid in new_by_id
    ]
    # A previously merged event may have left a persistent redirect whose
    # source id is now being restored as one of the split groups. Remove that
    # stale alias before recreating the real event row.
    replacement_ids = {cluster.id for cluster in replacement_clusters}
    stale_redirects = session.scalars(
        select(EventClusterRedirectModel).where(
            EventClusterRedirectModel.source_event_id.in_(replacement_ids)
        )
    ).all()
    for redirect in stale_redirects:
        session.delete(redirect)
    session.flush()

    repository = RadarRepository(session)
    write_result = repository.upsert_event_clusters(
        replacement_clusters,
        cluster_window_hours=cluster_window_hours,
        similarity_threshold=threshold,
        same_event_verifier=same_event_verifier,
    )
    for source_event_id, target_event_id in redirects_to_restore:
        # A split can restore the old source id as a real event (the NVIDIA
        # event ef9… is the production example). In that case the stale alias
        # must stay deleted instead of shadowing the restored event.
        if session.get(EventClusterModel, source_event_id) is not None:
            continue
        resolved_target = write_result.redirects.get(target_event_id, target_event_id)
        if session.get(EventClusterModel, resolved_target) is not None:
            session.add(
                EventClusterRedirectModel(
                    source_event_id=source_event_id,
                    target_event_id=resolved_target,
                )
            )

    for cluster_id in changed_old_ids:
        for article_id in old_membership[cluster_id]:
            resolved_event_id = write_result.redirects.get(
                new_group_of.get(article_id),
                new_group_of.get(article_id),
            )
            processed = session.scalar(
                select(ProcessedArticleModel).where(
                    ProcessedArticleModel.raw_article_id == article_id
                )
            )
            if processed is not None:
                processed.event_cluster_id = resolved_event_id
            for entry in session.scalars(
                select(DailyReportEntryModel).where(
                    DailyReportEntryModel.raw_article_id == article_id
                )
            ).all():
                entry.event_id = resolved_event_id
            for period in session.scalars(select(PeriodReportModel)).all():
                entries = list(period.entries or [])
                changed = False
                for entry in entries:
                    if (
                        isinstance(entry, dict)
                        and entry.get("raw_article_id") == article_id
                    ):
                        entry["event_id"] = resolved_event_id
                        changed = True
                if changed:
                    period.entries = entries
    if commit:
        session.commit()
    else:
        session.flush()
        session.rollback()
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
    parser.add_argument("--cluster-window-hours", type=int, default=24)
    parser.add_argument(
        "--min-source-count",
        type=int,
        default=2,
        help="only audit events currently presented as multi-source hotspots",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.90")),
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the recomputed grouping/embeddings to the database"
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="execute the full write path and roll the transaction back",
    )
    parser.add_argument(
        "--review-plan",
        help="local human-reviewed JSON split manifest; sends no article data externally",
    )
    args = parser.parse_args()
    if args.apply and args.rollback:
        parser.error("--apply and --rollback are mutually exclusive")
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from datetime import datetime, timedelta, timezone

    from app.db.session import build_session_factory, session_scope
    from app.services.ai_service import LocalEmbeddingProvider

    since = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    session_factory = build_session_factory(args.database_url)
    embedder = LocalEmbeddingProvider()
    reviewed_event_ids = None
    reviewed_members_by_event = None
    if args.review_plan:
        same_event_verifier, reviewed_members_by_event = load_review_plan(
            args.review_plan
        )
        reviewed_event_ids = set(reviewed_members_by_event)
    else:
        same_event_verifier = build_same_event_verifier(provider_from_env())
    if (args.apply or args.rollback) and same_event_verifier is None:
        parser.error(
            "--apply requires a real AI provider with same-event verification; "
            "fake/local mode is intentionally fail-closed"
        )

    with session_scope(session_factory) as session:
        computed = recompute(
            session,
            since=since,
            embedder=embedder,
            threshold=args.threshold,
            max_event_span_hours=args.cluster_window_hours,
            min_source_count=args.min_source_count,
            event_ids=reviewed_event_ids,
            reviewed_members_by_event=reviewed_members_by_event,
            same_event_verifier=same_event_verifier,
            persist_embeddings=args.apply or args.rollback,
        )
        if args.apply or args.rollback:
            result = apply(
                session,
                computed,
                threshold=args.threshold,
                cluster_window_hours=args.cluster_window_hours,
                same_event_verifier=same_event_verifier,
                commit=args.apply,
            )
            print(
                f"{'applied' if args.apply else 'rolled back'}: "
                f"{result['changed_clusters']} old event(s) rebuilt into "
                f"{result.get('new_groups', 0)} new group(s), "
                f"{result['embeddings_updated']} embedding(s) refreshed "
                f"(inserted={result.get('inserted', 0)}, updated={result.get('updated', 0)})"
            )
        else:
            print_report(session, computed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
