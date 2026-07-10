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

    def test_daily_report_resolves_items_live_from_entries_when_present(self):
        # 去快照化核心行为：有 daily_report_entries 时，精选/日报的 items
        # 必须是当前实时数据（含后台治理结果），而不是生成当天固化的快照。
        from app.repositories.radar_repository import RadarRepository

        report_date = date(2026, 7, 1)
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="旧标题快照")])
            repository.upsert_processed_articles([self._processed("a1")])
            repository.upsert_daily_report(self._report(report_date, article_count=1))
            repository.replace_daily_report_entries(
                report_date,
                [
                    {
                        "event_id": "aa1",
                        "raw_article_id": "a1",
                        "reason": "生成当天的推荐理由快照",
                        "final_score": 88.0,
                    }
                ],
            )
            session.commit()

            # 后台把标题改了——实时数据应该反映这个修改，快照里的旧标题不应该出现
            repository.update_event_moderation("aa1", {"title_zh": "治理后的新标题"})
            session.commit()

            payload = repository.get_daily_report_payload(report_date)

        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["title"], "治理后的新标题")
        # 当日推荐语是编辑决策，来自 entries 快照而不是 processed_articles 当前值
        self.assertEqual(item["reason"], "生成当天的推荐理由快照")
        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(payload["sections"]["model"][0]["title"], "治理后的新标题")

    def test_daily_report_hides_moderated_article_immediately(self):
        from app.repositories.radar_repository import RadarRepository

        report_date = date(2026, 7, 1)
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="将被隐藏")])
            repository.upsert_processed_articles([self._processed("a1")])
            repository.upsert_daily_report(self._report(report_date, article_count=1))
            repository.replace_daily_report_entries(
                report_date,
                [{"event_id": "aa1", "raw_article_id": "a1", "reason": "理由", "final_score": 88.0}],
            )
            session.commit()

            repository.update_event_moderation("aa1", {"hidden": True})
            session.commit()

            payload = repository.get_daily_report_payload(report_date)

        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["article_count"], 0)

    def test_daily_report_falls_back_to_snapshot_without_entries(self):
        # 历史数据（Phase A 之前生成的日报）没有 entries 行，必须继续能读。
        from app.repositories.radar_repository import RadarRepository

        report_date = date(2026, 7, 1)
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_daily_report(self._report(report_date, article_count=2))
            session.commit()

            payload = repository.get_daily_report_payload(report_date)

        self.assertEqual(payload["items"][0]["title"], "精选 2")

    def test_get_event_items_by_ids_preserves_order_and_skips_hidden(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="第一篇", url_hash="u1"),
                    self._article(article_id="a2", title="第二篇", url_hash="u2"),
                    self._article(article_id="a3", title="第三篇", url_hash="u3"),
                ]
            )
            repository.upsert_processed_articles(
                [self._processed("a1"), self._processed("a2"), self._processed("a3")]
            )
            session.commit()
            repository.update_event_moderation("aa2", {"hidden": True})
            session.commit()

            items = repository.get_event_items_by_ids(["aa3", "aa2", "aa1", "unknown-id"])

        # a2 隐藏被剔除，unknown-id 解析不到被跳过，顺序按传入顺序保留
        self.assertEqual([item["event_id"] for item in items], ["aa3", "aa1"])

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

    def test_upsert_article_embedding_stores_and_retrieves_source_hash(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="t")])
            repository.upsert_article_embedding(
                "a1", embedding_model="bge-small-zh-v1.5", vector=self._vec([1.0]), source_hash="h1"
            )
            session.commit()

            source_hash = repository.get_article_embedding_source_hash("a1")

        self.assertEqual(source_hash, "h1")

    def test_new_cluster_merges_into_existing_recent_event_via_embedding_similarity(self):
        # 跨天多源聚合核心行为：今天新抓到的文章和 3 天前已有事件的主文
        # 向量高度相似 → 应该合并进那个已有事件，而不是新建一个。
        from app.repositories.radar_repository import RadarRepository
        from app.db.models import EventClusterArticleModel, EventClusterModel
        from app.models.domain import RawArticle

        old_seen = datetime(2026, 7, 8, 9, tzinfo=timezone.utc)
        new_seen = datetime(2026, 7, 11, 9, tzinfo=timezone.utc)

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="old1", title="旧事件主文", url_hash="u-old"),
                    RawArticle(
                        id="new1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/new1",
                        title="今天的新报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=new_seen,
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-new1",
                        url_hash="u-new",
                    ),
                ]
            )
            repository.upsert_article_embedding(
                "old1", embedding_model="m", vector=self._vec([1.0, 0.0]), source_hash="h-old"
            )
            repository.upsert_article_embedding(
                "new1", embedding_model="m", vector=self._vec([0.99, 0.01]), source_hash="h-new"
            )
            existing_cluster = self._cluster("e-old", main_article_id="old1")
            existing_cluster.first_seen_at = old_seen
            existing_cluster.last_seen_at = old_seen
            repository.upsert_event_clusters([existing_cluster])
            session.commit()
            old_membership = session.scalar(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == "old1"
                )
            )
            original_joined_at = old_membership.joined_at

            new_cluster = self._cluster("e-new-bucket", main_article_id="new1")
            new_cluster.article_ids = ["new1"]
            new_cluster.final_score = 50.0  # lower than existing event's 88.0
            new_cluster.first_seen_at = new_seen
            new_cluster.last_seen_at = new_seen
            result = repository.upsert_event_clusters(
                [new_cluster], cluster_window_hours=168, similarity_threshold=0.9
            )
            session.commit()

            all_clusters = session.scalars(select(EventClusterModel)).all()
            merged = session.get(EventClusterModel, "e-old")
            memberships = session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == "e-old"
                )
            ).all()
            old_membership_after = session.scalar(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == "old1"
                )
            )

        self.assertEqual(len(all_clusters), 1)  # no new event_clusters row created
        self.assertEqual(result.inserted, 0)
        self.assertEqual(result.updated, 1)
        self.assertEqual({m.raw_article_id for m in memberships}, {"old1", "new1"})
        self.assertEqual(merged.source_count, 2)
        # lower-scoring new article must not steal the main slot
        self.assertEqual(merged.main_article_id, "old1")
        self.assertEqual(merged.last_seen_at.replace(tzinfo=timezone.utc), new_seen)
        # pre-existing member's joined_at is never reset by a later merge
        self.assertEqual(old_membership_after.joined_at, original_joined_at)

    def test_new_cluster_adopts_main_when_it_outscores_existing_event(self):
        from app.repositories.radar_repository import RadarRepository
        from app.db.models import EventClusterModel
        from app.models.domain import RawArticle

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="old1", title="旧主文", url_hash="u-old"),
                    RawArticle(
                        id="new1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/new1",
                        title="更高分的新报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-new1",
                        url_hash="u-new",
                    ),
                ]
            )
            repository.upsert_article_embedding(
                "old1", embedding_model="m", vector=self._vec([1.0, 0.0]), source_hash="h-old"
            )
            repository.upsert_article_embedding(
                "new1", embedding_model="m", vector=self._vec([0.99, 0.01]), source_hash="h-new"
            )
            repository.upsert_event_clusters([self._cluster("e-old", main_article_id="old1")])
            session.commit()

            new_cluster = self._cluster("e-new-bucket", main_article_id="new1")
            new_cluster.article_ids = ["new1"]
            new_cluster.final_score = 99.0  # higher than existing event's 88.0
            new_cluster.event_title = "更高分的新报道标题"
            repository.upsert_event_clusters(
                [new_cluster], cluster_window_hours=168, similarity_threshold=0.9
            )
            session.commit()

            merged = session.get(EventClusterModel, "e-old")

        self.assertEqual(merged.main_article_id, "new1")
        self.assertEqual(merged.event_title, "更高分的新报道标题")
        self.assertEqual(merged.final_score, 99.0)

    def test_new_cluster_stays_separate_without_similar_recent_event(self):
        from app.repositories.radar_repository import RadarRepository
        from app.db.models import EventClusterModel

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="old1", title="不相关的旧事件", url_hash="u-old"),
                    self._article(article_id="new1", title="全新的事件", url_hash="u-new"),
                ]
            )
            repository.upsert_article_embedding(
                "old1", embedding_model="m", vector=self._vec([1.0, 0.0]), source_hash="h-old"
            )
            repository.upsert_article_embedding(
                "new1", embedding_model="m", vector=self._vec([0.0, 1.0]), source_hash="h-new"
            )
            repository.upsert_event_clusters([self._cluster("e-old", main_article_id="old1")])
            session.commit()

            new_cluster = self._cluster("e-new-bucket", main_article_id="new1")
            new_cluster.article_ids = ["new1"]
            result = repository.upsert_event_clusters(
                [new_cluster], cluster_window_hours=168, similarity_threshold=0.9
            )
            session.commit()

            all_clusters = session.scalars(select(EventClusterModel)).all()

        self.assertEqual(len(all_clusters), 2)
        self.assertEqual(result.inserted, 1)

    def _vec(self, leading_dims: list[float]) -> list[float]:
        return list(leading_dims) + [0.0] * (512 - len(leading_dims))

    def test_cached_results_by_url_hash_return_scoring_and_metadata(self):
        from app.repositories.radar_repository import RadarRepository

        article = self._article(
            article_id="a1", title="OpenAI releases agent model", url_hash="hash-a1"
        )
        article.metadata["translated_paragraphs"] = ["中文段落"]
        article.metadata["readme_status"] = "ok"
        article.metadata["readme_zh_probe"] = "failed"
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
        # README 状态必须跨轮回填，否则每轮刷新都重抓全部 README（打光
        # GitHub 匿名限额），限流自愈标记也传不到下一轮
        self.assertEqual(hit["metadata"]["readme_status"], "ok")
        self.assertEqual(hit["metadata"]["readme_zh_probe"], "failed")
        miss = cached[skipped.url_hash]
        self.assertIsNone(miss["scoring"])
        self.assertEqual(miss["skipped_reason"], "not_ai_related")

    def test_translation_output_is_not_stored_in_raw_metadata(self):
        # architectural split: translation is AI output, not crawl data, so
        # it must live in its own table rather than raw_articles.raw_metadata
        from app.repositories.radar_repository import RadarRepository
        from app.db.models import RawArticleModel

        article = self._article(article_id="a1", title="t", url_hash="hash-a1")
        article.metadata["translated_paragraphs"] = ["中文段落"]
        article.metadata["translated_blocks"] = [{"type": "paragraph", "text": "中文段落"}]
        article.metadata["translation_source_hash"] = "abc123"
        article.metadata["original_paragraphs"] = ["English paragraph"]

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article])
            session.commit()

            stored = session.get(RawArticleModel, "a1")
            translation = repository.get_article_translation("a1")

        self.assertNotIn("translated_paragraphs", stored.raw_metadata)
        self.assertNotIn("translated_blocks", stored.raw_metadata)
        self.assertNotIn("translation_source_hash", stored.raw_metadata)
        # crawl-domain metadata must be unaffected by the split
        self.assertEqual(stored.raw_metadata["original_paragraphs"], ["English paragraph"])
        self.assertEqual(translation["translated_paragraphs"], ["中文段落"])
        self.assertEqual(translation["source_hash"], "abc123")

    def test_event_detail_includes_translation_from_its_own_table(self):
        from app.repositories.radar_repository import RadarRepository

        article = self._article(article_id="a1", title="t", url_hash="hash-a1")
        article.metadata["translated_paragraphs"] = ["中文段落"]
        article.metadata["translated_blocks"] = [{"type": "paragraph", "text": "中文段落"}]
        article.metadata["translation_status"] = "completed"

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article])
            repository.upsert_processed_articles([self._processed("a1")])
            session.commit()

            detail = repository.get_event_item("aa1")

        self.assertEqual(detail["translated_paragraphs"], ["中文段落"])
        self.assertEqual(
            detail["translated_blocks"], [{"type": "paragraph", "text": "中文段落"}]
        )
        self.assertEqual(detail["translation_status"], "completed")

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
        self.assertIn("crawled_at", selected_item)
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

    def test_hidden_events_are_filtered_from_public_queries(self):
        from app.repositories.radar_repository import RadarRepository

        article = self._article(article_id="a1", title="Visible", url_hash="hash-a1")
        other = self._article(article_id="a2", title="Hidden one", url_hash="hash-a2")

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article, other])
            repository.upsert_processed_articles(
                [self._processed("a1"), self._processed("a2")]
            )
            session.commit()

            updated = repository.update_event_moderation("aa2", {"hidden": True})
            session.commit()

            public_items = repository.get_all_event_items_between(
                date(2026, 6, 30), date(2026, 7, 2)
            )
            admin_items = repository.get_all_event_items_between(
                date(2026, 6, 30), date(2026, 7, 2), include_hidden=True
            )
            detail = repository.get_event_item("aa2")

        self.assertTrue(updated)
        self.assertEqual(len(public_items), 1)
        self.assertEqual(len(admin_items), 2)
        hidden_item = next(i for i in admin_items if i["event_id"] == "aa2")
        self.assertTrue(hidden_item["hidden"])
        self.assertIsNone(detail)  # hidden events 404 publicly

    def test_moderation_survives_a_later_ai_reprocessing_of_the_same_article(self):
        # regression: processed_articles is AI-owned territory. Before
        # editorial_overrides existed, update_event_moderation wrote hidden/
        # title_zh/category/tags directly onto that row, so a later pipeline
        # run that re-crawled and re-scored the same URL (upsert_processed_articles
        # again for the same raw_article_id) would silently overwrite the
        # human's moderation decision with the AI's fresh output.
        from app.repositories.radar_repository import RadarRepository

        article = self._article(article_id="a1", title="Moderated", url_hash="hash-a1")

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article])
            repository.upsert_processed_articles([self._processed("a1")])
            session.commit()

            repository.update_event_moderation(
                "aa1", {"hidden": True, "title_zh": "人工改后的标题"}
            )
            session.commit()

            # a later run re-scores the same article (e.g. RSS re-served the
            # same URL); this must not resurrect it or revert the title
            repository.upsert_processed_articles(
                [self._processed("a1", final_score=95.0)]
            )
            session.commit()

            detail = repository.get_event_item("aa1")
            admin_items = repository.get_all_event_items_between(
                date(2026, 6, 30), date(2026, 7, 2), include_hidden=True
            )

        self.assertIsNone(detail)
        item = next(i for i in admin_items if i["event_id"] == "aa1")
        self.assertTrue(item["hidden"])
        self.assertEqual(item["title"], "人工改后的标题")

    def test_update_event_moderation_edits_and_restores(self):
        from app.repositories.radar_repository import RadarRepository

        article = self._article(article_id="a1", title="Editable", url_hash="hash-a1")
        rejected = self._processed("a1", final_score=40.0)
        rejected.selected = False
        rejected.status = "rejected"
        rejected.rejection_reason = "below_threshold:70"

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article])
            repository.upsert_processed_articles([rejected])
            session.commit()

            repository.update_event_moderation(
                "aa1",
                {"hidden": True, "title_zh": "改后的标题", "category": "research", "tags": ["新标签"]},
            )
            session.commit()
            repository.update_event_moderation("aa1", {"hidden": False})
            session.commit()

            items = repository.get_all_event_items_between(
                date(2026, 6, 30), date(2026, 7, 2), include_hidden=True
            )
            missing = repository.update_event_moderation("a-nope", {"hidden": True})

        item = items[0]
        self.assertEqual(item["title"], "改后的标题")
        self.assertEqual(item["category"], "research")
        self.assertEqual(item["tags"], ["新标签"])
        self.assertFalse(item["hidden"])
        # restore returns to prior rejected status, not processed
        self.assertEqual(item["selected"], False)
        self.assertFalse(missing)

    def test_period_reports_upsert_get_and_archive(self):
        from app.repositories.radar_repository import RadarRepository

        report = {
            "kind": "weekly",
            "period_key": "2026-W28",
            "range_start": "2026-07-06",
            "range_end": "2026-07-12",
            "mainline_title": "智能体落地成为本周主线",
            "mainline_body": "本周……",
            "theme_notes": [{"label": "模型", "note": "多家更新"}],
            "article_count": 12,
            "report_dates": ["2026-07-09", "2026-07-10"],
            "generated_at": "2026-07-10T08:00:00+00:00",
            "status": "generated",
        }

        with self.Session() as session:
            repository = RadarRepository(session)
            first = repository.upsert_period_report(report)
            updated = dict(report, mainline_title="更新后的主线", article_count=15)
            second = repository.upsert_period_report(updated)
            repository.upsert_period_report(
                dict(report, period_key="2026-W27", mainline_title="上周主线")
            )
            session.commit()

            fetched = repository.get_period_report("weekly", "2026-W28")
            missing = repository.get_period_report("weekly", "2026-W99")
            archive = repository.list_period_reports("weekly")

        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.updated, 1)
        self.assertEqual(fetched["mainline_title"], "更新后的主线")
        self.assertEqual(fetched["article_count"], 15)
        self.assertEqual(fetched["theme_notes"], [{"label": "模型", "note": "多家更新"}])
        self.assertIsNone(missing)
        self.assertEqual(
            [entry["period_key"] for entry in archive], ["2026-W28", "2026-W27"]
        )

    def test_list_daily_report_dates(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            for day in [10, 8, 9]:
                repository.upsert_daily_report(self._report(date(2026, 7, day), article_count=1))
            session.commit()

            dates = repository.list_daily_report_dates()

        self.assertEqual(dates, ["2026-07-10", "2026-07-09", "2026-07-08"])

    def test_schedule_config_defaults_then_updates(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)

            defaults = repository.get_schedule_config()
            session.commit()

        self.assertEqual(defaults["enabled"], False)
        self.assertEqual(defaults["interval_minutes"], 120)
        self.assertIsNone(defaults["last_triggered_at"])

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.update_schedule_config(enabled=True, interval_minutes=30)
            session.commit()

            updated = repository.get_schedule_config()

        self.assertEqual(updated["enabled"], True)
        self.assertEqual(updated["interval_minutes"], 30)

    def test_schedule_config_records_trigger_time(self):
        from app.repositories.radar_repository import RadarRepository

        triggered_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.record_schedule_triggered(triggered_at)
            session.commit()

            config = repository.get_schedule_config()

        self.assertEqual(config["last_triggered_at"], triggered_at.isoformat())

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

    def _other_source(self):
        return Source(
            id="techcrunch",
            name="TechCrunch",
            source_role="signal",
            tier="T2",
            type="rss",
            category="news",
            url="https://techcrunch.com/rss.xml",
            homepage="https://techcrunch.com",
            allowed_domains=["techcrunch.com"],
            can_be_main_source=True,
            config={},
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
