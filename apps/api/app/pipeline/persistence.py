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

    def upsert_raw_articles(self, articles: list[RawArticle], **kwargs: Any) -> Any:
        ...

    def upsert_article_embedding(
        self,
        raw_article_id: str,
        *,
        embedding_model: str,
        vector: list[float],
        source_hash: str,
        **kwargs: Any,
    ) -> Any:
        ...

    def upsert_processed_articles(
        self, processed_articles: list[ProcessedArticle], **kwargs: Any
    ) -> Any:
        ...

    def upsert_event_clusters(
        self,
        clusters: list[EventCluster],
        *,
        cluster_window_hours: int = 72,
        similarity_threshold: float = 0.85,
    ) -> Any:
        ...

    def upsert_daily_report(self, report: DailyReport, **kwargs: Any) -> Any:
        ...

    def replace_daily_report_entries(self, report_date: Any, entries: list[dict[str, Any]]) -> Any:
        ...

    def record_pipeline_run(self, **kwargs: Any) -> Any:
        ...

    def finish_pipeline_run(self, run_id: int, *, status: str, **kwargs: Any) -> Any:
        ...


@dataclass(frozen=True)
class PipelinePersistenceSummary:
    sources: Any
    raw_articles: Any
    daily_report: Any
    processed_articles: Any = None
    event_clusters: Any = None
    pipeline_run: Any = None
    # 台账漏斗指标(2026-07-12 深夜):单一事实源,下游(Telegram 通知等)
    # 直接读取,不再各自重算——避免两处口径不一致
    new_raw_count: int = 0
    new_selected_count: int = 0
    non_ai_dropped_count: int = 0


def persist_pipeline_result(
    repository: PipelineRepository,
    *,
    sources: list[Source],
    result: PipelineResult,
    cluster_window_hours: int = 72,
    similarity_threshold: float = 0.85,
    started_at: datetime | None = None,
    pipeline_run_id: int | None = None,
    source_report: dict[str, Any] | None = None,
    intake_inserted_ids: list[str] | None = None,
) -> PipelinePersistenceSummary:
    source_result = repository.upsert_sources(sources)
    raw_result = repository.upsert_raw_articles(
        result.raw_articles, pipeline_run_id=pipeline_run_id
    )

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
            pipeline_run_id=pipeline_run_id,
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
    processed_result = repository.upsert_processed_articles(
        processed_articles, pipeline_run_id=pipeline_run_id
    )
    daily_result = repository.upsert_daily_report(
        result.daily_report, pipeline_run_id=pipeline_run_id
    )
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
    # ledger ingest metrics: what did this run actually contribute, as
    # opposed to re-processing already-known articles via the AI cache.
    # 新文章清单以 intake(抓取后立即落库)为准;CLI/JSON 模式没有 intake,
    # 回退到本次 upsert 的插入清单。恒等式:抓取 = 重复 + 非AI + 入库
    if intake_inserted_ids is not None:
        new_ids = set(intake_inserted_ids)
    else:
        new_ids = set(getattr(raw_result, "inserted_ids", None) or [])
    non_ai_dropped_count = len(
        [
            article_id
            for article_id in new_ids
            if result.skipped_reason_by_raw_id.get(article_id) == "not_ai_related"
        ]
    )
    # 入库 = 新文章中通过筛选的;非AI 行虽然保留(跳过标记)但不算入库
    new_raw_count = len(new_ids) - non_ai_dropped_count
    new_selected_count = len(
        [
            processed
            for processed in result.processed_articles
            if processed.selected and processed.raw_article_id in new_ids
        ]
    )
    if pipeline_run_id is not None:
        # the run row was created up-front as 'running'; close it out
        run_result = repository.finish_pipeline_run(
            pipeline_run_id,
            status="succeeded",
            raw_count=len(result.raw_articles),
            processed_count=len(result.processed_articles),
            cluster_count=len(result.event_clusters),
            new_raw_count=new_raw_count,
            new_selected_count=new_selected_count,
            non_ai_dropped_count=non_ai_dropped_count,
            skipped_reasons=dict(result.skipped_reasons),
            source_report=source_report,
            finished_at=datetime.now(timezone.utc),
        )
    else:
        # CLI/legacy path with no up-front run row: record after the fact
        run_result = repository.record_pipeline_run(
            status="succeeded",
            raw_count=len(result.raw_articles),
            processed_count=len(result.processed_articles),
            cluster_count=len(result.event_clusters),
            new_raw_count=new_raw_count,
            new_selected_count=new_selected_count,
            non_ai_dropped_count=non_ai_dropped_count,
            skipped_reasons=dict(result.skipped_reasons),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            source_report=source_report,
        )
    return PipelinePersistenceSummary(
        sources=source_result,
        raw_articles=raw_result,
        daily_report=daily_result,
        processed_articles=processed_result,
        event_clusters=cluster_result,
        pipeline_run=run_result,
        new_raw_count=new_raw_count,
        new_selected_count=new_selected_count,
        non_ai_dropped_count=non_ai_dropped_count,
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
    pipeline_run_id: int | None = None,
    source_report: dict[str, Any] | None = None,
    intake_inserted_ids: list[str] | None = None,
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
            pipeline_run_id=pipeline_run_id,
            source_report=source_report,
            intake_inserted_ids=intake_inserted_ids,
        )


def persist_raw_intake_to_database(
    database_url: str,
    articles: list[Any],
    *,
    pipeline_run_id: int | None = None,
) -> list[str] | None:
    """四步流程第 1 步(2026-07-12):抓取一结束就把新文章插入库
    (status='raw',未入选默认态),让数据先于 AI 处理可见。返回本轮新
    插入的文章 id 清单,作为台账"入库/非AI"指标的事实源。Best-effort:
    失败返回 None(调用方回退到最终 upsert 的插入清单),只损失即时
    可见性,整轮结束后的全量 upsert 仍会补齐数据。"""
    try:
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            result = RadarRepository(session).insert_missing_raw_articles(
                articles, pipeline_run_id=pipeline_run_id
            )
            return list(result.inserted_ids)
    except Exception:  # pragma: no cover - best-effort visibility
        return None


def persist_single_article_to_database(
    database_url: str,
    article: Any,
    processed: Any,
    embedding: list[float] | None,
    *,
    embedding_model: str = "",
    pipeline_run_id: int | None = None,
) -> None:
    """逐条即时落库(2026-07-12 深夜决策):每评完一条马上写库,让数据
    在整轮结束前就持续可见。幂等 upsert;event_cluster_id 此时为 None,
    聚类归属由整轮结束后的最终落库补写(None 不会覆盖已有值)。
    Best-effort:失败只损失即时可见性。"""
    try:
        from app.crawlers.base import stable_hash
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import embedding_input

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            repository = RadarRepository(session)
            repository.upsert_raw_articles([article], pipeline_run_id=pipeline_run_id)
            repository.upsert_processed_articles([processed], pipeline_run_id=pipeline_run_id)
            if embedding is not None:
                repository.upsert_article_embedding(
                    article.id,
                    embedding_model=embedding_model,
                    vector=embedding,
                    source_hash=stable_hash(embedding_input(article.title, article.content)),
                    pipeline_run_id=pipeline_run_id,
                )
    except Exception:  # pragma: no cover - best-effort visibility
        return


def start_pipeline_run_in_database(
    database_url: str, *, started_at: datetime | None = None, phase: str | None = None
) -> int | None:
    """Create the 'running' row the moment a refresh begins. Best-effort:
    a DB hiccup must not stop the pipeline, it only costs lineage."""
    try:
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            return RadarRepository(session).start_pipeline_run(
                started_at=started_at, phase=phase
            )
    except Exception:  # pragma: no cover - best-effort bookkeeping
        return None


def get_active_pipeline_run_in_database(
    database_url: str, *, stale_after_minutes: int = 45
) -> dict[str, Any] | None:
    """Cross-process concurrency guard: sweep orphaned running rows, then
    return the freshest live one (or None). Best-effort: a DB hiccup means
    "unknown", reported as None so the pipeline itself is never blocked by
    guard bookkeeping."""
    try:
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            repository = RadarRepository(session)
            repository.sweep_stale_pipeline_runs(max_age_minutes=stale_after_minutes)
            return repository.get_active_pipeline_run()
    except Exception:  # pragma: no cover - best-effort bookkeeping
        return None


def update_pipeline_run_progress_in_database(
    database_url: str,
    run_id: int,
    *,
    phase: str | None = None,
    raw_count: int | None = None,
    source_report: dict[str, Any] | None = None,
) -> None:
    """Best-effort progress heartbeat on the running row."""
    try:
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            RadarRepository(session).update_pipeline_run_progress(
                run_id, phase=phase, raw_count=raw_count, source_report=source_report
            )
    except Exception:  # pragma: no cover - best-effort bookkeeping
        pass


def record_failed_pipeline_run(
    database_url: str,
    *,
    started_at: datetime | None,
    error: str,
    pipeline_run_id: int | None = None,
) -> None:
    """Leave a durable trace of a failed run. Must never mask the original
    failure, so any error while recording (e.g. the DB itself being down)
    is swallowed."""
    try:
        from app.db.session import build_session_factory, session_scope
        from app.repositories.radar_repository import RadarRepository

        session_factory = build_session_factory(database_url)
        with session_scope(session_factory) as session:
            repository = RadarRepository(session)
            if pipeline_run_id is not None:
                repository.finish_pipeline_run(
                    pipeline_run_id,
                    status="failed",
                    error=error,
                    finished_at=datetime.now(timezone.utc),
                )
            else:
                repository.record_pipeline_run(
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
