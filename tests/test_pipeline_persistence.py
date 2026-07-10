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


class FakeWriteResult:
    def __init__(self, *, inserted=0, updated=0, skipped=0):
        self.inserted = inserted
        self.updated = updated
        self.skipped = skipped


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.entries_written = None
        self.embeddings_written = []
        self.event_cluster_kwargs = None

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
        return FakeWriteResult(inserted=len(processed_articles))

    def upsert_event_clusters(self, clusters, **kwargs):
        self.calls.append("event_clusters")
        self.event_cluster_kwargs = kwargs
        return FakeWriteResult(inserted=len(clusters))

    def record_pipeline_run(self, **kwargs):
        self.calls.append("pipeline_run")
        return FakeWriteResult(inserted=1)


if __name__ == "__main__":
    unittest.main()
