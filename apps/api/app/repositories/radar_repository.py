from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session, aliased
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
    EventClusterRedirectModel,
    EventEditorialOverrideModel,
    PipelineRunModel,
    ProcessedArticleModel,
    RawArticleModel,
    RefreshScheduleModel,
    SourceModel,
)
from app.models.domain import DailyReport, EventCluster, ProcessedArticle, RawArticle, Source
from app.services.clustering_service import (
    ROLE_PRIORITY,
    TIER_PRIORITY,
    cosine_similarity,
    reference_keys_from_metadata,
)
from app.services.daily_report_service import (
    _clean_original_blocks,
    _plain_paragraphs_from_blocks,
    _strip_legacy_telegram_signature,
)
from app.services.taxonomy import category_label, display_category


@dataclass(frozen=True)
class WriteResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    # populated by upsert_raw_articles / insert_missing_raw_articles: ids of
    # articles written for the first time this call - the "入库/非AI" ledger
    # metrics and the basis for counting which selected articles are new
    inserted_ids: list[str] = field(default_factory=list)
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

    def upsert_raw_articles(
        self, articles: list[RawArticle], *, pipeline_run_id: Optional[int] = None
    ) -> WriteResult:
        inserted = 0
        updated = 0
        skipped = 0
        inserted_ids: list[str] = []
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
                inserted_ids.append(article.id)
                self._sync_translation_from_metadata(article, pipeline_run_id=pipeline_run_id)
                continue
            # later runs enrich articles in memory (README, full-page body);
            # merge that back instead of freezing the first crawl. Translation
            # output is synced to article_translations below, never merged here.
            previous_metadata = dict(existing.raw_metadata or {})
            previous_extraction_version = int(previous_metadata.get("content_extraction_version") or 0)
            incoming_extraction_version = int(article.metadata.get("content_extraction_version") or 0)
            extraction_upgraded = incoming_extraction_version > previous_extraction_version
            merged = dict(existing.raw_metadata or {})
            merged.update({"raw_score": article.raw_score, **_crawl_metadata(article.metadata)})
            # content-structure fields regress silently if a later crawl only
            # got a thin summary (empty blocks) - keep the last known-good
            # value instead of letting dict.update() blank it out
            for key in self._CACHED_CONTENT_STRUCTURE_KEYS:
                if (
                    not extraction_upgraded
                    and not merged.get(key)
                    and previous_metadata.get(key)
                ):
                    merged[key] = previous_metadata[key]
            existing.raw_metadata = merged
            if extraction_upgraded or len(article.content) > len(existing.content or ""):
                existing.content = article.content
            # the crawl re-detects the body's language (a zh-labeled
            # aggregator often points at English originals); persist it or
            # the translation toggle keeps using the stale label
            existing.language = article.language
            # RSS timestamps can become correct after a parser fix or a feed
            # correction. Update only when this crawl actually parsed a
            # pubDate; an undated feed still uses normalize_article's fallback
            # clock internally and must not make the stored time drift.
            if (
                "rss_pubdate_missing" in article.metadata
                and not article.metadata.get("rss_pubdate_missing")
            ):
                existing.published_at = article.published_at
            existing.status = article.status
            existing.skipped_reason = article.skipped_reason
            updated += 1
            self._sync_translation_from_metadata(article, pipeline_run_id=pipeline_run_id)
        return WriteResult(
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            inserted_ids=inserted_ids,
        )

    def insert_missing_raw_articles(
        self, articles: list[RawArticle], *, pipeline_run_id: Optional[int] = None
    ) -> WriteResult:
        """抓取后立即落库(2026-07-12 四步流程第 1 步):只插入库里没有的
        文章(默认未入选状态),已存在的完全跳过——不合并不更新,让抓取
        结果先于 AI 处理可见。增强合并仍由整轮结束后的 upsert 完成。"""
        inserted = 0
        skipped = 0
        inserted_ids: list[str] = []
        seen_url_hashes: set[str] = set()
        for article in articles:
            if article.url_hash in seen_url_hashes:
                skipped += 1
                continue
            seen_url_hashes.add(article.url_hash)
            exists = self.session.scalar(
                select(RawArticleModel.id).where(
                    RawArticleModel.url_hash == article.url_hash
                )
            )
            if exists is not None:
                skipped += 1
                continue
            self.session.add(_raw_article_to_model(article))
            inserted += 1
            inserted_ids.append(article.id)
        self.session.flush()
        return WriteResult(inserted=inserted, skipped=skipped, inserted_ids=inserted_ids)

    def _sync_translation_from_metadata(
        self, article: RawArticle, *, pipeline_run_id: Optional[int] = None
    ) -> None:
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
            pipeline_run_id=pipeline_run_id,
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
        pipeline_run_id: Optional[int] = None,
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
        if pipeline_run_id is not None:
            model.pipeline_run_id = pipeline_run_id
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

    def upsert_daily_report(
        self, report: DailyReport, *, pipeline_run_id: Optional[int] = None
    ) -> WriteResult:
        model = self.session.scalar(
            select(DailyReportModel).where(DailyReportModel.report_date == report.report_date)
        )
        if model is None:
            model = _daily_report_to_model(report)
            self.session.add(model)
            if pipeline_run_id is not None:
                model.pipeline_run_id = pipeline_run_id
            return WriteResult(inserted=1)

        _apply_daily_report(model, report)
        if pipeline_run_id is not None:
            model.pipeline_run_id = pipeline_run_id
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
            processed, raw, source, cluster = row
            override = self._get_override(processed.raw_article_id)
            event_override = self._get_event_override(cluster.id) if cluster else None
            if (override is not None and override.hidden) or (
                event_override is not None and event_override.hidden
            ):
                continue
            translation = self._get_translation_model(processed.raw_article_id)
            items.append(
                _event_item(
                    processed,
                    raw,
                    source,
                    include_content=True,
                    override=override,
                    event_override=event_override,
                    translation=translation,
                    source_count=cluster.source_count if cluster else 1,
                    event_id=cluster.id if cluster else None,
                    last_seen_at=cluster.last_seen_at if cluster else None,
                )
            )
        return items

    def _get_override(self, raw_article_id: str) -> Optional[EditorialOverrideModel]:
        return self.session.scalar(
            select(EditorialOverrideModel).where(
                EditorialOverrideModel.raw_article_id == raw_article_id
            )
        )

    def _get_event_override(
        self, event_cluster_id: str
    ) -> Optional[EventEditorialOverrideModel]:
        return self.session.scalar(
            select(EventEditorialOverrideModel).where(
                EventEditorialOverrideModel.event_cluster_id == event_cluster_id
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

    def upsert_processed_articles(
        self,
        processed_articles: list[ProcessedArticle],
        *,
        pipeline_run_id: Optional[int] = None,
    ) -> WriteResult:
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
            if pipeline_run_id is not None:
                model.pipeline_run_id = pipeline_run_id
        return WriteResult(inserted=inserted, updated=updated)

    def upsert_article_embedding(
        self,
        raw_article_id: str,
        *,
        embedding_model: str,
        vector: list[float],
        source_hash: str,
        pipeline_run_id: Optional[int] = None,
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
        if pipeline_run_id is not None:
            model.pipeline_run_id = pipeline_run_id
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
    ) -> Optional[tuple[str, float]]:
        """Cross-day multi-source aggregation: is there an already-published
        event whose main article is close enough to this vector within the
        sliding window? Returns (event_id, similarity) so the caller can
        persist the score that actually justified the merge. Similarity is
        computed in Python (not pgvector's Postgres-only <=> operator) so
        this stays testable against the SQLite-based test suite; correctness
        matters far more here than pushing the comparison into SQL."""
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
        if best_id is None:
            return None
        return best_id, best_score

    def _similarity_between_articles(
        self, left_article_id: str, right_article_id: str
    ) -> Optional[float]:
        left = self._get_embedding_vector(left_article_id)
        right = self._get_embedding_vector(right_article_id)
        if left is None or right is None:
            return None
        return cosine_similarity(left, right)

    def _reference_keys_for_articles(self, article_ids: list[str]) -> set[str]:
        if not article_ids:
            return set()
        metadata_rows = self.session.execute(
            select(RawArticleModel.raw_metadata).where(RawArticleModel.id.in_(article_ids))
        ).scalars()
        keys: set[str] = set()
        for metadata in metadata_rows:
            keys.update(reference_keys_from_metadata(metadata))
        return keys

    def find_recent_event_by_reference_keys(
        self, reference_keys: set[str], *, since: datetime
    ) -> Optional[str]:
        """Find an event citing the exact same article/status URL.

        This is deliberately separate from vector similarity: an exact
        non-homepage source link is deterministic same-event evidence and
        safely recovers paraphrases that sit below the conservative vector
        threshold.
        """
        if not reference_keys:
            return None
        rows = self.session.execute(
            select(
                EventClusterModel.id,
                EventClusterModel.last_seen_at,
                RawArticleModel.raw_metadata,
            )
            .join(
                EventClusterArticleModel,
                EventClusterArticleModel.event_cluster_id == EventClusterModel.id,
            )
            .join(
                RawArticleModel,
                RawArticleModel.id == EventClusterArticleModel.raw_article_id,
            )
        ).all()
        candidates: set[str] = set()
        for event_id, last_seen_at, metadata in rows:
            if _ensure_utc(last_seen_at) < _ensure_utc(since):
                continue
            if reference_keys.intersection(reference_keys_from_metadata(metadata)):
                candidates.add(event_id)
        if not candidates:
            return None
        return max(candidates, key=self._event_merge_rank)

    def _event_merge_rank(
        self, event_id: str
    ) -> tuple[int, int, int, float, int, datetime, str]:
        model = self.session.get(EventClusterModel, event_id)
        if model is None:
            return (0, 0, 0, 0.0, 0, datetime.min.replace(tzinfo=timezone.utc), event_id)
        source = self.session.execute(
            select(SourceModel)
            .join(RawArticleModel, RawArticleModel.source_id == SourceModel.id)
            .where(RawArticleModel.id == model.main_article_id)
        ).scalar_one_or_none()
        return (
            1 if source and source.can_be_main_source else 0,
            ROLE_PRIORITY.get(source.source_role, 0) if source else 0,
            TIER_PRIORITY.get(source.tier, 0) if source else 0,
            float(model.final_score or 0.0),
            int(model.source_count or 1),
            _ensure_utc(model.last_seen_at),
            event_id,
        )

    @staticmethod
    def _follow_redirects(event_id: str, redirects: dict[str, str]) -> str:
        seen: set[str] = set()
        while event_id in redirects and event_id not in seen:
            seen.add(event_id)
            event_id = redirects[event_id]
        return event_id

    def _merge_event_cluster(
        self,
        source_id: str,
        target_id: str,
        redirects: dict[str, str],
    ) -> str:
        source_id = self._follow_redirects(source_id, redirects)
        target_id = self._follow_redirects(target_id, redirects)
        if source_id == target_id:
            return target_id
        source = self.session.get(EventClusterModel, source_id)
        target = self.session.get(EventClusterModel, target_id)
        if source is None or target is None:
            return target_id

        target.first_seen_at = min(
            _ensure_utc(target.first_seen_at), _ensure_utc(source.first_seen_at)
        )
        target.last_seen_at = max(
            _ensure_utc(target.last_seen_at), _ensure_utc(source.last_seen_at)
        )
        target.final_score = max(float(target.final_score or 0), float(source.final_score or 0))

        target_memberships = {
            membership.raw_article_id: membership
            for membership in self.session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == target_id
                )
            ).all()
        }
        source_memberships = self.session.scalars(
            select(EventClusterArticleModel).where(
                EventClusterArticleModel.event_cluster_id == source_id
            )
        ).all()
        next_priority = len(target_memberships)
        for membership in source_memberships:
            if membership.raw_article_id in target_memberships:
                self.session.delete(membership)
                continue
            membership.event_cluster_id = target_id
            membership.is_main = False
            membership.source_priority = next_priority
            next_priority += 1

        for processed in self.session.scalars(
            select(ProcessedArticleModel).where(
                ProcessedArticleModel.event_cluster_id == source_id
            )
        ).all():
            processed.event_cluster_id = target_id

        source_override = self._get_event_override(source_id)
        target_override = self._get_event_override(target_id)
        if source_override is not None:
            if target_override is None:
                source_override.event_cluster_id = target_id
            else:
                self.session.delete(source_override)

        # Historical report mastheads should keep resolving to the original
        # article rather than rendering the canonical event's main article
        # multiple times after consolidation. Article pseudo-ids are stable
        # and still inherit the canonical cluster's coverage facts.
        article_alias = f"a{source.main_article_id[:12]}"
        for entry in self.session.scalars(
            select(DailyReportEntryModel).where(DailyReportEntryModel.event_id == source_id)
        ).all():
            entry.event_id = article_alias
        for period in self.session.scalars(select(PeriodReportModel)).all():
            entries = list(period.entries or [])
            changed = False
            for entry in entries:
                if isinstance(entry, dict) and entry.get("event_id") == source_id:
                    entry["event_id"] = article_alias
                    changed = True
            if changed:
                period.entries = entries

        for redirect in self.session.scalars(
            select(EventClusterRedirectModel).where(
                EventClusterRedirectModel.target_event_id == source_id
            )
        ).all():
            redirect.target_event_id = target_id
        redirect = self.session.get(EventClusterRedirectModel, source_id)
        if redirect is None:
            self.session.add(
                EventClusterRedirectModel(
                    source_event_id=source_id,
                    target_event_id=target_id,
                )
            )
        else:
            redirect.target_event_id = target_id

        self.session.flush()
        self.session.delete(source)
        self.session.flush()
        redirects[source_id] = target_id
        for original_id, redirected_id in list(redirects.items()):
            redirects[original_id] = self._follow_redirects(redirected_id, redirects)
        target.source_count = self._count_distinct_sources(target_id)
        self._refresh_event_similarity_scores(target_id)
        return target_id

    def reconcile_recent_events_by_reference(self, *, since: datetime) -> dict[str, str]:
        """Consolidate recent split clusters that cite one exact source URL."""
        rows = self.session.execute(
            select(
                EventClusterModel.id,
                EventClusterModel.last_seen_at,
                RawArticleModel.raw_metadata,
            )
            .join(
                EventClusterArticleModel,
                EventClusterArticleModel.event_cluster_id == EventClusterModel.id,
            )
            .join(
                RawArticleModel,
                RawArticleModel.id == EventClusterArticleModel.raw_article_id,
            )
            .where(EventClusterModel.last_seen_at >= _ensure_utc(since))
        ).all()
        event_ids_by_key: dict[str, set[str]] = {}
        for event_id, _last_seen_at, metadata in rows:
            for key in reference_keys_from_metadata(metadata):
                event_ids_by_key.setdefault(key, set()).add(event_id)

        redirects: dict[str, str] = {}
        for event_ids in event_ids_by_key.values():
            live_ids = {
                self._follow_redirects(event_id, redirects)
                for event_id in event_ids
                if self.session.get(EventClusterModel, self._follow_redirects(event_id, redirects))
                is not None
            }
            if len(live_ids) < 2:
                continue
            target_id = max(live_ids, key=self._event_merge_rank)
            for source_id in sorted(live_ids - {target_id}):
                self._merge_event_cluster(source_id, target_id, redirects)
        return redirects

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

    def _refresh_event_similarity_scores(self, event_cluster_id: str) -> None:
        cluster = self.session.get(EventClusterModel, event_cluster_id)
        if cluster is None:
            return
        memberships = self.session.scalars(
            select(EventClusterArticleModel).where(
                EventClusterArticleModel.event_cluster_id == event_cluster_id
            )
        ).all()
        for membership in memberships:
            if membership.raw_article_id == cluster.main_article_id:
                membership.similarity_score = 1.0
                continue
            membership.similarity_score = self._similarity_between_articles(
                membership.raw_article_id, cluster.main_article_id
            )

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
                since = cluster.last_seen_at - timedelta(hours=cluster_window_hours)
                reference_keys = self._reference_keys_for_articles(cluster.article_ids)
                reference_match = self.find_recent_event_by_reference_keys(
                    reference_keys, since=since
                )
                if reference_match is not None:
                    target_id = reference_match
                    model = self.session.get(EventClusterModel, target_id)
                    redirects[cluster.id] = target_id

            if model is None:
                main_vector = self._get_embedding_vector(cluster.main_article_id)
                if main_vector is not None:
                    match = self.find_similar_recent_event(
                        main_vector, since=since, threshold=similarity_threshold
                    )
                    if match is not None:
                        target_id, _matched_score = match
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

            # A previous run may already have put one of these articles in a
            # separate event. Consolidate that entire old event before adding
            # the member so raw_article_id remains globally one-event-only.
            prior_memberships = self.session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id.in_(cluster.article_ids)
                )
            ).all()
            for membership in prior_memberships:
                if membership.event_cluster_id == target_id:
                    continue
                target_id = self._merge_event_cluster(
                    membership.event_cluster_id, target_id, redirects
                )
                model = self.session.get(EventClusterModel, target_id)

            existing_memberships = self.session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == target_id
                )
            ).all()
            existing_article_ids = {membership.raw_article_id for membership in existing_memberships}
            next_priority = len(existing_memberships)
            redirected = target_id != cluster.id
            # never delete-and-recreate memberships here: that would reset
            # joined_at for every pre-existing member on every later merge
            for article_id in cluster.article_ids:
                if article_id in existing_article_ids:
                    continue
                # None (not 0.0) when evidence is unavailable - the column
                # distinguishes "unknown" from a real low score
                similarity = cluster.article_similarities.get(article_id)
                if redirected:
                    # the evidence must describe the event actually joined:
                    # against the incoming bucket the value is trivially ~1.0,
                    # but the merge was justified by closeness to the target
                    # event's main article
                    recomputed = self._similarity_between_articles(
                        article_id, model.main_article_id
                    )
                    if recomputed is not None:
                        similarity = recomputed
                self.session.add(
                    EventClusterArticleModel(
                        event_cluster_id=target_id,
                        raw_article_id=article_id,
                        similarity_score=similarity,
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
            # demote first and flush before promoting: the partial unique
            # index (one main per event) is checked per statement, so a
            # promote-before-demote update order would transiently violate it
            for membership in all_memberships:
                if membership.raw_article_id != model.main_article_id and membership.is_main:
                    membership.is_main = False
            self.session.flush()
            for membership in all_memberships:
                if membership.raw_article_id == model.main_article_id and not membership.is_main:
                    membership.is_main = True

            model.source_count = self._count_distinct_sources(target_id)
        if clusters:
            since = min(cluster.last_seen_at for cluster in clusters) - timedelta(
                hours=cluster_window_hours
            )
            reference_redirects = self.reconcile_recent_events_by_reference(since=since)
            redirects.update(reference_redirects)
            for original_id, target_id in list(redirects.items()):
                redirects[original_id] = self._follow_redirects(target_id, redirects)
        self.session.flush()
        return WriteResult(inserted=inserted, updated=updated, redirects=redirects)

    def start_pipeline_run(self, *, started_at: Any = None, phase: Optional[str] = None) -> int:
        """Insert a 'running' row the moment work begins, so the DB can
        answer "is anything running right now / did it hang" instead of
        only learning about runs after they finish. Returns the run id for
        lineage stamping and the final finish_pipeline_run update."""
        model = PipelineRunModel(status="running", phase=phase)
        if started_at is not None:
            model.started_at = started_at
        self.session.add(model)
        self.session.flush()
        return model.id

    def get_active_pipeline_run(self) -> Optional[dict[str, Any]]:
        """The freshest 'running' row, if any - the cross-process source of
        truth for "is a refresh in flight right now"."""
        model = self.session.scalar(
            select(PipelineRunModel)
            .where(PipelineRunModel.status == "running")
            .order_by(PipelineRunModel.id.desc())
            .limit(1)
        )
        if model is None:
            return None
        return {
            "id": model.id,
            "started_at": model.started_at.isoformat() if model.started_at else None,
            "phase": model.phase,
        }

    def sweep_stale_pipeline_runs(self, *, max_age_minutes: int = 45) -> int:
        """Close out 'running' rows whose process evidently died (older than
        max_age_minutes), so the concurrency guard can never dead-lock on an
        orphan. Honest bookkeeping: marked failed with an explicit reason.
        45min: 流程重排后正常运行是分钟级,这里纯作孤儿兜底——阈值必须
        大于任何合法运行时长,否则活着的运行会被误杀并叠加双跑。"""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        stale_models = self.session.scalars(
            select(PipelineRunModel).where(PipelineRunModel.status == "running")
        ).all()
        swept = 0
        for model in stale_models:
            if _ensure_utc(model.started_at) >= cutoff:
                continue
            model.status = "failed"
            model.error = f"stale running row swept after {max_age_minutes}min (process died mid-run?)"
            model.finished_at = datetime.now(timezone.utc)
            swept += 1
        if swept:
            self.session.flush()
        return swept

    def update_pipeline_run_progress(
        self,
        run_id: int,
        *,
        phase: Optional[str] = None,
        raw_count: Optional[int] = None,
        source_report: Optional[dict[str, Any]] = None,
    ) -> None:
        model = self.session.get(PipelineRunModel, run_id)
        if model is None:
            return
        if phase is not None:
            model.phase = phase
        if raw_count is not None:
            model.raw_count = raw_count
        if source_report is not None:
            model.source_report = source_report
        self.session.flush()

    def finish_pipeline_run(
        self,
        run_id: int,
        *,
        status: str,
        raw_count: int = 0,
        processed_count: int = 0,
        cluster_count: int = 0,
        skipped_reasons: Optional[dict[str, int]] = None,
        source_report: Optional[dict[str, Any]] = None,
        error: str | None = None,
        finished_at: Any = None,
        new_raw_count: Optional[int] = None,
        new_selected_count: Optional[int] = None,
        non_ai_dropped_count: Optional[int] = None,
    ) -> WriteResult:
        model = self.session.get(PipelineRunModel, run_id)
        if model is None:
            return WriteResult()
        model.status = status
        model.raw_count = raw_count
        model.processed_count = processed_count
        model.cluster_count = cluster_count
        model.new_raw_count = new_raw_count
        model.new_selected_count = new_selected_count
        model.non_ai_dropped_count = non_ai_dropped_count
        model.skipped_reasons = dict(skipped_reasons or {})
        if source_report is not None:
            # supersedes the coarse crawl-stage report _report_progress wrote
            # earlier, now that AI processing has produced real per-source
            # saved counts
            model.source_report = source_report
        model.error = error
        model.finished_at = finished_at if finished_at is not None else datetime.now(timezone.utc)
        self.session.flush()
        return WriteResult(updated=1)

    def record_pipeline_run(
        self,
        *,
        status: str,
        raw_count: int,
        processed_count: int,
        cluster_count: int,
        skipped_reasons: dict[str, int],
        source_report: Optional[dict[str, Any]] = None,
        started_at: Any = None,
        finished_at: Any = None,
        error: str | None = None,
        new_raw_count: Optional[int] = None,
        new_selected_count: Optional[int] = None,
        non_ai_dropped_count: Optional[int] = None,
    ) -> WriteResult:
        model = PipelineRunModel(
            status=status,
            raw_count=raw_count,
            processed_count=processed_count,
            cluster_count=cluster_count,
            new_raw_count=new_raw_count,
            new_selected_count=new_selected_count,
            non_ai_dropped_count=non_ai_dropped_count,
            skipped_reasons=dict(skipped_reasons),
            error=error,
        )
        if source_report is not None:
            model.source_report = source_report
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
        model.entries = list(report.get("entries") or [])
        model.stats = dict(report.get("stats") or {})
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
            # automatic runs only know per-source counts, not which articles
            # were ultimately selected (that's decided later, across all
            # sources together) - store what's honestly available so this
            # still overwrites a stale manual-fetch result with something
            # fresher, without claiming a save/reject verdict it doesn't have
            model.last_crawl_result = {
                "origin": "auto",
                "at": now.isoformat(),
                "status": report.get("status"),
                "error": report.get("error"),
                "fetched_count": report.get("fetched_count"),
                "accepted_count": report.get("article_count"),
                "articles": [],
            }

    def set_last_crawl_result(self, source_id: str, result: dict[str, Any]) -> None:
        """Stores this source's most recent crawl outcome, whichever origin
        (manual single-source fetch or a full automatic sync) ran most
        recently simply wins by virtue of being the latest write."""
        model = self.session.get(SourceModel, source_id)
        if model is None:
            return
        model.last_crawl_result = result

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
                "last_crawl_result": model.last_crawl_result,
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
                "new_raw_count": model.new_raw_count,
                "new_selected_count": model.new_selected_count,
                "non_ai_dropped_count": model.non_ai_dropped_count,
                # 恒等式:抓取 = 重复 + 非AI + 入库。NULL(历史行)保持
                # None,前端显示 --,不能伪装成 0
                "duplicate_count": (
                    model.raw_count - model.new_raw_count - model.non_ai_dropped_count
                    if model.new_raw_count is not None
                    and model.non_ai_dropped_count is not None
                    else None
                ),
                "skipped_reasons": dict(model.skipped_reasons or {}),
                "error": model.error,
                "phase": model.phase,
                "source_report": dict(model.source_report or {}),
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
        # 缓存命中时不会重新抓正文（见 pipeline/runner.py 的 cached 分支），
        # 这四个字段必须带到下一轮，否则会被本轮薄摘要解析出的空结构覆盖
        "original_paragraphs",
        "original_blocks",
        "original_text",
        "original_images",
        "content_extraction_version",
        "content_profile",
        "content_extraction_diagnostics",
    )

    # 缓存命中时只应回填这几个"正文结构"字段——且只在本轮值为空时才用缓存
    # 值，不能像 README 字段那样用 setdefault（RSS 抓取阶段已经无条件写入
    # 这些 key，哪怕值是空列表，setdefault 也不会覆盖）
    _CACHED_CONTENT_STRUCTURE_KEYS = (
        "original_paragraphs",
        "original_blocks",
        "original_text",
        "original_images",
    )

    def get_cached_results_by_url_hash(self, url_hashes: list[str]) -> dict[str, dict[str, Any]]:
        if not url_hashes:
            return {}
        rows = self.session.execute(
            select(
                RawArticleModel,
                ProcessedArticleModel,
                ArticleTranslationModel,
                ArticleEmbeddingModel,
            )
            .join(
                ProcessedArticleModel,
                ProcessedArticleModel.raw_article_id == RawArticleModel.id,
                isouter=True,
            )
            .outerjoin(
                ArticleTranslationModel,
                ArticleTranslationModel.raw_article_id == RawArticleModel.id,
            )
            .outerjoin(
                ArticleEmbeddingModel,
                ArticleEmbeddingModel.raw_article_id == RawArticleModel.id,
            )
            .where(RawArticleModel.url_hash.in_(url_hashes))
        ).all()
        cached: dict[str, dict[str, Any]] = {}
        for raw, processed, translation, embedding in rows:
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
                "raw_article_id": raw.id,
                "language": raw.language,
                "scoring": scoring,
                "skipped_reason": raw.skipped_reason if scoring is None else None,
                "metadata": metadata,
                # 缓存文章不再拉正文(2026-07-12 流程重排):把库里的全文
                # 和既有向量带回 pipeline,防止 feed 摘要重算出劣质向量
                # 覆盖全文向量。必须转纯 float:pgvector 给的是 numpy
                # float32,顺着相似度计算混进日报 JSON 会崩掉序列化
                "content": raw.content,
                "embedding": (
                    [float(value) for value in embedding.content_vector]
                    if embedding is not None and embedding.content_vector is not None
                    else None
                ),
                "embedding_source_hash": embedding.source_hash if embedding is not None else None,
            }
        return cached

    def get_existing_outcome_by_url_hash(self, url_hash: str) -> Optional[dict[str, Any]]:
        """Already-known verdict for one URL, for reporting a manual fetch's
        duplicates without re-spending AI calls on unchanged content."""
        row = self.session.execute(
            select(RawArticleModel, ProcessedArticleModel)
            .outerjoin(
                ProcessedArticleModel,
                ProcessedArticleModel.raw_article_id == RawArticleModel.id,
            )
            .where(RawArticleModel.url_hash == url_hash)
        ).first()
        if row is None:
            return None
        raw, processed = row
        result_url = str((raw.raw_metadata or {}).get("aihot_permalink") or raw.source_url)
        if processed is None:
            return {
                "title": raw.title,
                "url": result_url,
                "selected": None,
                "final_score": None,
                "category": None,
                "reason": raw.skipped_reason,
            }
        selected = processed.status == "processed"
        return {
            "title": processed.title_zh or raw.title,
            "url": result_url,
            "selected": selected,
            "final_score": processed.final_score,
            "category": processed.category,
            "reason": processed.selection_reason if selected else processed.rejection_reason,
        }

    _EVENT_CONTENT_METADATA_KEYS = (
        "original_paragraphs",
        "original_blocks",
        "original_markdown",
        "readme_name",
        "readme_language",
        "readme_selection",
        # "aihot_item_page_link_only" tells the frontend to skip rendering a
        # 原文 block entirely (known unscrapable domain, e.g. WeChat) rather
        # than fall back to a synthesized summary-as-原文 paragraph
        "content_origin",
    )

    def get_all_event_items_between(
        self,
        start_date: date,
        end_date: date,
        *,
        include_hidden: bool = False,
        selected_only: bool = False,
    ) -> list[dict[str, Any]]:
        # 产品决策(2026-07-13):不做事件级去重——同一事件的每篇处理过的
        # 文章都独立展示，各自带自己的标题/评分/地址。事件聚簇只服务
        # 热点榜排序(build_hotspots_payload 按 is_main 过滤)和详情页的
        # 跨源列表，不再用于折叠 /all 或后台内容管理的列表。
        shanghai = ZoneInfo("Asia/Shanghai")
        window_start = datetime.combine(start_date, time.min, tzinfo=shanghai).astimezone(
            timezone.utc
        )
        window_end = datetime.combine(end_date, time.max, tzinfo=shanghai).astimezone(
            timezone.utc
        )
        # event membership comes from event_cluster_articles (the source of
        # truth), NOT from processed_articles.event_cluster_id - that cache
        # column drifts (a later run can overwrite it)
        #
        # 每篇文章独立管理(2026-07-13 产品决策):hide/title/category 的
        # 事件级覆盖只在这一行本身是主条时才生效(main_cluster) - 隐藏
        # 一条不会连带隐藏同事件的其他成员，反之亦然。source_count 和
        # last_seen_at 是客观事实，仍然查真实所属聚类(member_cluster)。
        main_membership = aliased(EventClusterArticleModel)
        main_cluster = aliased(EventClusterModel)
        main_event_override = aliased(EventEditorialOverrideModel)
        member_membership = aliased(EventClusterArticleModel)
        member_cluster = aliased(EventClusterModel)
        query = (
            select(
                ProcessedArticleModel,
                RawArticleModel,
                SourceModel,
                EditorialOverrideModel,
                main_cluster,
                member_cluster,
                main_event_override,
            )
            .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
            .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
            .outerjoin(
                EditorialOverrideModel,
                EditorialOverrideModel.raw_article_id == ProcessedArticleModel.raw_article_id,
            )
            .outerjoin(
                main_membership,
                (main_membership.raw_article_id == ProcessedArticleModel.raw_article_id)
                & main_membership.is_main.is_(True),
            )
            .outerjoin(main_cluster, main_cluster.id == main_membership.event_cluster_id)
            .outerjoin(
                main_event_override,
                main_event_override.event_cluster_id == main_cluster.id,
            )
            .outerjoin(
                member_membership,
                member_membership.raw_article_id == ProcessedArticleModel.raw_article_id,
            )
            .outerjoin(member_cluster, member_cluster.id == member_membership.event_cluster_id)
            .where(RawArticleModel.published_at >= window_start)
            .where(RawArticleModel.published_at <= window_end)
            .order_by(RawArticleModel.published_at.desc())
        )
        if selected_only:
            selected_membership = aliased(EventClusterArticleModel)
            selected_processed = aliased(ProcessedArticleModel)
            has_selected_member = (
                select(selected_membership.id)
                .join(
                    selected_processed,
                    selected_processed.raw_article_id == selected_membership.raw_article_id,
                )
                .where(selected_membership.event_cluster_id == member_cluster.id)
                .where(selected_processed.status == "processed")
                .exists()
            )
            query = query.where(
                (member_cluster.id.isnot(None) & has_selected_member)
                | (member_cluster.id.is_(None) & (ProcessedArticleModel.status == "processed"))
            )
        if not include_hidden:
            query = query.where(
                (EditorialOverrideModel.hidden.is_(None)) | (EditorialOverrideModel.hidden.is_(False))
            ).where(
                (main_event_override.hidden.is_(None))
                | (main_event_override.hidden.is_(False))
            )
        rows = self.session.execute(query).all()
        items = []
        for processed, raw, source, override, cluster, m_cluster, event_override in rows:
            # this row is the designated main of its cluster, or genuinely
            # standalone (no membership at all) - both are "one candidate
            # per event" cases for hotspot ranking; only a non-main member
            # of a real cluster is not
            is_main = cluster is not None or m_cluster is None
            items.append(
                _event_item(
                    processed,
                    raw,
                    source,
                    include_content=False,
                    override=override,
                    event_override=event_override,
                    source_count=m_cluster.source_count if m_cluster else 1,
                    event_id=cluster.id if cluster is not None else f"a{raw.id[:12]}",
                    last_seen_at=m_cluster.last_seen_at if m_cluster else None,
                    is_main=is_main,
                )
            )
        return items

    def _find_cluster_for_raw_article(self, raw_article_id: str) -> Optional[EventClusterModel]:
        """Is this article actually a member of some event cluster, regardless
        of role? Used so a non-main member's own `a…` pseudo-id page (the
        article's address always stays article-level) can still: attach a
        coverage panel, report the event's real source_count/last_seen_at,
        and - critically - respect an event-level hide, which must cascade
        to every member, not just the one designated main."""
        membership = self.session.scalar(
            select(EventClusterArticleModel).where(
                EventClusterArticleModel.raw_article_id == raw_article_id
            )
        )
        if membership is None:
            return None
        return self.session.get(EventClusterModel, membership.event_cluster_id)

    def _canonical_event_id(self, event_id: str) -> str:
        seen: set[str] = set()
        while event_id not in seen:
            seen.add(event_id)
            redirect = self.session.get(EventClusterRedirectModel, event_id)
            if redirect is None:
                break
            event_id = redirect.target_event_id
        return event_id

    def _resolve_processed_row(self, event_id: str):
        """Resolve an event id to (processed, raw, source, cluster). `cluster`
        here is None whenever resolution went through the `a…` prefix path -
        that path matches by raw_article_id regardless of actual cluster
        membership (see get_event_item, which re-checks membership via
        _find_cluster_id_for_raw_article to still attach a coverage panel)."""
        event_id = self._canonical_event_id(event_id)
        cluster = self.session.get(EventClusterModel, event_id)
        if cluster is not None:
            row = self.session.execute(
                select(ProcessedArticleModel, RawArticleModel, SourceModel)
                .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
                .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
                .where(ProcessedArticleModel.raw_article_id == cluster.main_article_id)
            ).first()
            return (*row, cluster) if row is not None else None
        if event_id.startswith("a"):
            row = self.session.execute(
                select(ProcessedArticleModel, RawArticleModel, SourceModel)
                .join(RawArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id)
                .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
                .where(RawArticleModel.id.like(f"{event_id[1:]}%"))
            ).first()
            return (*row, None) if row is not None else None
        return None

    EVENT_MODERATION_FIELDS = {"hidden", "title_zh", "category", "tags"}

    def update_event_moderation(self, event_id: str, fields: dict[str, Any]) -> bool:
        """Editorial decisions live in override tables, never on
        processed_articles: that row is AI-generated territory and a later
        pipeline run re-scoring the same re-crawled article overwrites it
        unconditionally, which would otherwise silently undo moderation.

        Real events get an event-scoped override so the decision follows the
        event even when a cross-day merge replaces its main article; only
        standalone `a…` pseudo-events fall back to the article-level table."""
        row = self._resolve_processed_row(event_id)
        if row is None:
            return False
        processed, _raw, _source, cluster = row
        if cluster is not None:
            override = self._get_event_override(cluster.id)
            if override is None:
                override = EventEditorialOverrideModel(event_cluster_id=cluster.id)
                self.session.add(override)
        else:
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

    def delete_raw_article(self, event_id: str) -> bool:
        """Permanently remove one article and every row that references it,
        in FK-dependency order, inside the caller's transaction. Mirrors
        update_event_moderation's event_id resolution and commit contract:
        returns False (session untouched) when event_id doesn't resolve to
        a real article; the caller commits on True."""
        row = self._resolve_processed_row(event_id)
        if row is None:
            return False
        _processed, raw, _source, cluster = row
        raw_article_id = raw.id

        self.session.execute(
            delete(DailyReportEntryModel).where(
                DailyReportEntryModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(
            delete(ArticleEmbeddingModel).where(
                ArticleEmbeddingModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(
            delete(ArticleTranslationModel).where(
                ArticleTranslationModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(
            delete(EditorialOverrideModel).where(
                EditorialOverrideModel.raw_article_id == raw_article_id
            )
        )
        # processed_articles must go before event_clusters below:
        # processed_articles.event_cluster_id carries a real FK to
        # event_clusters.id in Postgres (it's a read cache, per the model's
        # docstring, but the FK is still enforced) - deleting the cluster
        # first while this row still references it violates the constraint.
        # Not caught by the SQLite test harness, which doesn't enforce FKs.
        self.session.execute(
            delete(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id == raw_article_id
            )
        )

        cluster_id = cluster.id if cluster is not None else None
        if cluster_id is None:
            found = self._find_cluster_for_raw_article(raw_article_id)
            cluster_id = found.id if found is not None else None

        if cluster_id is not None:
            event_cluster = self.session.get(EventClusterModel, cluster_id)
            remaining = self.session.scalars(
                select(EventClusterArticleModel)
                .where(EventClusterArticleModel.event_cluster_id == cluster_id)
                .where(EventClusterArticleModel.raw_article_id != raw_article_id)
            ).all()
            self.session.execute(
                delete(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == raw_article_id
                )
            )
            # flush before touching `remaining`'s is_main: the partial unique
            # index (one main per event) is checked per statement, so the old
            # main's membership row must actually be gone first (same
            # ordering concern as upsert_event_clusters's demote/promote split)
            self.session.flush()

            if not remaining:
                self.session.execute(
                    delete(EventEditorialOverrideModel).where(
                        EventEditorialOverrideModel.event_cluster_id == cluster_id
                    )
                )
                self.session.execute(
                    delete(EventClusterRedirectModel).where(
                        EventClusterRedirectModel.target_event_id == cluster_id
                    )
                )
                self.session.execute(
                    delete(EventClusterModel).where(EventClusterModel.id == cluster_id)
                )
            elif event_cluster is not None and event_cluster.main_article_id == raw_article_id:
                earliest_id = self.session.execute(
                    select(EventClusterArticleModel.raw_article_id)
                    .join(
                        RawArticleModel,
                        RawArticleModel.id == EventClusterArticleModel.raw_article_id,
                    )
                    .where(EventClusterArticleModel.event_cluster_id == cluster_id)
                    .order_by(RawArticleModel.published_at.asc())
                    .limit(1)
                ).scalar_one()
                for member in remaining:
                    member.is_main = member.raw_article_id == earliest_id
                event_cluster.main_article_id = earliest_id
                event_cluster.source_count = self._count_distinct_sources(cluster_id)
            elif event_cluster is not None:
                event_cluster.source_count = self._count_distinct_sources(cluster_id)

        self.session.execute(delete(RawArticleModel).where(RawArticleModel.id == raw_article_id))
        self.session.flush()
        return True

    def get_event_item(self, event_id: str) -> Optional[dict[str, Any]]:
        row = self._resolve_processed_row(event_id)
        if row is None:
            return None
        processed, raw, source, cluster = row
        # 每篇文章独立管理(2026-07-13 产品决策):隐藏/标题/分类的事件级
        # 覆盖只在这一行本身就是被解析成"主条"时才生效(cluster is not
        # None,即通过真实事件 ID 访问);通过 a{id} 伪地址访问的非主条
        # 永远不受主条的隐藏/覆盖影响，反之亦然。
        #
        # source_count/last_seen_at/coverage 是描述"这篇文章客观上属于
        # 哪个事件"的事实字段，不是治理决定，所以仍然查它真实所属的
        # 聚类(不管是不是主条)。
        member_cluster = cluster if cluster is not None else self._find_cluster_for_raw_article(
            processed.raw_article_id
        )
        override = self._get_override(processed.raw_article_id)
        event_override = self._get_event_override(cluster.id) if cluster is not None else None
        if (override is not None and override.hidden) or (
            event_override is not None and event_override.hidden
        ):
            return None
        translation = self._get_translation_model(processed.raw_article_id)
        # never let _event_item fall back to processed.event_cluster_id (a
        # cache column that can drift/stay stale) for this article's own
        # address - always pass the identity we already resolved reliably
        own_event_id = cluster.id if cluster is not None else f"a{raw.id[:12]}"
        item = _event_item(
            processed,
            raw,
            source,
            include_content=True,
            override=override,
            event_override=event_override,
            translation=translation,
            source_count=member_cluster.source_count if member_cluster else 1,
            event_id=own_event_id,
            last_seen_at=member_cluster.last_seen_at if member_cluster else None,
        )
        if member_cluster is not None:
            item["coverage"] = self.get_event_cluster_coverage(member_cluster.id)
        return item

    def get_event_cluster_coverage(self, event_cluster_id: str) -> list[dict[str, Any]]:
        """Every source article clustered into this event - the "同一事件·N家
        报道" panel. A hidden member is dropped the same way a hidden main
        article would be; this is display-only, never used for dedup."""
        rows = self.session.execute(
            select(EventClusterArticleModel, RawArticleModel, SourceModel, ProcessedArticleModel, EditorialOverrideModel)
            .join(RawArticleModel, EventClusterArticleModel.raw_article_id == RawArticleModel.id)
            .join(SourceModel, RawArticleModel.source_id == SourceModel.id)
            .outerjoin(
                ProcessedArticleModel, ProcessedArticleModel.raw_article_id == RawArticleModel.id
            )
            .outerjoin(
                EditorialOverrideModel, EditorialOverrideModel.raw_article_id == RawArticleModel.id
            )
            .where(EventClusterArticleModel.event_cluster_id == event_cluster_id)
            .order_by(RawArticleModel.published_at.desc())
        ).all()
        coverage = []
        for membership, raw, source, processed, override in rows:
            if override is not None and override.hidden:
                continue
            title = (processed.title_zh if processed and processed.title_zh else None) or raw.title
            coverage.append(
                {
                    "raw_article_id": raw.id,
                    "title": title,
                    "source_name": source.name,
                    "source_url": raw.source_url,
                    "published_at": _as_utc_isoformat(raw.published_at),
                    "is_main": membership.is_main,
                    # 站内跳转地址(2026-07-13):主条用真实事件 ID,非主条
                    # 用文章自己的伪事件地址——前端不用重新推导哈希格式
                    "event_id": event_cluster_id if membership.is_main else f"a{raw.id[:12]}",
                }
            )
        return coverage

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
        "entries": list(model.entries or []),
        "stats": dict(model.stats or {}),
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
    event_override: Optional[EventEditorialOverrideModel] = None,
    translation: Optional[ArticleTranslationModel] = None,
    source_count: int = 1,
    event_id: Optional[str] = None,
    last_seen_at: Optional[datetime] = None,
    is_main: bool = True,
) -> dict[str, Any]:
    metadata = dict(raw.raw_metadata or {})
    published_at = raw.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    if last_seen_at is not None and last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    display_published_at = None if metadata.get("rss_pubdate_missing") else published_at
    # precedence: event-level moderation > article-level moderation > AI value
    title_zh = (
        (event_override.title_zh if event_override and event_override.title_zh else None)
        or (override.title_zh if override and override.title_zh else None)
        or processed.title_zh
    )
    category = (
        (event_override.category if event_override and event_override.category else None)
        or (override.category if override and override.category else None)
        or processed.category
    )
    # tags None means the editor never touched tags; an empty list is a
    # deliberate "clear all tags" decision and must win
    if event_override is not None and event_override.tags is not None:
        tags = list(event_override.tags)
    elif override is not None and override.tags is not None:
        tags = list(override.tags)
    else:
        tags = list(processed.tags or [])
    hidden = bool(
        (override is not None and override.hidden)
        or (event_override is not None and event_override.hidden)
    )
    item: dict[str, Any] = {
        "event_id": event_id or processed.event_cluster_id or f"a{raw.id[:12]}",
        "title": title_zh or raw.title,
        "category": display_category(category),
        "category_label": category_label(category),
        "scoring_category": category,
        "tags": tags,
        "final_score": processed.final_score,
        "selected": processed.status == "processed",
        "selection_origin": processed.selection_origin,
        "selection_reason": processed.selection_reason,
        "hidden": hidden,
        "source_count": max(source_count, 1),
        # 是否为其所属事件的代表条(标准孤立文章也算) - 热点榜靠这个字段
        # 把同一事件的多个成员折叠成一个候选，避免占满前 5 名
        "is_main": is_main,
        "main_source": {
            "id": source.id,
            "name": source.name,
            "url": raw.source_url,
            "tier": source.tier,
        },
        "source_language": raw.language,
        "one_line_summary": processed.one_line_summary,
        "summary": processed.summary_zh,
        "reason": processed.reason_zh,
        "action": processed.action_zh,
        "published_at": display_published_at.isoformat() if display_published_at else None,
        # the event's latest coverage time - hotspot recency anchors on this
        # so an older event that just gained a new source still counts
        "last_seen_at": (last_seen_at or published_at).isoformat()
        if (last_seen_at or published_at)
        else None,
        "crawled_at": raw.crawled_at.isoformat() if raw.crawled_at else None,
        "original_url": raw.source_url,
    }
    images = metadata.get("original_images")
    if images:
        item["original_images"] = images
    if include_content:
        content_origin = str(metadata.get("content_origin") or "")
        is_telegram_rss = content_origin == "telegram_rss_description"
        blocks = _clean_original_blocks(
            metadata.get("original_blocks") or [],
            strip_telegram_signatures=is_telegram_rss,
        )
        paragraphs = (
            _plain_paragraphs_from_blocks(blocks)
            if is_telegram_rss and blocks
            else metadata.get("original_paragraphs") or []
        )
        if is_telegram_rss and not blocks:
            paragraphs = [
                cleaned
                for paragraph in paragraphs
                if (cleaned := _strip_legacy_telegram_signature(str(paragraph)))
            ]
        content = str(
            metadata.get("original_text") or "\n\n".join(str(p) for p in paragraphs)
        ).strip()
        if is_telegram_rss and blocks:
            content = "\n\n".join(str(p) for p in paragraphs)
        if not content:
            # fall back to the crawled body (e.g. a repo description) so the
            # detail page is never blank
            content = str(raw.content or "").strip()
            if content and not paragraphs:
                paragraphs = [content]
        item["original_content"] = content
        item["original_paragraphs"] = paragraphs
        item["original_blocks"] = blocks
        for key in RadarRepository._EVENT_CONTENT_METADATA_KEYS:
            if key in {"original_paragraphs", "original_blocks"}:
                continue
            value = metadata.get(key)
            if value:
                item[key] = value
        if translation is not None:
            if translation.translated_paragraphs:
                item["translated_paragraphs"] = translation.translated_paragraphs
            if translation.translated_blocks:
                item["translated_blocks"] = _clean_original_blocks(
                    translation.translated_blocks,
                    strip_telegram_signatures=is_telegram_rss,
                )
            if translation.status:
                item["translation_status"] = translation.status
            if translation.error:
                item["translation_error"] = translation.error
    return item


def _apply_processed_article(model: ProcessedArticleModel, processed: ProcessedArticle) -> None:
    # event membership is permanent: a later run that re-processes the same
    # article without clustering it hands us event_cluster_id=None, and that
    # must not detach the article from its event (event_cluster_articles is
    # the source of truth; this column is a read cache of it)
    if processed.event_cluster_id is not None:
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
    model.selection_origin = processed.selection_origin
    model.selection_reason = processed.selection_reason


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
