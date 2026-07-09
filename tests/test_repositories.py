import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
except ModuleNotFoundError:  # pragma: no cover - local lightweight env may omit SQLAlchemy
    create_engine = None

from app.models.domain import DailyReport, RawArticle, Source


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def test_sources_are_upserted(self):
        from app.db.models import SourceModel
        from app.repositories.radar_repository import RadarRepository

        source = self._source(name="OpenAI Blog")
        updated = self._source(name="OpenAI News")

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([source])
            repository.upsert_sources([updated])
            session.commit()

            stored = session.get(SourceModel, "openai_blog")

        self.assertEqual(stored.name, "OpenAI News")
        self.assertEqual(stored.allowed_domains, ["openai.com"])
        self.assertEqual(stored.config_json, {"priority": "high"})

    def test_raw_articles_are_inserted_once_by_url_hash(self):
        from app.db.models import RawArticleModel
        from app.repositories.radar_repository import RadarRepository

        first = self._article(article_id="a1", title="OpenAI releases agent model")
        duplicate = self._article(article_id="a2", title="Mirror copy")

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            result = repository.upsert_raw_articles([first, duplicate])
            session.commit()

            count = session.scalar(select(func.count()).select_from(RawArticleModel))
            stored = session.scalar(select(RawArticleModel))

        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(count, 1)
        self.assertEqual(stored.id, "a1")

    def test_daily_reports_are_upserted_and_queryable_by_date_and_latest(self):
        from app.repositories.radar_repository import RadarRepository

        first = self._report(date(2026, 7, 1), article_count=1)
        updated = self._report(date(2026, 7, 1), article_count=2)
        latest = self._report(date(2026, 7, 2), article_count=3)

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_daily_report(first)
            repository.upsert_daily_report(updated)
            repository.upsert_daily_report(latest)
            session.commit()

            july_first = repository.get_daily_report_payload(date(2026, 7, 1))
            latest_payload = repository.get_latest_daily_report_payload()

        self.assertEqual(july_first["report_date"], "2026-07-01")
        self.assertEqual(july_first["article_count"], 2)
        self.assertEqual(july_first["items"][0]["title"], "精选 2")
        self.assertEqual(latest_payload["report_date"], "2026-07-02")
        self.assertEqual(latest_payload["article_count"], 3)

    def test_daily_report_payloads_between_returns_range_in_ascending_order(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            for day, count in [(1, 1), (3, 3), (5, 5), (9, 9)]:
                repository.upsert_daily_report(self._report(date(2026, 7, day), article_count=count))
            session.commit()

            payloads = repository.get_daily_report_payloads_between(
                date(2026, 7, 2), date(2026, 7, 6)
            )

        self.assertEqual(
            [payload["report_date"] for payload in payloads],
            ["2026-07-03", "2026-07-05"],
        )

    def _source(self, *, name="OpenAI Blog"):
        return Source(
            id="openai_blog",
            name=name,
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
            config={"priority": "high"},
        )

    def _article(self, *, article_id: str, title: str):
        return RawArticle(
            id=article_id,
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url=f"https://openai.com/{article_id}",
            title=title,
            content="AI model release",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={"score": 1},
            metadata={"origin": "fixture"},
            title_hash=f"title-{article_id}",
            url_hash="same-url",
        )

    def _report(self, report_date: date, *, article_count: int):
        return DailyReport(
            report_date=report_date,
            markdown=f"# {report_date.isoformat()}",
            json_data={
                "report_date": report_date.isoformat(),
                "title": f"Suversal AI Radar 日报 - {report_date.isoformat()}",
                "summary": f"精选 {article_count} 条 AI 情报。",
                "updated_at": "2026-07-01T09:00:00+00:00",
                "items": [{"title": f"精选 {article_count}"}],
                "sections": {"model_release": [{"title": f"精选 {article_count}"}]},
                "article_count": article_count,
            },
            article_count=article_count,
        )


if __name__ == "__main__":
    unittest.main()
