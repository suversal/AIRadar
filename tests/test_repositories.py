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

    def test_processed_articles_clusters_and_runs_are_persisted_idempotently(self):
        from app.db.models import (
            EventClusterArticleModel,
            EventClusterModel,
            PipelineRunModel,
            ProcessedArticleModel,
        )
        from app.repositories.radar_repository import RadarRepository

        article = self._article(article_id="a1", title="OpenAI releases agent model")
        processed = self._processed("a1", final_score=88.0)
        cluster = self._cluster("e-abc123", main_article_id="a1")

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article])
            first = repository.upsert_processed_articles([processed])
            again = repository.upsert_processed_articles(
                [self._processed("a1", final_score=91.0)]
            )
            repository.upsert_event_clusters([cluster])
            repository.upsert_event_clusters([cluster])
            repository.record_pipeline_run(
                status="succeeded",
                raw_count=1,
                processed_count=1,
                cluster_count=1,
                skipped_reasons={"below_threshold": 3},
            )
            session.commit()

            self.assertEqual(first.inserted, 1)
            self.assertEqual(again.updated, 1)
            stored = session.scalar(
                select(ProcessedArticleModel).where(
                    ProcessedArticleModel.raw_article_id == "a1"
                )
            )
            self.assertEqual(stored.final_score, 91.0)
            self.assertEqual(stored.title_zh, "中文标题")
            self.assertEqual(
                session.scalar(select(func.count()).select_from(EventClusterModel)), 1
            )
            membership = session.scalars(select(EventClusterArticleModel)).all()
            self.assertEqual(len(membership), 1)
            self.assertTrue(membership[0].is_main)
            run = session.scalar(select(PipelineRunModel))
            self.assertEqual(run.status, "succeeded")
            self.assertEqual(run.skipped_reasons, {"below_threshold": 3})

    def test_cached_results_by_url_hash_return_scoring_and_metadata(self):
        from app.repositories.radar_repository import RadarRepository

        article = self._article(
            article_id="a1", title="OpenAI releases agent model", url_hash="hash-a1"
        )
        article.metadata["translated_paragraphs"] = ["中文段落"]
        skipped = self._article(
            article_id="a2", title="Office lunch menu", url_hash="hash-a2"
        )
        skipped.status = "skipped"
        skipped.skipped_reason = "not_ai_related"

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article, skipped])
            repository.upsert_processed_articles([self._processed("a1")])
            session.commit()

            cached = repository.get_cached_results_by_url_hash(
                [article.url_hash, skipped.url_hash, "unknown-hash"]
            )

        self.assertEqual(set(cached), {article.url_hash, skipped.url_hash})
        hit = cached[article.url_hash]
        self.assertEqual(hit["scoring"]["title_zh"], "中文标题")
        self.assertEqual(hit["scoring"]["category"], "model_release")
        self.assertEqual(hit["scoring"]["dimensions"]["ai_relevance"], 9)
        self.assertEqual(hit["metadata"]["translated_paragraphs"], ["中文段落"])
        miss = cached[skipped.url_hash]
        self.assertIsNone(miss["scoring"])
        self.assertEqual(miss["skipped_reason"], "not_ai_related")

    def _processed(self, raw_article_id, *, final_score=88.0):
        from app.models.domain import ProcessedArticle, ScoreDimensions

        return ProcessedArticle(
            raw_article_id=raw_article_id,
            event_cluster_id=None,
            dimensions=ScoreDimensions(9, 8, 8, 7, 7, 6),
            base_score=7.8,
            final_score=final_score,
            title_zh="中文标题",
            one_line_summary="一句话摘要",
            summary_zh="核心摘要",
            reason_zh="推荐理由",
            action_zh="下一步动作",
            category="model_release",
            tags=["Agent"],
            selected=True,
            status="processed",
        )

    def _cluster(self, cluster_id, *, main_article_id):
        from app.models.domain import EventCluster

        return EventCluster(
            id=cluster_id,
            main_article_id=main_article_id,
            article_ids=[main_article_id],
            event_title="OpenAI releases agent model",
            event_summary="一句话摘要",
            category="model_release",
            tags=["Agent"],
            final_score=88.0,
            source_count=1,
            first_seen_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
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

    def _article(self, *, article_id: str, title: str, url_hash: str = "same-url"):
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
            url_hash=url_hash,
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
