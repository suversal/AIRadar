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

    def test_all_event_items_come_from_processed_articles_table(self):
        from app.repositories.radar_repository import RadarRepository

        main = self._article(
            article_id="a1", title="OpenAI releases agent model", url_hash="hash-a1"
        )
        main.metadata["original_images"] = [{"url": "https://openai.com/a.png", "alt": ""}]
        rejected = self._article(
            article_id="a2", title="Minor AI tooling update", url_hash="hash-a2"
        )

        selected = self._processed("a1", final_score=88.0)
        below = self._processed("a2", final_score=40.0)
        below.selected = False
        below.status = "rejected"
        below.rejection_reason = "below_threshold:70"

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([main, rejected])
            repository.upsert_event_clusters([self._cluster("e-abc123", main_article_id="a1")])
            selected.event_cluster_id = "e-abc123"
            repository.upsert_processed_articles([selected, below])
            session.commit()

            items = repository.get_all_event_items_between(
                date(2026, 6, 30), date(2026, 7, 2)
            )
            detail = repository.get_event_item("e-abc123")

        self.assertEqual(len(items), 2)  # rejected articles are visible in /all
        selected_item = next(item for item in items if item["event_id"] == "e-abc123")
        # scoring category model_release surfaces as the display taxonomy
        self.assertEqual(selected_item["category"], "model")
        self.assertEqual(selected_item["category_label"], "模型")
        self.assertEqual(selected_item["scoring_category"], "model_release")
        self.assertEqual(selected_item["final_score"], 88.0)
        self.assertEqual(selected_item["main_source"]["name"], "OpenAI Blog")
        self.assertEqual(
            selected_item["original_images"][0]["url"], "https://openai.com/a.png"
        )
        self.assertNotIn("original_paragraphs", selected_item)
        rejected_item = next(item for item in items if item["event_id"] != "e-abc123")
        self.assertTrue(rejected_item["event_id"].startswith("a"))

        self.assertEqual(detail["event_id"], "e-abc123")
        self.assertEqual(detail["original_url"], "https://openai.com/a1")
        self.assertIn("original_blocks", detail)

    def test_event_item_falls_back_to_raw_content_when_metadata_empty(self):
        from app.repositories.radar_repository import RadarRepository

        article = self._article(
            article_id="a1", title="GitHub Trending: x / y", url_hash="hash-a1"
        )
        article.content = "A tiny AI helper library."
        article.metadata.clear()

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article])
            repository.upsert_processed_articles([self._processed("a1")])
            session.commit()

            detail = repository.get_event_item("aa1")

        self.assertEqual(detail["original_content"], "A tiny AI helper library.")
        self.assertEqual(
            detail["original_paragraphs"], ["A tiny AI helper library."]
        )

    def test_upsert_raw_articles_updates_metadata_and_status_of_existing_rows(self):
        from app.db.models import RawArticleModel
        from app.repositories.radar_repository import RadarRepository

        first = self._article(
            article_id="a1", title="GitHub Trending: x / y", url_hash="hash-a1"
        )

        enriched = self._article(
            article_id="a1", title="GitHub Trending: x / y", url_hash="hash-a1"
        )
        enriched.metadata["original_markdown"] = "# README"
        enriched.metadata["readme_status"] = "ok"
        enriched.status = "processed"

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([first])
            session.commit()

            result = repository.upsert_raw_articles([enriched])
            session.commit()

            stored = session.get(RawArticleModel, "a1")

        self.assertEqual(result.updated, 1)
        self.assertEqual(stored.raw_metadata.get("original_markdown"), "# README")
        self.assertEqual(stored.status, "processed")

    def test_source_health_updates_from_crawl_report(self):
        from app.db.models import SourceModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            session.commit()

            repository.update_source_health(
                {"openai_blog": {"status": "ok", "article_count": 5, "duration_ms": 1200.0, "error": None}}
            )
            session.commit()
            ok_row = session.get(SourceModel, "openai_blog")
            first_rate = ok_row.success_rate
            self.assertIsNotNone(ok_row.last_crawled_at)
            self.assertIsNotNone(ok_row.last_success_at)
            self.assertEqual(ok_row.error_count, 0)
            self.assertGreater(first_rate, 0.5)

            repository.update_source_health(
                {"openai_blog": {"status": "skipped", "article_count": 0, "duration_ms": 100.0, "error": "HTTP 429"}}
            )
            session.commit()
            failed_row = session.get(SourceModel, "openai_blog")

        self.assertEqual(failed_row.error_count, 1)
        self.assertLess(failed_row.success_rate, first_rate)
        # last success timestamp survives the failure
        self.assertIsNotNone(failed_row.last_success_at)

    def test_get_all_sources_returns_domain_objects(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            session.commit()

            sources = repository.get_all_sources()

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].id, "openai_blog")
        self.assertEqual(sources[0].tier, "T1")
        self.assertEqual(sources[0].config, {"priority": "high"})

    def test_admin_overview_queries(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [self._article(article_id="a1", title="t", url_hash="h1")]
            )
            repository.record_pipeline_run(
                status="succeeded",
                raw_count=10,
                processed_count=8,
                cluster_count=2,
                skipped_reasons={"below_threshold": 2},
            )
            session.commit()

            runs = repository.get_recent_pipeline_runs(limit=5)
            sources = repository.list_sources_with_health()
            counts = repository.get_table_counts()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "succeeded")
        self.assertEqual(runs[0]["raw_count"], 10)
        self.assertEqual(sources[0]["id"], "openai_blog")
        self.assertIn("success_rate", sources[0])
        self.assertEqual(counts["raw_articles"], 1)
        self.assertEqual(counts["sources"], 1)

    def test_update_source_fields_whitelists_keys(self):
        from app.db.models import SourceModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            session.commit()

            found = repository.update_source_fields(
                "openai_blog",
                {"is_active": False, "tier": "T2", "id": "hack", "success_rate": 9.9, "config": {"a": 1}},
            )
            missing = repository.update_source_fields("nope", {"is_active": False})
            session.commit()

            model = session.get(SourceModel, "openai_blog")

        self.assertTrue(found)
        self.assertFalse(missing)
        self.assertFalse(model.is_active)
        self.assertEqual(model.tier, "T2")
        self.assertEqual(model.id, "openai_blog")  # id not editable
        self.assertEqual(model.success_rate, 0.0)  # health not editable
        self.assertEqual(model.config_json, {"a": 1})

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
