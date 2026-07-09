from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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

    def upsert_processed_articles(self, processed_articles: list[ProcessedArticle]) -> Any:
        ...

    def upsert_event_clusters(self, clusters: list[EventCluster]) -> Any:
        ...

    def upsert_daily_report(self, report: DailyReport) -> Any:
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
) -> PipelinePersistenceSummary:
    source_result = repository.upsert_sources(sources)
    raw_result = repository.upsert_raw_articles(result.raw_articles)
    cluster_result = repository.upsert_event_clusters(result.event_clusters)
    processed_result = repository.upsert_processed_articles(result.processed_articles)
    daily_result = repository.upsert_daily_report(result.daily_report)
    run_result = repository.record_pipeline_run(
        status="succeeded",
        raw_count=len(result.raw_articles),
        processed_count=len(result.processed_articles),
        cluster_count=len(result.event_clusters),
        skipped_reasons=dict(result.skipped_reasons),
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
) -> PipelinePersistenceSummary:
    from app.db.session import build_session_factory, session_scope
    from app.repositories.radar_repository import RadarRepository

    session_factory = build_session_factory(database_url)
    with session_scope(session_factory) as session:
        repository = RadarRepository(session)
        return persist_pipeline_result(repository, sources=sources, result=result)
