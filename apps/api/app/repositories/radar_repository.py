from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

try:
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard for local stdlib tests
    raise RuntimeError("SQLAlchemy is required for database repositories.") from exc

from app.db.models import (
    ArticleEmbeddingModel,
    ArticleTranslationModel,
    DailyReportEntryModel,
    DailyReportModel,
    EditorialOverrideModel,
    PeriodReportModel,
    EventClusterArticleModel,
    EventClusterModel,
    PipelineRunModel,
    ProcessedArticleModel,
    RawArticleModel,
    RefreshScheduleModel,
    SourceModel,
)
from app.models.domain import DailyReport, EventCluster, ProcessedArticle, RawArticle, Source
from app.services.clustering_service import cosine_similarity
from app.services.taxonomy import category_label, display_category


@dataclass(frozen=True)
class WriteResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    # populated only by upsert_event_clusters: {original_cluster_id: target_event_id}
    # for every incoming cluster that got merged into a different, already-
    # existing event instead of creating its own row. Callers (persistence
    # layer) must remap processed_articles.event_cluster_id and daily report
    # entries through this before writing them, or they'll reference an
    # event_clusters row that was never actually created.
    redirects: dict[str, str] = field(default_factory=dict)


# translation is AI output, not crawl data: these keys never get merged into
# raw_articles.raw_metadata, they go to article_translations instead
TRANSLATION_METADATA_KEYS = frozenset(
    {
        "translated_paragraphs",
        "translated_blocks",
        "translation_source_language",
        "translation_target_language",
        "translation_source_hash",
        "translation_status",
        "translation_error",
    }
)


def _crawl_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in TRANSLATION_METADATA_KEYS}


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
                self._sync_translation_from_metadata(article)
                continue
            # later runs enrich articles in memory (README, full-page body);
            # merge that back instead of freezing the first crawl. Translation
            # output is synced to article_translations below, never merged here.
            merged = dict(existing.raw_metadata or {})
            merged.update({"raw_score": article.raw_score, **_crawl_metadata(article.metadata)})
            existing.raw_metadata = merged
            if len(article.content) > len(existing.content or ""):
                existing.content = article.content
            existing.status = article.status
            existing.skipped_reason = article.skipped_reason
            updated += 1
            self._sync_translation_from_metadata(article)
        return WriteResult(inserted=inserted, updated=updated, skipped=skipped)

    def _sync_translation_from_metadata(self, article: RawArticle) -> None:
        metadata = article.metadata
        has_translation = bool(
            metadata.get("translated_paragraphs")
            or metadata.get("translated_blocks")
            or metadata.get("translation_status")
        )
        if not has_translation:
            return
        self.upsert_article_translation(
            article.id,
            translated_paragraphs=metadata.get("translated_paragraphs") or [],
            translated_blocks=metadata.get("translated_blocks") or [],
            source_language=metadata.get("translation_source_language"),
            target_language=metadata.get("translation_target_language") or "zh",
            source_hash=metadata.get("translation_source_hash") or "",
            status=metadata.get("translation_status") or "completed",
            error=metadata.get("translation_error"),
        )

    def upsert_article_translation(
        self,
        raw_article_id: str,
        *,
        translated_paragraphs: list[str],
        translated_blocks: list[dict[str, Any]],
        source_language: Optional[str],
        target_language: str = "zh",
        source_hash: str,
        status: str = "completed",
        error: Optional[str] = None,
    ) -> None:
        model = self.session.scalar(
            select(ArticleTranslationModel).where(
                ArticleTranslationModel.raw_article_id == raw_article_id
            )
        )
        if model is None:
            model = ArticleTranslationModel(raw_article_id=raw_article_id)
            self.session.add(model)
        model.translated_paragraphs = translated_paragraphs
        model.translated_blocks = translated_blocks
        model.source_language = source_language
        model.target_language = target_language
        model.source_hash = source_hash
        model.status = status
        model.error = error
        self.session.flush()

    def get_article_translation(self, raw_article_id: str) -> Optional[dict[str, Any]]:
        model = self.session.scalar(
            select(ArticleTranslationModel).where(
                ArticleTranslationModel.raw_article_id == raw_article_id
            )
        )
        if model is None:
            return None
        return {
            "translated_paragraphs": list(model.translated_paragraphs or []),
            "translated_blocks": list(model.translated_blocks or []),
            "source_language": model.source_language,
            "target_language": model.target_language,
            "source_hash": model.source_hash,
            "status": model.status,
            "error": model.error,
        }

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
        return self._resolve_daily_report_payload(model)

    def replace_daily_report_entries(self, report_date: date, entries: list[dict[str, Any]]) -> None:
        """Persist the masthead (which events, in what order, with what
        recommendation text) for a report date. Content is never stored here -
        it is always resolved live at read time via get_event_items_by_ids."""
        self.session.execute(
            delete(DailyReportEntryModel).where(DailyReportEntryModel.report_date == report_date)
        )
        for position, entry in enumerate(entries):
            self.session.add(
                DailyReportEntryModel(
                    report_date=report_date,
                    position=position,
                    event_id=str(entry["event_id"]),
                    raw_article_id=str(entry["raw_article_id"]),
                    reason_snapshot=str(entry.get("reason") or ""),
                    score_at_selection=float(entry.get("final_score") or 0.0),
                )
            )
        self.session.flush()

    def get_daily_report_entries(self, report_date: date) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(DailyReportEntryModel)
            .where(DailyReportEntryModel.report_date == report_date)
            .order_by(DailyReportEntryModel.position)
        ).all()
        return [
            {
                "event_id": model.event_id,
                "raw_article_id": model.raw_article_id,
                "reason_snapshot": model.reason_snapshot,
                "score_at_selection": model.score_at_selection,
            }
            for model in models
        ]

    def get_event_items_by_ids(self, event_ids: list[str]) -> list[dict[str, Any]]:
        """Batch-resolve events to their current live content, preserving
        the given order. Hidden or unresolvable ids are silently skipped -
        callers (report masthead resolution) treat a shorter result as
        normal, not an error."""
        items = []
        for event_id in event_ids:
            row = self._resolve_processed_row(event_id)
            if row is None:
                continue
            processed, raw, source = row
            override = self._get_override(processed.raw_article_id)
            if override is not None and override.hidden:
                continue
            translation = self._get_translation_model(processed.raw_article_id)
            items.append(
                _event_item(
                    processed, raw, source, include_content=True, override=override, translation=translation
                )
            )
        return items

    def _get_override(self, raw_article_id: str) -> Optional[EditorialOverrideModel]:
        return self.session.scalar(
            select(EditorialOverrideModel).where(
                EditorialOverrideModel.raw_article_id == raw_article_id
            )
        )

    def _get_translation_model(self, raw_article_id: str) -> Optional[ArticleTranslationModel]:
        return self.session.scalar(
            select(ArticleTranslationModel).where(
                ArticleTranslationModel.raw_article_id == raw_article_id
            )
        )

    def _resolve_daily_report_payload(self, model: DailyReportModel) -> dict[str, Any]:
        payload = _daily_report_payload(model)
        entries = self.get_daily_report_entries(model.report_date)
        if not entries:
            return payload

        reason_by_event = {entry["event_id"]: entry["reason_snapshot"] for entry in entries}
        items = self.get_event_items_by_ids([entry["event_id"] for entry in entries])
        # note: an empty result here is not a signal to fall back - it can
        # legitimately mean every selected article is currently hidden, and
        # showing stale snapshot content instead would defeat the whole
        # point of resolving live (a moderated-away article must disappear)
        for item in items:
            snapshot_reason = reason_by_event.get(item["event_id"])
            if snapshot_reason:
                item["reason"] = snapshot_reason

        sections: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            sections.setdefault(item["category"], []).append(item)

        payload["items"] = items
        payload["sections"] = sections
        payload["article_count"] = len(items)
        return payload

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

    def upsert_article_embedding(
        self,
        raw_article_id: str,
        *,
        embedding_model: str,
        vector: list[float],
        source_hash: str,
    ) -> None:
        model = self.session.scalar(
            select(ArticleEmbeddingModel).where(
                ArticleEmbeddingModel.raw_article_id == raw_article_id
            )
        )
        if model is None:
            model = ArticleEmbeddingModel(raw_article_id=raw_article_id)
            self.session.add(model)
        model.embedding_model = embedding_model
        model.content_vector = vector
        model.source_hash = source_hash
        self.session.flush()

    def get_article_embedding_source_hash(self, raw_article_id: str) -> Optional[str]:
        model = self.session.scalar(
            select(ArticleEmbeddingModel).where(
                ArticleEmbeddingModel.raw_article_id == raw_article_id
            )
        )
        return model.source_hash if model else None

    def _get_embedding_vector(self, raw_article_id: str) -> Optional[list[float]]:
        model = self.session.scalar(
            select(ArticleEmbeddingModel).where(
                ArticleEmbeddingModel.raw_article_id == raw_article_id
            )
        )
        if model is None or model.content_vector is None:
            return None
        return list(model.content_vector)

    def find_similar_recent_event(
        self, vector: list[float], *, since: datetime, threshold: float = 0.85
    ) -> Optional[str]:
        """Cross-day multi-source aggregation: is there an already-published
        event whose main article is close enough to this vector within the
        sliding window? Similarity is computed in Python (not pgvector's
        Postgres-only <=> operator) so this stays testable against the
        SQLite-based test suite; correctness matters far more here than
        pushing the comparison into SQL."""
        candidates = self.session.execute(
            select(
                EventClusterModel.id,
                EventClusterModel.last_seen_at,
                ArticleEmbeddingModel.content_vector,
            ).join(
                ArticleEmbeddingModel,
                ArticleEmbeddingModel.raw_article_id == EventClusterModel.main_article_id,
            )
        ).all()
        best_id: Optional[str] = None
        best_score = threshold
        for event_id, last_seen_at, candidate_vector in candidates:
            if candidate_vector is None or _ensure_utc(last_seen_at) < _ensure_utc(since):
                continue
            score = cosine_similarity(vector, list(candidate_vector))
            if score >= best_score:
                best_score = score
                best_id = event_id
        return best_id

    def _count_distinct_sources(self, event_cluster_id: str) -> int:
        rows = self.session.execute(
            select(RawArticleModel.source_id)
            .join(
                EventClusterArticleModel,
                EventClusterArticleModel.raw_article_id == RawArticleModel.id,
            )
            .where(EventClusterArticleModel.event_cluster_id == event_cluster_id)
            .distinct()
        ).all()
        return len(rows)

    def upsert_event_clusters(
        self,
        clusters: list[EventCluster],
        *,
        cluster_window_hours: int = 72,
        similarity_threshold: float = 0.85,
    ) -> WriteResult:
        inserted = 0
        updated = 0
        redirects: dict[str, str] = {}
        for cluster in clusters:
            model = self.session.get(EventClusterModel, cluster.id)
            target_id = cluster.id

            if model is None:
                main_vector = self._get_embedding_vector(cluster.main_article_id)
                if main_vector is not None:
                    since = cluster.last_seen_at - timedelta(hours=cluster_window_hours)
                    matched_id = self.find_similar_recent_event(
                        main_vector, since=since, threshold=similarity_threshold
                    )
                    if matched_id is not None:
                        target_id = matched_id
                        model = self.session.get(EventClusterModel, target_id)
                        redirects[cluster.id] = target_id

            if model is None:
                model = EventClusterModel(id=target_id)
                self.session.add(model)
                inserted += 1
                _apply_event_cluster(model, cluster)
            else:
                updated += 1
                # a lower-scoring later bucket must not steal the main-article
                # slot or overwrite the title/summary of the existing event
                if cluster.final_score > model.final_score:
                    _apply_event_cluster(model, cluster)
                else:
                    model.last_seen_at = max(
                        _ensure_utc(model.last_seen_at), _ensure_utc(cluster.last_seen_at)
                    )

            existing_memberships = self.session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == target_id
                )
            ).all()
            existing_article_ids = {membership.raw_article_id for membership in existing_memberships}
            next_priority = len(existing_memberships)
            # never delete-and-recreate memberships here: that would reset
            # joined_at for every pre-existing member on every later merge
            for article_id in cluster.article_ids:
                if article_id in existing_article_ids:
                    continue
                self.session.add(
                    EventClusterArticleModel(
                        event_cluster_id=target_id,
                        raw_article_id=article_id,
                        is_main=False,
                        source_priority=next_priority,
                    )
                )
                next_priority += 1

            all_memberships = self.session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == target_id
                )
            ).all()
            for membership in all_memberships:
                membership.is_main = membership.raw_article_id == model.main_article_id

            model.source_count = self._count_distinct_sources(target_id)
        self.session.flush()
        return WriteResult(inserted=inserted, updated=updated, redirects=redirects)

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

    def _get_or_create_schedule_row(self) -> RefreshScheduleModel:
        model = self.session.scalar(select(RefreshScheduleModel).order_by(RefreshScheduleModel.id).limit(1))
        if model is None:
            model = RefreshScheduleModel()
            self.session.add(model)
            self.session.flush()
        return model

    def get_schedule_config(self) -> dict[str, Any]:
        model = self._get_or_create_schedule_row()
        return _schedule_config_payload(model)

    def update_schedule_config(self, *, enabled: bool, interval_minutes: int) -> dict[str, Any]:
        model = self._get_or_create_schedule_row()
        model.enabled = enabled
        model.interval_minutes = interval_minutes
        self.session.flush()
        return _schedule_config_payload(model)

    def record_schedule_triggered(self, triggered_at: datetime) -> None:
        model = self._get_or_create_schedule_row()
        model.last_triggered_at = triggered_at
        self.session.flush()

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
        "original_markdown",
        "readme_name",
        "readme_language",
        "readme_selection",
        # 跨轮跳过已成功的 README 抓取（省 GitHub API 限额），
        # zh_probe=failed 的自愈重试标记也要传到下一轮
        "readme_status",
        "readme_zh_probe",
    )

    def get_cached_results_by_url_hash(self, url_hashes: list[str]) -> dict[str, dict[str, Any]]:
        if not url_hashes:
            return {}
        rows = self.session.execute(
            select(RawArticleModel, ProcessedArticleModel, ArticleTranslationModel)
            .join(
                ProcessedArticleModel,
                ProcessedArticleModel.raw_article_id == RawArticleModel.id,
                isouter=True,
            )
            .outerjoin(
                ArticleTranslationModel,
                ArticleTranslationModel.raw_article_id == RawArticleModel.id,
            )
            .where(RawArticleModel.url_hash.in_(url_hashes))
        ).all()
        cached: dict[str, dict[str, Any]] = {}
        for raw, processed, translation in rows:
            raw_metadata = dict(raw.raw_metadata or {})
            metadata = {
                key: raw_metadata[key]
                for key in self.CACHED_METADATA_KEYS
                if raw_metadata.get(key)
            }
            if translation is not None and translation.translated_paragraphs:
                metadata["translated_paragraphs"] = translation.translated_paragraphs
                metadata["translated_blocks"] = translation.translated_blocks
                metadata["translation_source_language"] = translation.source_language
                metadata["translation_target_language"] = translation.target_language
                metadata["translation_source_hash"] = translation.source_hash
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
            select(ProcessedArticleModel, RawArticleModel, SourceModel, EditorialOverrideModel)
            .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
            .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
            .outerjoin(
                EditorialOverrideModel,
                EditorialOverrideModel.raw_article_id == ProcessedArticleModel.raw_article_id,
            )
            .outerjoin(
                EventClusterModel,
                EventClusterModel.id == ProcessedArticleModel.event_cluster_id,
            )
            .where(RawArticleModel.published_at >= window_start)
            .where(RawArticleModel.published_at <= window_end)
            # an event with multiple source members must appear once, not
            # once per member article - only its designated main article
            # (or a standalone article with no cluster at all) passes through
            .where(
                (EventClusterModel.id.is_(None))
                | (EventClusterModel.main_article_id == RawArticleModel.id)
            )
            .order_by(RawArticleModel.published_at.desc())
        )
        if not include_hidden:
            query = query.where(
                (EditorialOverrideModel.hidden.is_(None)) | (EditorialOverrideModel.hidden.is_(False))
            )
        rows = self.session.execute(query).all()
        return [
            _event_item(processed, raw, source, include_content=False, override=override)
            for processed, raw, source, override in rows
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
        """Editorial decisions live in editorial_overrides, never on
        processed_articles: that row is AI-generated territory and a later
        pipeline run re-scoring the same re-crawled article overwrites it
        unconditionally, which would otherwise silently undo moderation."""
        row = self._resolve_processed_row(event_id)
        if row is None:
            return False
        processed, _raw, _source = row
        override = self._get_override(processed.raw_article_id)
        if override is None:
            override = EditorialOverrideModel(raw_article_id=processed.raw_article_id)
            self.session.add(override)
        for key, value in fields.items():
            if key not in self.EVENT_MODERATION_FIELDS:
                continue
            if key == "hidden":
                override.hidden = bool(value)
            elif key == "tags":
                override.tags = [str(tag) for tag in (value or [])][:5]
            else:
                setattr(override, key, str(value))
        self.session.flush()
        return True

    def get_event_item(self, event_id: str) -> Optional[dict[str, Any]]:
        row = self._resolve_processed_row(event_id)
        if row is None:
            return None
        processed, raw, source = row
        override = self._get_override(processed.raw_article_id)
        if override is not None and override.hidden:
            return None
        translation = self._get_translation_model(processed.raw_article_id)
        return _event_item(
            processed, raw, source, include_content=True, override=override, translation=translation
        )

    def get_daily_report_payloads_between(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        models = self.session.scalars(
            select(DailyReportModel)
            .where(DailyReportModel.report_date >= start_date)
            .where(DailyReportModel.report_date <= end_date)
            .order_by(DailyReportModel.report_date.asc())
        )
        return [self._resolve_daily_report_payload(model) for model in models]

    def get_latest_daily_report_payload(self) -> Optional[dict[str, Any]]:
        model = self.session.scalar(
            select(DailyReportModel).order_by(DailyReportModel.report_date.desc()).limit(1)
        )
        if model is None:
            return None
        return self._resolve_daily_report_payload(model)

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


def _as_utc_isoformat(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        # sqlite (unit tests) drops tzinfo on round-trip; Postgres TIMESTAMPTZ
        # always returns aware datetimes, so naive here always means UTC
        return value.replace(tzinfo=timezone.utc)
    return value


def _schedule_config_payload(model: RefreshScheduleModel) -> dict[str, Any]:
    return {
        "enabled": model.enabled,
        "interval_minutes": model.interval_minutes,
        "last_triggered_at": _as_utc_isoformat(model.last_triggered_at),
        "updated_at": _as_utc_isoformat(model.updated_at),
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
        raw_metadata={"raw_score": article.raw_score, **_crawl_metadata(article.metadata)},
        status=article.status,
        skipped_reason=article.skipped_reason,
    )


def _event_item(
    processed: ProcessedArticleModel,
    raw: RawArticleModel,
    source: SourceModel,
    *,
    include_content: bool,
    override: Optional[EditorialOverrideModel] = None,
    translation: Optional[ArticleTranslationModel] = None,
) -> dict[str, Any]:
    metadata = dict(raw.raw_metadata or {})
    published_at = raw.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    title_zh = (override.title_zh if override and override.title_zh else None) or processed.title_zh
    category = (override.category if override and override.category else None) or processed.category
    tags = list(override.tags) if override and override.tags else list(processed.tags or [])
    hidden = bool(override.hidden) if override else False
    item: dict[str, Any] = {
        "event_id": processed.event_cluster_id or f"a{raw.id[:12]}",
        "title": title_zh or raw.title,
        "category": display_category(category),
        "category_label": category_label(category),
        "scoring_category": category,
        "tags": tags,
        "final_score": processed.final_score,
        "selected": processed.status == "processed",
        "hidden": hidden,
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
        if translation is not None:
            if translation.translated_paragraphs:
                item["translated_paragraphs"] = translation.translated_paragraphs
            if translation.translated_blocks:
                item["translated_blocks"] = translation.translated_blocks
            if translation.status:
                item["translation_status"] = translation.status
            if translation.error:
                item["translation_error"] = translation.error
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
