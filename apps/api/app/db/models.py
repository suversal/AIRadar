from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

try:
    from sqlalchemy import (
        JSON,
        Boolean,
        Date,
        DateTime,
        Float,
        ForeignKey,
        Index,
        Integer,
        String,
        Text,
        UniqueConstraint,
        func,
        text,
    )
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard for local stdlib tests
    raise RuntimeError("SQLAlchemy is required for database models.") from exc

try:
    from pgvector.sqlalchemy import Vector
except ModuleNotFoundError:  # pragma: no cover - lightweight stdlib test env may omit pgvector
    Vector = None


class Base(DeclarativeBase):
    pass


class SourceModel(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source_role: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    homepage: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_domains: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    fetch_interval_min: Mapped[int] = mapped_column(Integer, default=60)
    language: Mapped[str] = mapped_column(String, default="en")
    need_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    need_browser: Mapped[bool] = mapped_column(Boolean, default=False)
    can_be_main_source: Mapped[bool] = mapped_column(Boolean, default=True)
    affects_heat_score: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    # the freshest crawl outcome for this source, whichever happened more
    # recently: an admin's manual fetch (per-article save/reject detail) or
    # the latest automatic sync's per-source summary (coarser: counts only,
    # since automatic runs don't track per-article outcome back to source_id)
    last_crawl_result: Mapped[Optional[dict]] = mapped_column(JSON)


class RawArticleModel(Base):
    __tablename__ = "raw_articles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[Optional[str]] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="en")
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    title_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    url_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="raw")
    skipped_reason: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReportModel(Base):
    __tablename__ = "daily_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sections: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # lineage: the pipeline run that last (re)generated this report
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pipeline_runs.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="generated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyReportEntryModel(Base):
    """A daily report's masthead: which events ran, in what order, and the
    AI recommendation text at the moment they were selected. Deliberately
    holds no article content - that is always resolved live from
    processed_articles/raw_articles at read time, so admin moderation and
    content upgrades (retranslation, README fixes) take effect immediately
    instead of being frozen into a JSON snapshot."""

    __tablename__ = "daily_report_entries"
    __table_args__ = (
        UniqueConstraint("report_date", "position", name="uq_daily_report_entries_date_position"),
        # persistence dedupes per event before writing; the DB backstops it
        UniqueConstraint("report_date", "event_id", name="uq_daily_report_entries_date_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # note: event_id has NO foreign key on purpose - unclustered masthead
    # articles legitimately carry the `a…` pseudo-id, which never exists in
    # event_clusters
    report_date: Mapped[date] = mapped_column(
        ForeignKey("daily_reports.report_date"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    raw_article_id: Mapped[str] = mapped_column(ForeignKey("raw_articles.id"), nullable=False)
    reason_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score_at_selection: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArticleTranslationModel(Base):
    """AI-generated translation output for one article, kept out of
    raw_articles.raw_metadata (crawl domain) so the two never need a
    hand-maintained key whitelist to stay apart. source_hash lets the
    pipeline detect that the original content changed and a stale
    translation needs regenerating, without re-translating unchanged
    articles on every run."""

    __tablename__ = "article_translations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_article_id: Mapped[str] = mapped_column(
        ForeignKey("raw_articles.id"), nullable=False, unique=True, index=True
    )
    translated_paragraphs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    translated_blocks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_language: Mapped[Optional[str]] = mapped_column(String)
    target_language: Mapped[str] = mapped_column(String, nullable=False, default="zh")
    source_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="completed")
    error: Mapped[Optional[str]] = mapped_column(Text)
    # lineage: the pipeline run that last (re)generated this translation
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pipeline_runs.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedArticleModel(Base):
    __tablename__ = "processed_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_article_id: Mapped[str] = mapped_column(
        ForeignKey("raw_articles.id"), nullable=False, unique=True, index=True
    )
    # read cache of the article's event, NOT the source of truth - that is
    # event_cluster_articles. Never trust this column for listing/dedup and
    # never let a None overwrite an existing value (see _apply_processed_article)
    event_cluster_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("event_clusters.id"), index=True
    )
    ai_relevance: Mapped[float] = mapped_column(Float, nullable=False)
    novelty: Mapped[float] = mapped_column(Float, nullable=False)
    impact: Mapped[float] = mapped_column(Float, nullable=False)
    information_density: Mapped[float] = mapped_column(Float, nullable=False)
    actionability: Mapped[float] = mapped_column(Float, nullable=False)
    creator_value: Mapped[float] = mapped_column(Float, nullable=False)
    base_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    title_zh: Mapped[str] = mapped_column(Text, nullable=False)
    one_line_summary: Mapped[str] = mapped_column(Text, nullable=False)
    summary_zh: Mapped[str] = mapped_column(Text, nullable=False)
    reason_zh: Mapped[str] = mapped_column(Text, nullable=False)
    action_zh: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model_used: Mapped[Optional[str]] = mapped_column(String)
    # lineage: the pipeline run that last (re)generated this row
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pipeline_runs.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False, default="processed")
    rejection_reason: Mapped[Optional[str]] = mapped_column(String)
    selection_origin: Mapped[str] = mapped_column(String, nullable=False, default="score")
    selection_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EditorialOverrideModel(Base):
    """Human moderation decisions, kept out of processed_articles so a later
    pipeline run re-scoring the same article can never silently clobber them.
    Only columns actually touched by an editor are non-null/true; everything
    else keeps deferring to the AI-generated value on processed_articles."""

    __tablename__ = "editorial_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_article_id: Mapped[str] = mapped_column(
        ForeignKey("raw_articles.id"), nullable=False, unique=True, index=True
    )
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title_zh: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String)
    tags: Mapped[Optional[list]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EventEditorialOverrideModel(Base):
    """Event-scoped moderation. Article-level editorial_overrides stay bound
    to one raw article and silently stop applying when a cross-day merge
    hands the event's main slot to a different article; decisions made
    against an event id live here, keyed by the event itself, so they
    survive main-article changes."""

    __tablename__ = "event_editorial_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id"), nullable=False, unique=True, index=True
    )
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title_zh: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String)
    tags: Mapped[Optional[list]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EventClusterModel(Base):
    __tablename__ = "event_clusters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    main_article_id: Mapped[str] = mapped_column(ForeignKey("raw_articles.id"), nullable=False)
    event_title: Mapped[str] = mapped_column(Text, nullable=False)
    event_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventClusterRedirectModel(Base):
    """Persistent alias for event ids consolidated into a canonical event."""

    __tablename__ = "event_cluster_redirects"

    source_event_id: Mapped[str] = mapped_column(String, primary_key=True)
    target_event_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventClusterArticleModel(Base):
    """THE source of truth for article↔event membership. The cache column
    processed_articles.event_cluster_id may drift; readers must resolve
    membership and per-event dedup through this table."""

    __tablename__ = "event_cluster_articles"
    __table_args__ = (
        UniqueConstraint(
            "event_cluster_id", "raw_article_id", name="uq_event_cluster_articles_member"
        ),
        UniqueConstraint("raw_article_id", name="uq_event_cluster_articles_raw_article"),
        # at most one main article per event, enforced by the DB itself
        Index(
            "uq_event_cluster_articles_main",
            "event_cluster_id",
            unique=True,
            postgresql_where=text("is_main"),
            sqlite_where=text("is_main"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_cluster_id: Mapped[str] = mapped_column(
        ForeignKey("event_clusters.id"), nullable=False, index=True
    )
    raw_article_id: Mapped[str] = mapped_column(
        ForeignKey("raw_articles.id"), nullable=False, index=True
    )
    # clustering evidence; NULL means "unknown" (legacy rows written before
    # evidence was captured) - never fake it as 0.0
    similarity_score: Mapped[Optional[float]] = mapped_column(Float)
    is_main: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # when this article joined the event - distinct from the event's own
    # first_seen_at/last_seen_at, needed to compute a sliding-window "how
    # many sources covered this in the last N hours" heat count that decays
    # instead of only ever accumulating
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ArticleEmbeddingModel(Base):
    """One semantic embedding per article, used to detect the same real-
    world event reported by different sources on different days. Every
    article keeps its own row regardless of similarity to others - this
    table never deduplicates content, it only powers the similarity lookup
    that decides which event an article's coverage belongs to."""

    __tablename__ = "article_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_article_id: Mapped[str] = mapped_column(
        ForeignKey("raw_articles.id"), nullable=False, unique=True, index=True
    )
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    # bge-small-zh-v1.5 is 512-dim; the vector width is tied to whichever
    # local embedding model app.services.ai_service.LocalEmbeddingProvider
    # wraps, so this column must be resized if that model ever changes
    content_vector: Mapped[Any] = mapped_column(Vector(512), nullable=False)
    source_hash: Mapped[str] = mapped_column(String, nullable=False)
    # lineage: the pipeline run that last (re)computed this vector
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pipeline_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PeriodReportModel(Base):
    __tablename__ = "period_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    range_start: Mapped[date] = mapped_column(Date, nullable=False)
    range_end: Mapped[date] = mapped_column(Date, nullable=False)
    mainline_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mainline_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    theme_notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # frozen masthead: which events were selected, in what order, and their
    # score at generation time. Content (title/summary/reason/tags/...) is
    # never stored here - it is always resolved live from event_id via
    # get_event_items_by_ids, same as daily_report_entries.
    entries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # aggregate counts computed once at generation time (source coverage,
    # multi-source ratio, category breakdown) so they stop changing once the
    # period has rolled over, instead of being recomputed on every read
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # lineage: the pipeline run that last (re)generated this report
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pipeline_runs.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False, default="generated")


class PipelineRunModel(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="succeeded")
    # which stage a running refresh is in (crawling/scoring/persisting/reports)
    phase: Mapped[Optional[str]] = mapped_column(String)
    # per-source crawl outcome for this run: {source_id: {status, article_count,
    # fetched_count, duration_ms, error}}
    source_report: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cluster_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # ingest metrics (2026-07-12): raw_count is dominated by re-crawled
    # articles whose AI results are cache-reused, so the ledger surfaces
    # what a run actually contributed. NULL = row predates these columns.
    new_raw_count: Mapped[Optional[int]] = mapped_column(Integer)
    new_selected_count: Mapped[Optional[int]] = mapped_column(Integer)
    # non-AI verdicts dropped outright this run (never stored as rows);
    # 抓取 = 重复 + non_ai_dropped + new_raw 的恒等式成员
    non_ai_dropped_count: Mapped[Optional[int]] = mapped_column(Integer)
    skipped_reasons: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text)


class RefreshScheduleModel(Base):
    __tablename__ = "refresh_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
