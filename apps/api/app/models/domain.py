from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class Source:
    id: str
    name: str
    source_role: str
    tier: str
    type: str
    category: str
    url: str
    homepage: str
    allowed_domains: list[str]
    fetch_interval_min: int = 60
    language: str = "en"
    country_region: str | None = None
    need_proxy: bool = False
    need_browser: bool = False
    can_be_main_source: bool = True
    affects_heat_score: bool = False
    is_active: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawArticle:
    id: str
    source_id: str
    source_name: str
    source_role: str
    source_tier: str
    source_url: str
    title: str
    content: str
    author: str | None
    published_at: datetime
    language: str
    raw_score: dict[str, Any]
    metadata: dict[str, Any]
    title_hash: str
    url_hash: str
    status: str = "raw"
    skipped_reason: str | None = None


@dataclass
class ScoreDimensions:
    ai_relevance: float
    novelty: float
    impact: float
    information_density: float
    actionability: float
    creator_value: float


@dataclass
class PrefilterResult:
    is_ai_related: bool
    confidence: float
    reason: str


@dataclass
class ScoringResult:
    dimensions: ScoreDimensions
    category: str
    tags: list[str]
    title_zh: str
    one_line_summary: str
    summary_zh: str
    reason_zh: str
    action_zh: str


@dataclass
class ProcessedArticle:
    raw_article_id: str
    event_cluster_id: str | None
    dimensions: ScoreDimensions
    base_score: float
    final_score: float
    title_zh: str
    one_line_summary: str
    summary_zh: str
    reason_zh: str
    action_zh: str
    category: str
    tags: list[str]
    selected: bool
    status: str
    rejection_reason: str | None = None


@dataclass
class EventCluster:
    id: str
    main_article_id: str
    article_ids: list[str]
    event_title: str
    event_summary: str
    category: str
    tags: list[str]
    final_score: float
    source_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    status: str = "published"
    # clustering evidence: per member article, the cosine similarity that
    # justified putting it in this cluster (the seed/main article is 1.0)
    article_similarities: dict[str, float] = field(default_factory=dict)


@dataclass
class DailyReport:
    report_date: date
    markdown: str
    json_data: dict[str, Any]
    article_count: int
    status: str = "generated"


@dataclass
class PipelineResult:
    raw_articles: list[RawArticle]
    processed_articles: list[ProcessedArticle]
    event_clusters: list[EventCluster]
    daily_report: DailyReport
    skipped_reasons: dict[str, int]
    embeddings: dict[str, list[float]] = field(default_factory=dict)
    embedding_model: str = ""
