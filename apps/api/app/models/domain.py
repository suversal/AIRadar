from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


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


AIFocus = Literal["primary", "contributing", "tangential"]


@dataclass
class ContentValueDimensions:
    """三个正交的内容价值维度(0-10)，替代原六维加权评分里彼此重叠的
    novelty/impact/information_density/actionability/creator_value。
    ai_relevance不再是这里的一个分量——它是否为AI内容由独立的AIFocus
    分类层判断，不参与value_score的加权求和，避免高分维度稀释掉
    "这根本不是AI内容"这个判断。"""

    impact: float
    novelty: float
    substance: float


@dataclass
class PrefilterResult:
    is_ai_related: bool
    confidence: float
    reason: str


@dataclass
class ScoringResult:
    ai_focus: AIFocus
    dimensions: ContentValueDimensions
    category: str
    tags: list[str]
    title_zh: str
    one_line_summary: str
    summary_zh: str
    reason_zh: str
    action_zh: str
    focus_category: str | None = None


@dataclass
class ProcessedArticle:
    raw_article_id: str
    event_cluster_id: str | None
    ai_focus: AIFocus
    dimensions: ContentValueDimensions
    # final_score = value_score(impact/novelty/substance加权) × 信源tier系数
    # (T1=1.2/T2=1.1/T3=1.0，只加成不惩罚)，clamp到0-100。这是唯一展示给
    # 用户看的分数 - 见scoring_service.py的compute_final_score()
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
    selection_origin: str = "score"
    selection_reason: str | None = None
    focus_category: str | None = None


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
    article_similarities: dict[str, float | None] = field(default_factory=dict)


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
    # per-article reason a raw article never got a ProcessedArticle row at
    # all (no_content, not_ai_related, ai_error, ...) -
    # keyed by raw_article.id, so callers can show a full fetched/verdict
    # breakdown per source, not just the aggregate skipped_reasons counter
    skipped_reason_by_raw_id: dict[str, str] = field(default_factory=dict)
    # 每阶段耗时(秒):ai_candidates/clustering/readme/translation/report,
    # 用于定位"AI 处理中"这个粗阶段里时间的真实去向
    stage_timings: dict[str, float] = field(default_factory=dict)
    # 本轮仅从持久化快照读取、不得再次写回的终态文章。它们仍可参与
    # 聚类和成报，但不能覆盖 raw/processed/embedding/event 数据。
    read_only_raw_article_ids: set[str] = field(default_factory=set)
    # 终态快照通常完全只读；唯一例外是先前流水线在评分后、翻译前中断，
    # 留下了 processed 行却没有 article_translations。后续运行只补写
    # 缺失的翻译派生物，不重写原文、评分、向量或事件关系。
    translation_only_raw_article_ids: set[str] = field(default_factory=set)
