from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.models.domain import DailyReport, PipelineResult, RawArticle, Source


class PipelineRepository(Protocol):
    def upsert_sources(self, sources: list[Source]) -> Any:
        ...

    def upsert_raw_articles(self, articles: list[RawArticle]) -> Any:
        ...

    def upsert_daily_report(self, report: DailyReport) -> Any:
        ...


@dataclass(frozen=True)
class PipelinePersistenceSummary:
    sources: Any
    raw_articles: Any
    daily_report: Any


def persist_pipeline_result(
    repository: PipelineRepository,
    *,
    sources: list[Source],
    result: PipelineResult,
) -> PipelinePersistenceSummary:
    source_result = repository.upsert_sources(sources)
    raw_result = repository.upsert_raw_articles(result.raw_articles)
    daily_result = repository.upsert_daily_report(result.daily_report)
    return PipelinePersistenceSummary(
        sources=source_result,
        raw_articles=raw_result,
        daily_report=daily_result,
    )
