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
    # AI-written daily mainline over the day's multi-source events, plus one
    # short note per focus category. Stored rather than recomputed at read
    # time: the text costs an AI call and must not change on every page view.
    mainline_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mainline_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category_notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # pending: never attempted. generated: AI wrote it. skipped: no material.
    summary_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    summary_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # fingerprint of the events the summary was written from; an unchanged
    # digest means a re-run can skip the call instead of re-buying the text
    summary_digest: Mapped[Optional[str]] = mapped_column(Text)
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
    # AI主体性分类:primary/contributing/tangential - 独立于下面三个内容价值
    # 维度,是"这是不是AI内容"的分类判断,不参与value_score加权,详见
    # app.services.scoring_service
    ai_focus: Mapped[str] = mapped_column(String, nullable=False)
    impact: Mapped[float] = mapped_column(Float, nullable=False)
    novelty: Mapped[float] = mapped_column(Float, nullable=False)
    substance: Mapped[float] = mapped_column(Float, nullable=False)
    # final_score = value_score(impact/novelty/substance加权) × 信源tier系数
    # (T1=1.2/T2=1.1/T3=1.0，只加成不惩罚) - 见scoring_service.compute_final_score
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    title_zh: Mapped[str] = mapped_column(Text, nullable=False)
    one_line_summary: Mapped[str] = mapped_column(Text, nullable=False)
    summary_zh: Mapped[str] = mapped_column(Text, nullable=False)
    reason_zh: Mapped[str] = mapped_column(Text, nullable=False)
    action_zh: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    # One primary user interest used by /latest, /all and /topics navigation.
    # The existing category column remains the eight-way scoring taxonomy.
    focus_category: Mapped[Optional[str]] = mapped_column(String, index=True)
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
    one_line_summary: Mapped[Optional[str]] = mapped_column(Text)
    summary_zh: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String)
    tags: Mapped[Optional[list]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ArticleSubmissionModel(Base):
    """Private admin draft/job state for manually supplied articles.

    Drafts deliberately live outside raw_articles/processed_articles.  Nothing
    becomes public until the publisher materializes a ready submission in one
    transaction.
    """

    __tablename__ = "article_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    publication_status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    processing_status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    processing_stage: Mapped[Optional[str]] = mapped_column(String)
    original_url: Mapped[Optional[str]] = mapped_column(Text)
    canonical_url_hash: Mapped[Optional[str]] = mapped_column(String, index=True)
    editor_document: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    editor_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manual_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extracted_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ai_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    field_provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selection_mode: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    raw_article_id: Mapped[Optional[str]] = mapped_column(ForeignKey("raw_articles.id"), index=True)
    last_error_code: Mapped[Optional[str]] = mapped_column(String)
    last_error_detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


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
    # fingerprint of exactly what the AI was shown (same mechanism as
    # daily_reports.summary_digest): equal digest -> the stored text is
    # reused instead of re-bought. Only set when status is "generated", so
    # a fallback row always retries on the next run.
    summary_digest: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # set once by the period's closing pass (first refresh after range_end,
    # succeeding with a generated summary). Non-NULL freezes the whole row:
    # no later run may rewrite the text or the entries/stats snapshot.
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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


class AIUsageStatModel(Base):
    """Billed AI tokens, aggregated per (run, model, operation).

    One row per operation per refresh rather than per API call: a run makes
    hundreds of calls but only needs to answer "which stage spent the money".
    No money amount is stored - DeepSeek's peak/off-peak pricing (from
    2026-08-16) makes the same token count cost different amounts depending
    on when it was spent, so cost is computed by the reader.
    """

    __tablename__ = "ai_usage_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NULL for usage spent outside a refresh (manual articles, ad-hoc scripts)
    pipeline_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("pipeline_runs.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    # prefilter / score_article / verify_same_event / translate_paragraphs / summarize_period
    operation: Mapped[str] = mapped_column(String, nullable=False)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_miss_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # thinking tokens, billed at the output rate; the reason this table exists
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_ai_usage_stats_recorded_at", "recorded_at"),
        Index("ix_ai_usage_stats_operation", "operation"),
    )


class RefreshScheduleModel(Base):
    __tablename__ = "refresh_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class XTweetModel(Base):
    """SourcePilot `/api/v1/x/tweets` 的本地镜像（Phase 4）。

    推文不进 LLM 管线（接入方案决策 4），独立于 raw_articles 存一份、随整库
    同步上云。`payload` 存 SP 返回的整条推文原样——渲染所需字段（display_text、
    互动数、external_urls、引用/转发链）全在里面，SP 契约 minor 升级加字段时
    这边零迁移；单列拎出来的只有过滤与排序要用的几个。

    内容边界必须在同步侧守住：SP 的 x_tweets 表刻意不分 collected/searched
    （契约 §5.4），别人现查捞回的无关推文也在里面——同步时只按订阅 handle
    拉取，见 services/x_tweets_sync.py。
    """

    __tablename__ = "x_tweets"

    tweet_id: Mapped[str] = mapped_column(String, primary_key=True)
    author_handle: Mapped[str] = mapped_column(String, nullable=False, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String, index=True)
    tweet_type: Mapped[str] = mapped_column(String, nullable=False, default="original")
    content_kind: Mapped[str] = mapped_column(String, nullable=False, default="brief", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # 命中的订阅话题，包裹逗号格式（",gpt-5.6,claude-fable-5,"，空 = ""）。
    # 不用 JSON 列做过滤是为了方言中立：LIKE '%,x,%' 在 SQLite（测试）与
    # Postgres（生产）行为一致。原始数组仍在 payload.topics 里。
    topics: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # AR 侧的中文翻译（方案 B：SP 不做翻译，中文化是 AIRADAR 的职责）。
    # 独立列而不塞 payload——payload 每轮同步整体覆盖，译文不能跟着被冲掉。
    # 形状：{display_text_zh, quoted_text_zh?, source_hash, model, translated_at}
    # 或 {skipped: "zh", source_hash}（原文已是中文）。source_hash 对齐原文，
    # 长文正文后补导致 display_text 变了会触发重翻。
    translation: Mapped[Optional[dict]] = mapped_column(JSON)
    first_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FeedbackSubmissionModel(Base):
    """A visitor-submitted note from /feedback. The DB row is the durable
    record; a best-effort Telegram push (see telegram_notifier.py) is just a
    convenience for noticing it quickly, not the source of truth."""

    __tablename__ = "feedback_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
