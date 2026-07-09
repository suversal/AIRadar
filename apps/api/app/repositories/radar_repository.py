from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

try:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard for local stdlib tests
    raise RuntimeError("SQLAlchemy is required for database repositories.") from exc

from app.db.models import DailyReportModel, RawArticleModel, SourceModel
from app.models.domain import DailyReport, RawArticle, Source


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
