import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import DailyReport, PipelineResult, RawArticle, Source
from app.pipeline.persistence import persist_pipeline_result


class PipelinePersistenceTests(unittest.TestCase):
    def test_persist_pipeline_result_writes_sources_raw_articles_and_daily_report(self):
        repository = FakeRepository()
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
        )
        article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a",
            title="OpenAI releases agent model",
            content="AI model release",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="title-a1",
            url_hash="url-a1",
        )
        daily_report = DailyReport(
            report_date=date(2026, 7, 1),
            markdown="# report",
            json_data={
                "report_date": "2026-07-01",
                "items": [
                    {
                        "event_id": "c1",
                        "raw_article_id": "a1",
                        "reason": "推荐理由",
                        "final_score": 88.0,
                    }
                ],
                "article_count": 1,
            },
            article_count=1,
        )
        result = PipelineResult(
            raw_articles=[article],
            processed_articles=[],
            event_clusters=[],
            daily_report=daily_report,
            skipped_reasons={},
        )

        summary = persist_pipeline_result(repository, sources=[source], result=result)

        self.assertEqual(
            repository.calls,
            [
                "sources",
                "raw_articles",
                # clusters must precede processed articles: processed rows carry
                # an event_cluster_id foreign key into event_clusters
                "event_clusters",
                "processed_articles",
                "daily_report",
                "daily_report_entries",
                "pipeline_run",
            ],
        )
        self.assertEqual(summary.sources.inserted, 1)
        self.assertEqual(summary.raw_articles.inserted, 1)
        self.assertEqual(summary.daily_report.updated, 2)
        self.assertIsNotNone(summary.processed_articles)
        self.assertIsNotNone(summary.event_clusters)
        # masthead entries are derived from the report's own items, not
        # re-fetched separately - keeps write side and content in lockstep
        self.assertEqual(
            repository.entries_written,
            (
                date(2026, 7, 1),
                [
                    {
                        "event_id": "c1",
                        "raw_article_id": "a1",
                        "reason": "推荐理由",
                        "final_score": 88.0,
                    }
                ],
            ),
        )


    def test_persist_pipeline_result_persists_embeddings_before_event_clusters(self):
        # article_embeddings must exist before upsert_event_clusters runs, since
        # the repository's cross-day merge looks up embeddings while deciding
        # whether an incoming cluster should join an existing event.
        repository = FakeRepository()
        article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a",
            title="OpenAI releases agent model",
            content="AI model release",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="title-a1",
            url_hash="url-a1",
        )
        daily_report = DailyReport(
            report_date=date(2026, 7, 1),
            markdown="# report",
            json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
            article_count=0,
        )
        result = PipelineResult(
            raw_articles=[article],
            processed_articles=[],
            event_clusters=[],
            daily_report=daily_report,
            skipped_reasons={},
            embeddings={"a1": [0.1, 0.2]},
            embedding_model="bge-small-zh-v1.5",
        )

        persist_pipeline_result(
            repository,
            sources=[],
            result=result,
            cluster_window_hours=168,
            similarity_threshold=0.9,
        )

        self.assertEqual(
            repository.calls,
            [
                "sources",
                "raw_articles",
                "article_embeddings",
                "event_clusters",
                "processed_articles",
                "daily_report",
                "daily_report_entries",
                "pipeline_run",
            ],
        )
        raw_article_id, embedding_model, vector, source_hash = repository.embeddings_written[0]
        self.assertEqual(raw_article_id, "a1")
        self.assertEqual(embedding_model, "bge-small-zh-v1.5")
        self.assertEqual(vector, [0.1, 0.2])
        self.assertTrue(source_hash)
        self.assertEqual(
            repository.event_cluster_kwargs,
            {"cluster_window_hours": 168, "similarity_threshold": 0.9},
        )


    def test_embedding_source_hash_covers_title_and_content(self):
        # runner 的 embedding 输入是 title+"\n"+content；落库的 source_hash
        # 必须哈希同一份输入，否则标题变化时哈希不变，血缘失真
        from app.crawlers.base import stable_hash

        repository = FakeRepository()
        article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a",
            title="OpenAI releases agent model",
            content="AI model release",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="title-a1",
            url_hash="url-a1",
        )
        daily_report = DailyReport(
            report_date=date(2026, 7, 1),
            markdown="# report",
            json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
            article_count=0,
        )
        result = PipelineResult(
            raw_articles=[article],
            processed_articles=[],
            event_clusters=[],
            daily_report=daily_report,
            skipped_reasons={},
            embeddings={"a1": [0.1, 0.2]},
            embedding_model="bge-small-zh-v1.5",
        )

        persist_pipeline_result(repository, sources=[], result=result)

        _, _, _, source_hash = repository.embeddings_written[0]
        self.assertEqual(
            source_hash,
            stable_hash("OpenAI releases agent model\nAI model release"),
        )

    def test_persist_pipeline_result_records_run_timing(self):
        # pipeline_runs 必须能回答"哪次任务何时开始、何时结束"——
        # started_at 由调用方（refresh）提供，finished_at 在落库时打点
        repository = FakeRepository()
        daily_report = DailyReport(
            report_date=date(2026, 7, 1),
            markdown="# report",
            json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
            article_count=0,
        )
        result = PipelineResult(
            raw_articles=[],
            processed_articles=[],
            event_clusters=[],
            daily_report=daily_report,
            skipped_reasons={},
            embeddings={},
            embedding_model="bge-small-zh-v1.5",
        )
        started = datetime(2026, 7, 1, 8, tzinfo=timezone.utc)

        persist_pipeline_result(repository, sources=[], result=result, started_at=started)

        kwargs = repository.pipeline_run_kwargs
        self.assertEqual(kwargs["status"], "succeeded")
        self.assertEqual(kwargs["started_at"], started)
        self.assertIsNotNone(kwargs["finished_at"])

    def test_refresh_records_failed_pipeline_run(self):
        # 失败的运行也必须留下 DB 记录，否则无法回答"哪一步失败了"
        import tempfile
        from unittest.mock import patch

        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.db.models import Base, PipelineRunModel
        from app.services import refresh_service

        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite+pysqlite:///{Path(tmp) / 'radar.sqlite'}"
            engine = create_engine(database_url, future=True)
            Base.metadata.create_all(engine)

            with patch.object(
                refresh_service, "crawl_sources", side_effect=RuntimeError("crawl exploded")
            ):
                with self.assertRaises(RuntimeError):
                    refresh_service.refresh_latest_report(
                        data_dir=Path(tmp), database_url=database_url
                    )

            with Session(engine) as session:
                run = session.scalar(select(PipelineRunModel))

        self.assertIsNotNone(run)
        self.assertEqual(run.status, "failed")
        self.assertIn("crawl exploded", run.error)
        self.assertIsNotNone(run.finished_at)

    def test_persist_pipeline_result_remaps_event_cluster_id_through_merge_redirects(self):
        # regression, found via real-data verification: upsert_event_clusters
        # can redirect a "new" cluster into a different, already-existing
        # event (cross-day merge). processed_articles/daily_report entries
        # are stamped with the ORIGINAL cluster id back in run_pipeline(),
        # before that redirect decision exists, so persistence must remap
        # them - otherwise they reference an event_clusters row that was
        # never created, and the processed_articles write raises a foreign
        # key violation.
        from app.models.domain import ProcessedArticle, ScoreDimensions

        repository = FakeRepository()
        repository.cluster_redirects = {"c-new": "c-existing"}
        article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a",
            title="t",
            content="c",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="title-a1",
            url_hash="url-a1",
        )
        processed = ProcessedArticle(
            raw_article_id="a1",
            event_cluster_id="c-new",
            dimensions=ScoreDimensions(9, 8, 8, 7, 7, 6),
            base_score=7.8,
            final_score=88.0,
            title_zh="t",
            one_line_summary="s",
            summary_zh="s",
            reason_zh="r",
            action_zh="a",
            category="model_release",
            tags=[],
            selected=True,
            status="processed",
        )
        daily_report = DailyReport(
            report_date=date(2026, 7, 1),
            markdown="# report",
            json_data={
                "report_date": "2026-07-01",
                "items": [
                    {"event_id": "c-new", "raw_article_id": "a1", "reason": "x", "final_score": 88.0}
                ],
                "article_count": 1,
            },
            article_count=1,
        )
        result = PipelineResult(
            raw_articles=[article],
            processed_articles=[processed],
            event_clusters=[],
            daily_report=daily_report,
            skipped_reasons={},
        )

        persist_pipeline_result(repository, sources=[], result=result)

        self.assertEqual(repository.processed_articles_written[0].event_cluster_id, "c-existing")
        self.assertEqual(repository.entries_written[1][0]["event_id"], "c-existing")

    def test_persist_pipeline_result_dedupes_masthead_entries_that_merge_into_the_same_event(self):
        # regression, found via real-data verification: two DIFFERENT
        # in-run clusters ("c-new-1" and "c-new-2", covering two genuinely
        # different articles) can each independently redirect into the same
        # pre-existing event during the cross-day merge. Remapping alone
        # then leaves the daily report masthead with the same event twice.
        repository = FakeRepository()
        repository.cluster_redirects = {"c-new-1": "c-existing", "c-new-2": "c-existing"}
        daily_report = DailyReport(
            report_date=date(2026, 7, 1),
            markdown="# report",
            json_data={
                "report_date": "2026-07-01",
                "items": [
                    {"event_id": "c-new-1", "raw_article_id": "a1", "reason": "x", "final_score": 90.0},
                    {"event_id": "c-new-2", "raw_article_id": "a2", "reason": "y", "final_score": 80.0},
                ],
                "article_count": 2,
            },
            article_count=2,
        )
        result = PipelineResult(
            raw_articles=[],
            processed_articles=[],
            event_clusters=[],
            daily_report=daily_report,
            skipped_reasons={},
        )

        persist_pipeline_result(repository, sources=[], result=result)

        entries = repository.entries_written[1]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event_id"], "c-existing")
        # the higher-scoring of the two merged-away items wins the slot
        self.assertEqual(entries[0]["raw_article_id"], "a1")


class FakeWriteResult:
    def __init__(self, *, inserted=0, updated=0, skipped=0, redirects=None):
        self.inserted = inserted
        self.updated = updated
        self.skipped = skipped
        self.redirects = redirects or {}


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.entries_written = None
        self.embeddings_written = []
        self.event_cluster_kwargs = None
        self.processed_articles_written = None
        self.cluster_redirects = {}
        self.pipeline_run_kwargs = None

    def upsert_sources(self, sources):
        self.calls.append("sources")
        return FakeWriteResult(inserted=len(sources))

    def upsert_raw_articles(self, articles):
        self.calls.append("raw_articles")
        return FakeWriteResult(inserted=len(articles))

    def upsert_article_embedding(self, raw_article_id, *, embedding_model, vector, source_hash):
        self.calls.append("article_embeddings")
        self.embeddings_written.append((raw_article_id, embedding_model, vector, source_hash))

    def upsert_daily_report(self, report):
        self.calls.append("daily_report")
        return FakeWriteResult(updated=report.article_count + 1)

    def replace_daily_report_entries(self, report_date, entries):
        self.calls.append("daily_report_entries")
        self.entries_written = (report_date, entries)

    def upsert_processed_articles(self, processed_articles):
        self.calls.append("processed_articles")
        self.processed_articles_written = processed_articles
        return FakeWriteResult(inserted=len(processed_articles))

    def upsert_event_clusters(self, clusters, **kwargs):
        self.calls.append("event_clusters")
        self.event_cluster_kwargs = kwargs
        return FakeWriteResult(inserted=len(clusters), redirects=self.cluster_redirects)

    def record_pipeline_run(self, **kwargs):
        self.calls.append("pipeline_run")
        self.pipeline_run_kwargs = kwargs
        return FakeWriteResult(inserted=1)


if __name__ == "__main__":
    unittest.main()
