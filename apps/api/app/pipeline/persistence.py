from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from app.crawlers.base import stable_hash
from app.services.ai_service import embedding_input
from app.models.domain import (
    DailyReport,
    EventCluster,
    PipelineResult,
    ProcessedArticle,
    RawArticle,
    Source,
)


class PipelineRepository(Protocol):
    def upsert_sources(self, sources: list[Source]) -> Any:
        ...

    def upsert_raw_articles(self, articles: list[RawArticle]) -> Any:
        ...

    def upsert_article_embedding(
        self, raw_article_id: str, *, embedding_model: str, vector: list[float], source_hash: str
    ) -> Any:
        ...

    def upsert_processed_articles(self, processed_articles: list[ProcessedArticle]) -> Any:
        ...

    def upsert_event_clusters(
        self,
        clusters: list[EventCluster],
        *,
        cluster_window_hours: int = 72,
        similarity_threshold: float = 0.85,
    ) -> Any:
        ...

    def upsert_daily_report(self, report: DailyReport) -> Any:
        ...

    def replace_daily_report_entries(self, report_date: Any, entries: list[dict[str, Any]]) -> Any:
        ...

    def record_pipeline_run(self, **kwargs: Any) -> Any:
        ...


@dataclass(frozen=True)
class PipelinePersistenceSummary:
    sources: Any
    raw_articles: Any
    daily_report: Any
    processed_articles: Any = None
    event_clusters: Any = None
    pipeline_run: Any = None


def persist_pipeline_result(
    repository: PipelineRepository,
    *,
    sources: list[Source],
    result: PipelineResult,
    cluster_window_hours: int = 72,
    similarity_threshold: float = 0.85,
    started_at: datetime | None = None,
) -> PipelinePersistenceSummary:
    source_result = repository.upsert_sources(sources)
    raw_result = repository.upsert_raw_articles(result.raw_articles)

    articles_by_id = {article.id: article for article in result.raw_articles}
    for raw_article_id, vector in result.embeddings.items():
        article = articles_by_id.get(raw_article_id)
        repository.upsert_article_embedding(
            raw_article_id,
            embedding_model=result.embedding_model,
            vector=vector,
            # must hash the same text the vector was computed from (see
            # embedding_input), not just the content
            source_hash=stable_hash(
                embedding_input(article.title, article.content) if article else ""
            ),
        )

    # embeddings must be written first: the repository's cross-day merge
    # looks up existing events' main-article embeddings while deciding
    # whether an incoming cluster should join one instead of creating new
    cluster_result = repository.upsert_event_clusters(
        result.event_clusters,
        cluster_window_hours=cluster_window_hours,
        similarity_threshold=similarity_threshold,
    )
    # a cluster's id was stamped onto processed_articles/daily_report items
    # back in run_pipeline(), before the repository decided (via the merge
    # above) that it should actually join a different, already-existing
    # event instead of creating its own row - remap through redirects or
    # these rows would reference an event_clusters id that was never created
    redirects: dict[str, str] = getattr(cluster_result, "redirects", None) or {}
    processed_articles = result.processed_articles
    if redirects:
        processed_articles = [
            replace(processed, event_cluster_id=redirects.get(processed.event_cluster_id, processed.event_cluster_id))
            for processed in processed_articles
        ]
    processed_result = repository.upsert_processed_articles(processed_articles)
    daily_result = repository.upsert_daily_report(result.daily_report)
    entries: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for item in result.daily_report.json_data.get("items", []):
        event_id = redirects.get(item["event_id"], item["event_id"])
        # two different in-run items can independently redirect into the same
        # pre-existing event; the masthead must still show that event only
        # once (items already arrive ranked highest-score-first, so the
        # first one seen per event_id wins the slot)
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        entries.append(
            {
                "event_id": event_id,
                "raw_article_id": item["raw_article_id"],
                "reason": item.get("reason", ""),
                "final_score": item.get("final_score", 0.0),
            }
        )
    repository.replace_daily_report_entries(result.daily_report.report_date, entries)
    run_result = repository.record_pipeline_run(
        status="succeeded",
        raw_count=len(result.raw_articles),
        processed_count=len(result.processed_articles),
        cluster_count=len(result.event_clusters),
        skipped_reasons=dict(result.skipped_reasons),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
    return PipelinePersistenceSummary(
        sources=source_result,
        raw_articles=raw_result,
        daily_report=daily_result,
        processed_articles=processed_result,
        event_clusters=cluster_result,
        pipeline_run=run_result,
    )


def load_cached_results_from_database(
    database_url: str,
    url_hashes: list[str],
) -> dict[str, Any]:
    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository

    session_factory = build_session_factory(database_url)
    session = session_factory()
    try:
        return RadarRepository(session).get_cached_results_by_url_hash(url_hashes)
    finally:
        session.close()


def persist_pipeline_result_to_database(
    database_url: str,
    sources: list[Source],
    result: PipelineResult,
    *,
    cluster_window_hours: int = 72,
    similarity_threshold: float = 0.85,
    started_at: datetime | None = None,
) -> PipelinePersistenceSummary:
    from app.db.session import build_session_factory, session_scope
    from app.repositories.radar_repository import RadarRepository

    session_factory = build_session_factory(database_url)
    with session_scope(session_factory) as session:
        repository = RadarRepository(session)
        return persist_pipeline_result(
            repository,
            sources=sources,
            result=result,
            cluster_window_hours=cluster_window_hours,
            similarity_threshold=similarity_threshold,
            started_at=started_at,
        )


def record_failed_pipeline_run(
    database_url: str, *, started_at: datetime | None, error: str
) -> None:
    """Leave a durable trace of a failed run. Must never mask the original
    failure, so any error while recording (e.g. the DB itself being down)
    is swallowed."""
    try:
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            RadarRepository(session).record_pipeline_run(
                status="failed",
                raw_count=0,
                processed_count=0,
                cluster_count=0,
                skipped_reasons={},
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error=error,
            )
    except Exception:  # pragma: no cover - best-effort bookkeeping
        pass
