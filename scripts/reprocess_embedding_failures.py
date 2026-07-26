#!/usr/bin/env python3
"""Reprocess historical articles whose scoring was discarded by an embedding outage.

The old pipeline treated an embedding exception as a whole-article ``ai_error``.
This repair finds only rows that are *still* in that failed state, forces a fresh
score/vector for them, and rebuilds each affected day from the complete persisted
article set. Non-target articles reuse their cached verdicts, so daily reports are
never replaced by a target-only subset.

Dry-run (default):
    .venv/bin/python scripts/reprocess_embedding_failures.py

Apply:
    .venv/bin/python scripts/reprocess_embedding_failures.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.core.config import load_env_file  # noqa: E402
from app.db.models import ProcessedArticleModel, RawArticleModel  # noqa: E402
from app.db.session import build_session_factory, session_scope  # noqa: E402
from app.pipeline.persistence import persist_pipeline_result_to_database  # noqa: E402
from app.pipeline.runner import run_pipeline  # noqa: E402
from app.repositories.radar_repository import RadarRepository  # noqa: E402
from app.services.ai_service import provider_from_env  # noqa: E402
from app.services.refresh_service import _regenerate_period_reports  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
EMBEDDING_FAILURE_MARKERS = (
    "onnxruntimeerror",
    "no_suchfile",
    "no such file",
    "fastembed_cache",
    "embedding model unavailable",
)


def is_embedding_failure(metadata: dict[str, Any]) -> bool:
    error = " ".join(
        str(metadata.get(key) or "") for key in ("embedding_error", "ai_error")
    ).lower()
    return any(marker in error for marker in EMBEDDING_FAILURE_MARKERS)


def is_current_failure(row: RawArticleModel) -> bool:
    return row.skipped_reason == "ai_error" and is_embedding_failure(
        dict(row.raw_metadata or {})
    )


def shanghai_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).date()


def raw_item(row: RawArticleModel, *, clear_failure: bool) -> dict[str, Any]:
    metadata = dict(row.raw_metadata or {})
    raw_score = metadata.pop("raw_score", {})
    if clear_failure:
        metadata.pop("ai_error", None)
        metadata.pop("embedding_error", None)
        if metadata.get("ai_fallback") == "embedding_error":
            metadata.pop("ai_fallback", None)
    return {
        "source_url": row.source_url,
        "title": row.title,
        "content": row.content,
        "author": row.author,
        "published_at": row.published_at,
        "language": row.language,
        "raw_score": raw_score,
        "metadata": metadata,
    }


def load_scope(
    session, *, explicit_target_ids: set[str] | None = None
) -> tuple[dict[date, list[RawArticleModel]], dict[date, set[str]]]:
    explicit_target_ids = explicit_target_ids or set()
    rows = session.scalars(
        select(RawArticleModel).order_by(RawArticleModel.published_at, RawArticleModel.id)
    ).all()
    target_dates = {
        shanghai_date(row.published_at)
        for row in rows
        if is_current_failure(row) or row.id in explicit_target_ids
    }
    all_by_date: dict[date, list[RawArticleModel]] = defaultdict(list)
    targets_by_date: dict[date, set[str]] = defaultdict(set)
    for row in rows:
        report_date = shanghai_date(row.published_at)
        if report_date not in target_dates:
            continue
        all_by_date[report_date].append(row)
        if is_current_failure(row) or row.id in explicit_target_ids:
            targets_by_date[report_date].add(row.id)
    return dict(all_by_date), dict(targets_by_date)


def synchronize_outcome_metadata(
    session,
    *,
    target_ids: set[str],
    result_articles: list[Any],
) -> None:
    """Replace failure outcome keys instead of merging stale outage markers."""
    incoming_by_id = {article.id: article for article in result_articles}
    for article_id in target_ids:
        incoming = incoming_by_id.get(article_id)
        stored = session.get(RawArticleModel, article_id)
        if incoming is None or stored is None:
            continue
        metadata = dict(stored.raw_metadata or {})
        for key in ("ai_error", "embedding_error", "ai_fallback"):
            if key in incoming.metadata:
                metadata[key] = incoming.metadata[key]
            else:
                metadata.pop(key, None)
        stored.raw_metadata = metadata


def resolve_omitted_title_duplicates(
    session,
    *,
    target_ids: set[str],
    result_articles: list[Any],
) -> int:
    """Resolve targets removed by the pipeline's exact-title dedupe.

    They should not remain labeled as an embedding outage forever when the
    same persisted story already has a scored canonical row.
    """
    result_ids = {article.id for article in result_articles}
    resolved = 0
    for article_id in target_ids - result_ids:
        stored = session.get(RawArticleModel, article_id)
        if stored is None:
            continue
        peer = session.scalar(
            select(RawArticleModel)
            .join(
                ProcessedArticleModel,
                ProcessedArticleModel.raw_article_id == RawArticleModel.id,
            )
            .where(
                RawArticleModel.title_hash == stored.title_hash,
                RawArticleModel.id != stored.id,
            )
            .order_by(RawArticleModel.created_at, RawArticleModel.id)
            .limit(1)
        )
        if peer is None:
            continue
        metadata = dict(stored.raw_metadata or {})
        metadata.pop("ai_error", None)
        metadata.pop("embedding_error", None)
        if metadata.get("ai_fallback") == "embedding_error":
            metadata.pop("ai_fallback", None)
        metadata["duplicate_of"] = peer.id
        stored.raw_metadata = metadata
        stored.status = "skipped"
        stored.skipped_reason = "duplicate_title"
        resolved += 1
    return resolved


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> int:
    load_env_file(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--date",
        action="append",
        default=[],
        help="limit to a Shanghai calendar date; repeat for multiple dates",
    )
    parser.add_argument(
        "--article-id",
        action="append",
        default=[],
        help="explicitly retry one stored article even if its current error is no longer embedding-related",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    requested_dates = {date.fromisoformat(value) for value in args.date}
    explicit_target_ids = set(args.article_id)
    session_factory = build_session_factory(args.database_url)
    with session_scope(session_factory) as session:
        all_by_date, targets_by_date = load_scope(
            session, explicit_target_ids=explicit_target_ids
        )
    if requested_dates:
        all_by_date = {
            report_date: rows
            for report_date, rows in all_by_date.items()
            if report_date in requested_dates
        }
        targets_by_date = {
            report_date: ids
            for report_date, ids in targets_by_date.items()
            if report_date in requested_dates
        }

    total_targets = sum(len(ids) for ids in targets_by_date.values())
    print(f"found {total_targets} current embedding-failure article(s)")
    for report_date in sorted(targets_by_date):
        print(
            f"  {report_date.isoformat()}: {len(targets_by_date[report_date])} target(s), "
            f"{len(all_by_date[report_date])} total persisted article(s)"
        )
    if not args.apply or not total_targets:
        return 0

    with session_scope(session_factory) as session:
        repository = RadarRepository(session)
        sources = repository.get_all_sources()
    provider = provider_from_env()
    threshold = _env_float("CLUSTER_SIMILARITY_THRESHOLD", 0.90)
    window_hours = _env_int("CLUSTER_WINDOW_HOURS", 24)
    concurrency = _env_int("AI_PIPELINE_CONCURRENCY", 1)
    selected_targets = 0
    vectorless_targets = 0
    processed_targets = 0
    duplicate_targets = 0
    affected_dates: list[date] = []

    for report_date in sorted(targets_by_date):
        rows = all_by_date[report_date]
        target_ids = targets_by_date[report_date]
        target_url_hashes = {row.url_hash for row in rows if row.id in target_ids}
        raw_items_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            raw_items_by_source[row.source_id].append(
                raw_item(row, clear_failure=row.id in target_ids)
            )

        with session_scope(session_factory) as session:
            cached_results = RadarRepository(session).get_cached_results_by_url_hash(
                [row.url_hash for row in rows]
            )
        for url_hash in target_url_hashes:
            cached_results.pop(url_hash, None)

        started_at = datetime.now(timezone.utc)
        result = run_pipeline(
            sources=sources,
            raw_items_by_source=dict(raw_items_by_source),
            ai_provider=provider,
            now=started_at,
            report_date=report_date,
            ai_concurrency=concurrency,
            skip_prefilter=True,
            cached_results=cached_results,
            cluster_similarity_threshold=threshold,
        )
        persist_pipeline_result_to_database(
            args.database_url,
            sources,
            result,
            cluster_window_hours=window_hours,
            similarity_threshold=threshold,
            started_at=started_at,
        )
        with session_scope(session_factory) as session:
            synchronize_outcome_metadata(
                session,
                target_ids=target_ids,
                result_articles=result.raw_articles,
            )
            day_duplicates = resolve_omitted_title_duplicates(
                session,
                target_ids=target_ids,
                result_articles=result.raw_articles,
            )

        processed_by_id = {
            processed.raw_article_id: processed
            for processed in result.processed_articles
            if processed.raw_article_id in target_ids
        }
        day_processed = len(processed_by_id)
        day_selected = len(
            [processed for processed in processed_by_id.values() if processed.selected]
        )
        day_vectorless = len(
            [article_id for article_id in processed_by_id if article_id not in result.embeddings]
        )
        processed_targets += day_processed
        selected_targets += day_selected
        vectorless_targets += day_vectorless
        duplicate_targets += day_duplicates
        affected_dates.append(report_date)
        print(
            f"reprocessed {report_date.isoformat()}: targets={len(target_ids)}, "
            f"scored={day_processed}, selected={day_selected}, "
            f"vectorless={day_vectorless}, duplicate_titles={day_duplicates}, "
            f"report_items={result.daily_report.article_count}, "
            f"clusters={len(result.event_clusters)}, skipped={result.skipped_reasons}"
        )

    # Two adjacent affected dates can share a month but not a week. Regenerate
    # once per affected week; the last call also leaves the month rollup current.
    period_anchors: dict[tuple[int, int], date] = {}
    for report_date in affected_dates:
        iso = report_date.isocalendar()
        period_anchors[(iso.year, iso.week)] = report_date
    for anchor in sorted(period_anchors.values()):
        _regenerate_period_reports(args.database_url, anchor, provider)

    with session_scope(session_factory) as session:
        remaining = len(
            [
                row
                for row in session.scalars(select(RawArticleModel)).all()
                if is_current_failure(row)
            ]
        )
    print(
        f"complete: targets={total_targets}, scored={processed_targets}, "
        f"selected={selected_targets}, vectorless={vectorless_targets}, "
        f"duplicate_titles={duplicate_targets}, "
        f"remaining_current_failures={remaining}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
