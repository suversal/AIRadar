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
    PeriodReportModel,
    EventClusterArticleModel,
    EventClusterModel,
    PipelineRunModel,
    ProcessedArticleModel,
    RawArticleModel,
    SourceModel,
)
from app.models.domain import DailyReport, EventCluster, ProcessedArticle, RawArticle, Source
from app.services.taxonomy import category_label, display_category


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
        updated = 0
        skipped = 0
        seen_url_hashes: set[str] = set()
        for article in articles:
            if article.url_hash in seen_url_hashes:
                skipped += 1
                continue
            seen_url_hashes.add(article.url_hash)
            existing = self.session.scalar(
                select(RawArticleModel).where(RawArticleModel.url_hash == article.url_hash)
            )
            if existing is None:
                self.session.add(_raw_article_to_model(article))
                inserted += 1
                continue
            # later runs enrich articles in memory (README, full-page body,
            # translations); merge that back instead of freezing the first crawl
            merged = dict(existing.raw_metadata or {})
            merged.update({"raw_score": article.raw_score, **article.metadata})
            existing.raw_metadata = merged
            if len(article.content) > len(existing.content or ""):
                existing.content = article.content
            existing.status = article.status
            existing.skipped_reason = article.skipped_reason
            updated += 1
        return WriteResult(inserted=inserted, updated=updated, skipped=skipped)

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

    def upsert_period_report(self, report: dict[str, Any]) -> WriteResult:
        model = self.session.scalar(
            select(PeriodReportModel).where(
                PeriodReportModel.kind == report["kind"],
                PeriodReportModel.period_key == report["period_key"],
            )
        )
        inserted = 0
        updated = 0
        if model is None:
            model = PeriodReportModel(kind=report["kind"], period_key=report["period_key"])
            self.session.add(model)
            inserted = 1
        else:
            updated = 1
        model.range_start = date.fromisoformat(report["range_start"])
        model.range_end = date.fromisoformat(report["range_end"])
        model.mainline_title = report["mainline_title"]
        model.mainline_body = report["mainline_body"]
        model.theme_notes = list(report.get("theme_notes") or [])
        model.article_count = int(report.get("article_count") or 0)
        model.report_dates = list(report.get("report_dates") or [])
        model.status = report.get("status") or "generated"
        return WriteResult(inserted=inserted, updated=updated)

    def get_period_report(self, kind: str, period_key: str) -> Optional[dict[str, Any]]:
        model = self.session.scalar(
            select(PeriodReportModel).where(
                PeriodReportModel.kind == kind,
                PeriodReportModel.period_key == period_key,
            )
        )
        if model is None:
            return None
        return _period_report_payload(model)

    def list_period_reports(self, kind: str, limit: int = 24) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(PeriodReportModel)
            .where(PeriodReportModel.kind == kind)
            .order_by(PeriodReportModel.period_key.desc())
            .limit(limit)
        ).all()
        return [_period_report_payload(model) for model in models]

    def list_daily_report_dates(self, limit: int = 90) -> list[str]:
        models = self.session.scalars(
            select(DailyReportModel.report_date)
            .order_by(DailyReportModel.report_date.desc())
            .limit(limit)
        ).all()
        return [value.isoformat() for value in models]

    def update_source_health(self, per_source: dict[str, dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc)
        for source_id, report in per_source.items():
            model = self.session.get(SourceModel, source_id)
            if model is None:
                continue
            ok = report.get("status") == "ok"
            had_history = model.last_crawled_at is not None
            model.last_crawled_at = now
            if ok:
                model.last_success_at = now
                model.error_count = 0
            else:
                model.error_count = (model.error_count or 0) + 1
            observation = 1.0 if ok else 0.0
            if not had_history:
                # first observation is authoritative
                model.success_rate = observation
            else:
                # exponential moving average keeps the rate responsive
                # without storing full history
                previous = model.success_rate or 0.0
                model.success_rate = round(0.8 * previous + 0.2 * observation, 4)

    SOURCE_EDITABLE_FIELDS = {
        "name",
        "url",
        "homepage",
        "tier",
        "category",
        "source_role",
        "type",
        "language",
        "fetch_interval_min",
        "is_active",
        "can_be_main_source",
        "affects_heat_score",
        "config",
    }

    def update_source_fields(self, source_id: str, fields: dict[str, Any]) -> bool:
        model = self.session.get(SourceModel, source_id)
        if model is None:
            return False
        for key, value in fields.items():
            if key not in self.SOURCE_EDITABLE_FIELDS:
                continue
            if key == "config":
                model.config_json = dict(value or {})
            else:
                setattr(model, key, value)
        return True

    def get_all_sources(self) -> list[Source]:
        models = self.session.scalars(select(SourceModel)).all()
        return [_source_to_domain(model) for model in models]

    def list_sources_with_health(self) -> list[dict[str, Any]]:
        models = self.session.scalars(select(SourceModel)).all()
        return [
            {
                "id": model.id,
                "name": model.name,
                "type": model.type,
                "tier": model.tier,
                "category": model.category,
                "url": model.url,
                "is_active": model.is_active,
                "fetch_interval_min": model.fetch_interval_min,
                "language": model.language,
                "last_crawled_at": model.last_crawled_at.isoformat() if model.last_crawled_at else None,
                "last_success_at": model.last_success_at.isoformat() if model.last_success_at else None,
                "success_rate": model.success_rate,
                "error_count": model.error_count,
                "config": dict(model.config_json or {}),
            }
            for model in models
        ]

    def get_recent_pipeline_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(PipelineRunModel).order_by(PipelineRunModel.id.desc()).limit(limit)
        ).all()
        return [
            {
                "id": model.id,
                "started_at": model.started_at.isoformat() if model.started_at else None,
                "finished_at": model.finished_at.isoformat() if model.finished_at else None,
                "status": model.status,
                "raw_count": model.raw_count,
                "processed_count": model.processed_count,
                "cluster_count": model.cluster_count,
                "skipped_reasons": dict(model.skipped_reasons or {}),
                "error": model.error,
            }
            for model in models
        ]

    def get_table_counts(self) -> dict[str, int]:
        from sqlalchemy import func as sa_func

        counts = {}
        for name, model in (
            ("sources", SourceModel),
            ("raw_articles", RawArticleModel),
            ("processed_articles", ProcessedArticleModel),
            ("event_clusters", EventClusterModel),
            ("daily_reports", DailyReportModel),
            ("pipeline_runs", PipelineRunModel),
        ):
            counts[name] = int(
                self.session.scalar(sa_func.count(model.id).select()) or 0
            )
        return counts

    CACHED_METADATA_KEYS = (
        "translated_paragraphs",
        "translated_blocks",
        "translation_source_language",
        "translation_source_hash",
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
        self, start_date: date, end_date: date, *, include_hidden: bool = False
    ) -> list[dict[str, Any]]:
        window_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        window_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
        query = (
            select(ProcessedArticleModel, RawArticleModel, SourceModel)
            .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
            .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
            .where(RawArticleModel.published_at >= window_start)
            .where(RawArticleModel.published_at <= window_end)
            .order_by(RawArticleModel.published_at.desc())
        )
        if not include_hidden:
            query = query.where(ProcessedArticleModel.status != "hidden")
        rows = self.session.execute(query).all()
        return [
            _event_item(processed, raw, source, include_content=False)
            for processed, raw, source in rows
        ]

    def _resolve_processed_row(self, event_id: str):
        cluster = self.session.get(EventClusterModel, event_id)
        if cluster is not None:
            return self.session.execute(
                select(ProcessedArticleModel, RawArticleModel, SourceModel)
                .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
                .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
                .where(ProcessedArticleModel.raw_article_id == cluster.main_article_id)
            ).first()
        if event_id.startswith("a"):
            return self.session.execute(
                select(ProcessedArticleModel, RawArticleModel, SourceModel)
                .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
                .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
                .where(RawArticleModel.id.like(f"{event_id[1:]}%"))
            ).first()
        return None

    EVENT_MODERATION_FIELDS = {"hidden", "title_zh", "category", "tags"}

    def update_event_moderation(self, event_id: str, fields: dict[str, Any]) -> bool:
        row = self._resolve_processed_row(event_id)
        if row is None:
            return False
        processed, _raw, _source = row
        for key, value in fields.items():
            if key not in self.EVENT_MODERATION_FIELDS:
                continue
            if key == "hidden":
                if value:
                    processed.status = "hidden"
                else:
                    # restore to the status implied by the stored verdict
                    processed.status = "rejected" if processed.rejection_reason else "processed"
            elif key == "tags":
                processed.tags = [str(tag) for tag in (value or [])][:5]
            else:
                setattr(processed, key, str(value))
        return True

    def get_event_item(self, event_id: str) -> Optional[dict[str, Any]]:
        row = self._resolve_processed_row(event_id)
        if row is None:
            return None
        processed, raw, source = row
        if processed.status == "hidden":
            return None
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


def _period_report_payload(model: PeriodReportModel) -> dict[str, Any]:
    return {
        "kind": model.kind,
        "period_key": model.period_key,
        "range_start": model.range_start.isoformat(),
        "range_end": model.range_end.isoformat(),
        "mainline_title": model.mainline_title,
        "mainline_body": model.mainline_body,
        "theme_notes": list(model.theme_notes or []),
        "article_count": model.article_count,
        "report_dates": list(model.report_dates or []),
        "generated_at": model.generated_at.isoformat() if model.generated_at else None,
        "status": model.status,
    }


def _source_to_domain(model: SourceModel) -> Source:
    return Source(
        id=model.id,
        name=model.name,
        source_role=model.source_role,
        tier=model.tier,
        type=model.type,
        category=model.category,
        url=model.url,
        homepage=model.homepage,
        allowed_domains=list(model.allowed_domains or []),
        fetch_interval_min=model.fetch_interval_min,
        language=model.language,
        need_proxy=model.need_proxy,
        need_browser=model.need_browser,
        can_be_main_source=model.can_be_main_source,
        affects_heat_score=model.affects_heat_score,
        is_active=model.is_active,
        config=dict(model.config_json or {}),
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
        "category": display_category(processed.category),
        "category_label": category_label(processed.category),
        "scoring_category": processed.category,
        "tags": list(processed.tags or []),
        "final_score": processed.final_score,
        "selected": processed.status == "processed",
        "hidden": processed.status == "hidden",
        "source_count": 1,
        "main_source": {"name": source.name, "url": raw.source_url, "tier": source.tier},
        "source_language": raw.language,
        "one_line_summary": processed.one_line_summary,
        "summary": processed.summary_zh,
        "reason": processed.reason_zh,
        "action": processed.action_zh,
        "published_at": published_at.isoformat() if published_at else None,
        "crawled_at": raw.crawled_at.isoformat() if raw.crawled_at else None,
        "original_url": raw.source_url,
    }
    images = metadata.get("original_images")
    if images:
        item["original_images"] = images
    if include_content:
        paragraphs = metadata.get("original_paragraphs") or []
        content = str(
            metadata.get("original_text") or "\n\n".join(str(p) for p in paragraphs)
        ).strip()
        if not content:
            # fall back to the crawled body (e.g. a repo description) so the
            # detail page is never blank
            content = str(raw.content or "").strip()
            if content and not paragraphs:
                paragraphs = [content]
        item["original_content"] = content
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
