from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Optional

try:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard for local stdlib tests
    raise RuntimeError("SQLAlchemy is required for database repositories.") from exc

from app.db.models import (
    DailyReportModel,
    EventClusterArticleModel,
    EventClusterModel,
    PipelineRunModel,
    ProcessedArticleModel,
    RawArticleModel,
    SourceModel,
)
from app.models.domain import DailyReport, EventCluster, ProcessedArticle, RawArticle, Source


@dataclass(frozen=True)
class WriteResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


class RadarRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_sources(self, sources: list[Source]) -> WriteResult:
        inserted = 0
        updated = 0
        for source in sources:
            model = self.session.get(SourceModel, source.id)
            if model is None:
                self.session.add(_source_to_model(source))
                inserted += 1
            else:
                _apply_source(model, source)
                updated += 1
        return WriteResult(inserted=inserted, updated=updated)

    def upsert_raw_articles(self, articles: list[RawArticle]) -> WriteResult:
        inserted = 0
        skipped = 0
        seen_url_hashes: set[str] = set()
        for article in articles:
            if article.url_hash in seen_url_hashes or self._raw_article_exists(article.url_hash):
                skipped += 1
                continue
            seen_url_hashes.add(article.url_hash)
            self.session.add(_raw_article_to_model(article))
            inserted += 1
        return WriteResult(inserted=inserted, skipped=skipped)

    def upsert_daily_report(self, report: DailyReport) -> WriteResult:
        model = self.session.scalar(
            select(DailyReportModel).where(DailyReportModel.report_date == report.report_date)
        )
        if model is None:
            self.session.add(_daily_report_to_model(report))
            return WriteResult(inserted=1)

        _apply_daily_report(model, report)
        return WriteResult(updated=1)

    def get_daily_report_payload(self, report_date: date) -> Optional[dict[str, Any]]:
        model = self.session.scalar(
            select(DailyReportModel).where(DailyReportModel.report_date == report_date)
        )
        if model is None:
            return None
        return _daily_report_payload(model)

    def upsert_processed_articles(self, processed_articles: list[ProcessedArticle]) -> WriteResult:
        inserted = 0
        updated = 0
        for processed in processed_articles:
            model = self.session.scalar(
                select(ProcessedArticleModel).where(
                    ProcessedArticleModel.raw_article_id == processed.raw_article_id
                )
            )
            if model is None:
                model = ProcessedArticleModel(raw_article_id=processed.raw_article_id)
                self.session.add(model)
                inserted += 1
            else:
                updated += 1
            _apply_processed_article(model, processed)
        return WriteResult(inserted=inserted, updated=updated)

    def upsert_event_clusters(self, clusters: list[EventCluster]) -> WriteResult:
        inserted = 0
        updated = 0
        for cluster in clusters:
            model = self.session.get(EventClusterModel, cluster.id)
            if model is None:
                model = EventClusterModel(id=cluster.id)
                self.session.add(model)
                inserted += 1
            else:
                updated += 1
            _apply_event_cluster(model, cluster)
            existing_memberships = self.session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == cluster.id
                )
            ).all()
            for membership in existing_memberships:
                self.session.delete(membership)
            for priority, article_id in enumerate(cluster.article_ids):
                self.session.add(
                    EventClusterArticleModel(
                        event_cluster_id=cluster.id,
                        raw_article_id=article_id,
                        is_main=article_id == cluster.main_article_id,
                        source_priority=priority,
                    )
                )
        self.session.flush()
        return WriteResult(inserted=inserted, updated=updated)

    def record_pipeline_run(
        self,
        *,
        status: str,
        raw_count: int,
        processed_count: int,
        cluster_count: int,
        skipped_reasons: dict[str, int],
        started_at: Any = None,
        finished_at: Any = None,
        error: str | None = None,
    ) -> WriteResult:
        model = PipelineRunModel(
            status=status,
            raw_count=raw_count,
            processed_count=processed_count,
            cluster_count=cluster_count,
            skipped_reasons=dict(skipped_reasons),
            error=error,
        )
        if started_at is not None:
            model.started_at = started_at
        if finished_at is not None:
            model.finished_at = finished_at
        self.session.add(model)
        return WriteResult(inserted=1)

    CACHED_METADATA_KEYS = (
        "translated_paragraphs",
        "translated_blocks",
        "translation_source_language",
        "translation_target_language",
        "original_markdown",
        "readme_name",
        "readme_language",
        "readme_selection",
    )

    def get_cached_results_by_url_hash(self, url_hashes: list[str]) -> dict[str, dict[str, Any]]:
        if not url_hashes:
            return {}
        rows = self.session.execute(
            select(RawArticleModel, ProcessedArticleModel)
            .join(
                ProcessedArticleModel,
                ProcessedArticleModel.raw_article_id == RawArticleModel.id,
                isouter=True,
            )
            .where(RawArticleModel.url_hash.in_(url_hashes))
        ).all()
        cached: dict[str, dict[str, Any]] = {}
        for raw, processed in rows:
            raw_metadata = dict(raw.raw_metadata or {})
            metadata = {
                key: raw_metadata[key]
                for key in self.CACHED_METADATA_KEYS
                if raw_metadata.get(key)
            }
            scoring = None
            if processed is not None:
                scoring = {
                    "dimensions": {
                        "ai_relevance": processed.ai_relevance,
                        "novelty": processed.novelty,
                        "impact": processed.impact,
                        "information_density": processed.information_density,
                        "actionability": processed.actionability,
                        "creator_value": processed.creator_value,
                    },
                    "category": processed.category,
                    "tags": list(processed.tags or []),
                    "title_zh": processed.title_zh,
                    "one_line_summary": processed.one_line_summary,
                    "summary_zh": processed.summary_zh,
                    "reason_zh": processed.reason_zh,
                    "action_zh": processed.action_zh,
                }
            cached[raw.url_hash] = {
                "scoring": scoring,
                "skipped_reason": raw.skipped_reason if scoring is None else None,
                "metadata": metadata,
            }
        return cached

    _EVENT_CONTENT_METADATA_KEYS = (
        "original_paragraphs",
        "original_blocks",
        "original_markdown",
        "translated_paragraphs",
        "translated_blocks",
        "translated_content",
        "translation_status",
        "translation_error",
        "readme_name",
        "readme_language",
        "readme_selection",
    )

    def get_all_event_items_between(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        window_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        window_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
        rows = self.session.execute(
            select(ProcessedArticleModel, RawArticleModel, SourceModel)
            .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
            .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
            .where(RawArticleModel.published_at >= window_start)
            .where(RawArticleModel.published_at <= window_end)
            .order_by(RawArticleModel.published_at.desc())
        ).all()
        return [
            _event_item(processed, raw, source, include_content=False)
            for processed, raw, source in rows
        ]

    def get_event_item(self, event_id: str) -> Optional[dict[str, Any]]:
        cluster = self.session.get(EventClusterModel, event_id)
        if cluster is not None:
            row = self.session.execute(
                select(ProcessedArticleModel, RawArticleModel, SourceModel)
                .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
                .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
                .where(ProcessedArticleModel.raw_article_id == cluster.main_article_id)
            ).first()
        elif event_id.startswith("a"):
            row = self.session.execute(
                select(ProcessedArticleModel, RawArticleModel, SourceModel)
                .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
                .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
                .where(RawArticleModel.id.like(f"{event_id[1:]}%"))
            ).first()
        else:
            row = None
        if row is None:
            return None
        processed, raw, source = row
        return _event_item(processed, raw, source, include_content=True)

    def get_daily_report_payloads_between(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(DailyReportModel)
            .where(DailyReportModel.report_date >= start_date)
            .where(DailyReportModel.report_date <= end_date)
            .order_by(DailyReportModel.report_date.asc())
        )
        return [_daily_report_payload(model) for model in models]

    def get_latest_daily_report_payload(self) -> Optional[dict[str, Any]]:
        model = self.session.scalar(
            select(DailyReportModel).order_by(DailyReportModel.report_date.desc()).limit(1)
        )
        if model is None:
            return None
        return _daily_report_payload(model)

    def _raw_article_exists(self, url_hash: str) -> bool:
        return (
            self.session.scalar(
                select(RawArticleModel.id).where(RawArticleModel.url_hash == url_hash).limit(1)
            )
            is not None
        )


def _source_to_model(source: Source) -> SourceModel:
    model = SourceModel(id=source.id)
    _apply_source(model, source)
    return model


def _apply_source(model: SourceModel, source: Source) -> None:
    model.name = source.name
    model.source_role = source.source_role
    model.tier = source.tier
    model.type = source.type
    model.category = source.category
    model.url = source.url
    model.homepage = source.homepage
    model.allowed_domains = list(source.allowed_domains)
    model.fetch_interval_min = source.fetch_interval_min
    model.language = source.language
    model.need_proxy = source.need_proxy
    model.need_browser = source.need_browser
    model.can_be_main_source = source.can_be_main_source
    model.affects_heat_score = source.affects_heat_score
    model.is_active = source.is_active
    model.config_json = dict(source.config)


def _raw_article_to_model(article: RawArticle) -> RawArticleModel:
    return RawArticleModel(
        id=article.id,
        source_id=article.source_id,
        source_url=article.source_url,
        title=article.title,
        content=article.content,
        author=article.author,
        language=article.language,
        published_at=article.published_at,
        title_hash=article.title_hash,
        url_hash=article.url_hash,
        raw_metadata={"raw_score": article.raw_score, **article.metadata},
        status=article.status,
        skipped_reason=article.skipped_reason,
    )


def _event_item(
    processed: ProcessedArticleModel,
    raw: RawArticleModel,
    source: SourceModel,
    *,
    include_content: bool,
) -> dict[str, Any]:
    metadata = dict(raw.raw_metadata or {})
    published_at = raw.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    item: dict[str, Any] = {
        "event_id": processed.event_cluster_id or f"a{raw.id[:12]}",
        "title": processed.title_zh or raw.title,
        "category": processed.category,
        "tags": list(processed.tags or []),
        "final_score": processed.final_score,
        "selected": processed.status == "processed",
        "source_count": 1,
        "main_source": {"name": source.name, "url": raw.source_url, "tier": source.tier},
        "source_language": raw.language,
        "one_line_summary": processed.one_line_summary,
        "summary": processed.summary_zh,
        "reason": processed.reason_zh,
        "action": processed.action_zh,
        "published_at": published_at.isoformat() if published_at else None,
        "original_url": raw.source_url,
    }
    images = metadata.get("original_images")
    if images:
        item["original_images"] = images
    if include_content:
        paragraphs = metadata.get("original_paragraphs") or []
        item["original_content"] = str(
            metadata.get("original_text") or "\n\n".join(str(p) for p in paragraphs)
        )
        item["original_paragraphs"] = paragraphs
        item["original_blocks"] = metadata.get("original_blocks") or []
        for key in RadarRepository._EVENT_CONTENT_METADATA_KEYS:
            value = metadata.get(key)
            if value:
                item[key] = value
    return item


def _apply_processed_article(model: ProcessedArticleModel, processed: ProcessedArticle) -> None:
    model.event_cluster_id = processed.event_cluster_id
    model.ai_relevance = processed.dimensions.ai_relevance
    model.novelty = processed.dimensions.novelty
    model.impact = processed.dimensions.impact
    model.information_density = processed.dimensions.information_density
    model.actionability = processed.dimensions.actionability
    model.creator_value = processed.dimensions.creator_value
    model.base_score = processed.base_score
    model.final_score = processed.final_score
    model.title_zh = processed.title_zh
    model.one_line_summary = processed.one_line_summary
    model.summary_zh = processed.summary_zh
    model.reason_zh = processed.reason_zh
    model.action_zh = processed.action_zh
    model.category = processed.category
    model.tags = list(processed.tags)
    model.status = processed.status
    model.rejection_reason = processed.rejection_reason


def _apply_event_cluster(model: EventClusterModel, cluster: EventCluster) -> None:
    model.main_article_id = cluster.main_article_id
    model.event_title = cluster.event_title
    model.event_summary = cluster.event_summary
    model.category = cluster.category
    model.tags = list(cluster.tags)
    model.final_score = cluster.final_score
    model.source_count = cluster.source_count
    model.first_seen_at = cluster.first_seen_at
    model.last_seen_at = cluster.last_seen_at
    model.status = cluster.status


def _daily_report_to_model(report: DailyReport) -> DailyReportModel:
    model = DailyReportModel(report_date=report.report_date)
    _apply_daily_report(model, report)
    return model


def _apply_daily_report(model: DailyReportModel, report: DailyReport) -> None:
    payload = dict(report.json_data)
    model.title = payload.get("title", f"Suversal AI Radar 日报 - {report.report_date.isoformat()}")
    model.summary = payload.get("summary", "")
    model.sections = payload
    model.article_count = report.article_count
    model.markdown = report.markdown
    model.status = report.status


def _daily_report_payload(model: DailyReportModel) -> dict[str, Any]:
    payload = dict(model.sections or {})
    payload["report_date"] = model.report_date.isoformat()
    payload["title"] = model.title
    payload["summary"] = model.summary
    payload["article_count"] = model.article_count
    payload.setdefault("items", [])
    payload.setdefault("sections", {})
    return payload
