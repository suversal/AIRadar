import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import DailyReport, PipelineResult, RawArticle, Source
from app.pipeline.persistence import persist_pipeline_result


class PipelinePersistenceTests(unittest.TestCase):
    def test_read_only_terminal_articles_do_not_write_article_or_event_rows(self):
        repository = FakeRepository()
        article = RawArticle(
            id="existing",
            source_id="ifanr",
            source_name="爱范儿",
            source_role="context",
            source_tier="T3",
            source_url="https://www.ifanr.com/1673165",
            title="爱范儿文章",
            content="已持久化正文",
            author="爱范儿",
            published_at=datetime(2026, 7, 27, 9, tzinfo=timezone.utc),
            language="zh",
            raw_score={},
            metadata={},
            title_hash="title-existing",
            url_hash="url-existing",
        )
        report = DailyReport(
            report_date=date(2026, 7, 27),
            markdown="# report",
            json_data={
                "report_date": "2026-07-27",
                "items": [{
                    "event_id": "event-existing",
                    "raw_article_id": "existing",
                    "reason": "既有推荐理由",
                    "final_score": 88.0,
                }],
                "article_count": 1,
            },
            article_count=1,
        )
        result = PipelineResult(
            raw_articles=[article],
            processed_articles=[],
            event_clusters=[],
            daily_report=report,
            skipped_reasons={},
            embeddings={"existing": [0.1, 0.2]},
            read_only_raw_article_ids={"existing"},
        )

        persist_pipeline_result(repository, sources=[], result=result)

        self.assertEqual(
            repository.calls,
            [
                "sources",
                "daily_report",
                "daily_report_entries",
                "pipeline_run",
            ],
        )

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

    def test_embedding_failure_deletes_stale_vector_before_event_clustering(self):
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
            metadata={
                "ai_fallback": "embedding_error",
                "embedding_error": "OSError: embedding model unavailable",
            },
            title_hash="title-a1",
            url_hash="url-a1",
        )
        result = PipelineResult(
            raw_articles=[article],
            processed_articles=[],
            event_clusters=[],
            daily_report=DailyReport(
                report_date=date(2026, 7, 1),
                markdown="# report",
                json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
                article_count=0,
            ),
            skipped_reasons={},
            embeddings={},
            embedding_model="bge-small-zh-v1.5",
        )

        persist_pipeline_result(repository, sources=[], result=result)

        self.assertEqual(repository.deleted_embeddings, ["a1"])
        self.assertLess(
            repository.calls.index("delete_article_embedding"),
            repository.calls.index("event_clusters"),
        )
        self.assertNotIn("article_embeddings", repository.calls)


    def test_embedding_source_hash_covers_title_and_content(self):
        # runner 的 embedding 输入是 embedding_input(title, content)；落库的
        # source_hash 必须哈希同一份输入，否则标题变化时哈希不变，血缘失真
        from app.crawlers.base import stable_hash
        from app.services.ai_service import embedding_input

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
            stable_hash(embedding_input("OpenAI releases agent model", "AI model release")),
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
        # 失败的运行也必须留下 DB 记录，否则无法回答"哪一步失败了"；
        # 开始时写入的 running 行必须被"更新"为 failed，而不是另插一行
        import tempfile
        from unittest.mock import patch

        from sqlalchemy import create_engine, func, select
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
                total = session.scalar(select(func.count()).select_from(PipelineRunModel))

        self.assertIsNotNone(run)
        self.assertEqual(total, 1)
        self.assertEqual(run.status, "failed")
        self.assertIn("crawl exploded", run.error)
        self.assertIsNotNone(run.finished_at)

    def test_refresh_refuses_to_start_when_another_run_is_active(self):
        # DB 级防重入：手动触发与调度器曾并发执行（实测 24 秒双跑）；
        # 存在新鲜 running 行时必须拒绝启动，且不再插入新 run 行
        import tempfile
        from unittest.mock import patch

        from sqlalchemy import create_engine, func, select
        from sqlalchemy.orm import Session

        from app.db.models import Base, PipelineRunModel
        from app.repositories.radar_repository import RadarRepository
        from app.services import refresh_service

        with tempfile.TemporaryDirectory() as tmp:
            database_url = f"sqlite+pysqlite:///{Path(tmp) / 'radar.sqlite'}"
            engine = create_engine(database_url, future=True)
            Base.metadata.create_all(engine)
            with Session(engine) as session:
                RadarRepository(session).start_pipeline_run()
                session.commit()

            with patch.object(refresh_service, "crawl_sources") as crawl:
                with self.assertRaises(refresh_service.RefreshAlreadyRunning):
                    refresh_service.refresh_latest_report(
                        data_dir=Path(tmp), database_url=database_url
                    )
                crawl.assert_not_called()

            with Session(engine) as session:
                total = session.scalar(select(func.count()).select_from(PipelineRunModel))

        self.assertEqual(total, 1)

    def test_persist_finishes_started_run_instead_of_inserting(self):
        # refresh 在开始时已建 running 行并把 run_id 传给 persist；
        # persist 结束时应更新那一行为 succeeded，并把 run_id 盖到派生写入上
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

        persist_pipeline_result(repository, sources=[], result=result, pipeline_run_id=77)

        self.assertNotIn("pipeline_run", repository.calls)
        self.assertEqual(repository.finished_run, (77, "succeeded"))
        self.assertEqual(repository.daily_report_run_id, 77)

    def test_persist_pipeline_result_remaps_event_cluster_id_through_merge_redirects(self):
        # regression, found via real-data verification: upsert_event_clusters
        # can redirect a "new" cluster into a different, already-existing
        # event (cross-day merge). processed_articles/daily_report entries
        # are stamped with the ORIGINAL cluster id back in run_pipeline(),
        # before that redirect decision exists, so persistence must remap
        # them - otherwise they reference an event_clusters row that was
        # never created, and the processed_articles write raises a foreign
        # key violation.
        from app.models.domain import ContentValueDimensions, ProcessedArticle

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
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=8, novelty=8, substance=7),
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

    def test_persist_records_new_ingest_metrics_from_inserted_ids(self):
        # 台账指标(2026-07-12):新入库 = 本轮首次插入的文章数;
        # 精选(新增) = 新入库且 selected 的数量——已存在文章即使本轮再次
        # 入选也不计入,否则缓存复用会把数字重新灌水
        from app.models.domain import ContentValueDimensions, ProcessedArticle

        def _raw(article_id):
            return RawArticle(
                id=article_id,
                source_id="openai_blog",
                source_name="OpenAI Blog",
                source_role="authority",
                source_tier="T1",
                source_url=f"https://openai.com/{article_id}",
                title=article_id,
                content="c",
                author="OpenAI",
                published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                language="en",
                raw_score={},
                metadata={},
                title_hash=f"title-{article_id}",
                url_hash=f"url-{article_id}",
            )

        def _processed(article_id, *, selected):
            return ProcessedArticle(
                raw_article_id=article_id,
                event_cluster_id=None,
                ai_focus="primary",
                dimensions=ContentValueDimensions(impact=8, novelty=8, substance=7),
                final_score=88.0 if selected else 40.0,
                title_zh=article_id,
                one_line_summary="s",
                summary_zh="s",
                reason_zh="r",
                action_zh="a",
                category="model_release",
                tags=[],
                selected=selected,
                status="processed" if selected else "rejected",
            )

        junk = _raw("junk1")
        junk.status = "skipped"
        junk.skipped_reason = "not_ai_related"

        repository = FakeRepository()
        # old1 已存在(重复);new1/new2 新入库;junk1 判非AI直接丢弃
        repository.raw_existing_ids = {"old1"}
        result = PipelineResult(
            raw_articles=[_raw("old1"), _raw("new1"), _raw("new2"), junk],
            processed_articles=[
                _processed("old1", selected=True),   # 旧文章再次入选:不计入新增精选
                _processed("new1", selected=True),   # 新入库且入选:计入
                _processed("new2", selected=False),  # 新入库但未达阈值:属于入库,不丢弃
            ],
            event_clusters=[],
            daily_report=DailyReport(
                report_date=date(2026, 7, 1),
                markdown="# report",
                json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
                article_count=0,
            ),
            skipped_reasons={"not_ai_related": 1},
            skipped_reason_by_raw_id={"junk1": "not_ai_related"},
        )

        summary = persist_pipeline_result(repository, sources=[], result=result)
        kwargs = repository.pipeline_run_kwargs
        self.assertEqual(kwargs["new_raw_count"], 2)
        self.assertEqual(kwargs["new_selected_count"], 1)
        self.assertEqual(kwargs["non_ai_dropped_count"], 1)
        # 恒等式:抓取 = 重复 + 非AI + 入库
        raw_total = len(result.raw_articles)
        duplicate = raw_total - kwargs["new_raw_count"] - kwargs["non_ai_dropped_count"]
        self.assertEqual(raw_total, duplicate + kwargs["non_ai_dropped_count"] + kwargs["new_raw_count"])
        self.assertEqual(duplicate, 1)
        # summary 必须携带同样的指标(2026-07-12 深夜):Telegram 通知等
        # 下游消费者应该从这里读,而不是各自重新计算一遍同样的口径
        self.assertEqual(summary.new_raw_count, 2)
        self.assertEqual(summary.new_selected_count, 1)
        self.assertEqual(summary.non_ai_dropped_count, 1)

        # 预建 running 行的正式路径(finish 分支)必须携带同样的指标;
        # intake(抓取后立即落库)提供的插入清单优先于本次 upsert 的结果
        finish_repository = FakeRepository()
        # 模拟 intake 已把新文章插入:最终 upsert 全部视为已存在
        finish_repository.raw_existing_ids = {"old1", "new1", "new2", "junk1"}
        persist_pipeline_result(
            finish_repository,
            sources=[],
            result=result,
            pipeline_run_id=42,
            intake_inserted_ids=["new1", "new2", "junk1"],
        )
        self.assertEqual(finish_repository.finished_run, (42, "succeeded"))
        self.assertEqual(finish_repository.finished_run_kwargs["new_raw_count"], 2)
        self.assertEqual(finish_repository.finished_run_kwargs["new_selected_count"], 1)
        self.assertEqual(finish_repository.finished_run_kwargs["non_ai_dropped_count"], 1)

    def test_persist_single_article_writes_raw_processed_and_embedding(self):
        # 逐条即时落库(2026-07-12 深夜):每评完一条马上可见;重复调用
        # 幂等(upsert),最终整轮落库再补聚类/日报
        import tempfile

        from app.models.domain import ContentValueDimensions, ProcessedArticle
        from app.pipeline.persistence import persist_single_article_to_database

        article = RawArticle(
            id="live1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/live1",
            title="Live article",
            content="Full fetched body for live persistence.",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="t-live1",
            url_hash="u-live1",
        )
        processed = ProcessedArticle(
            raw_article_id="live1",
            event_cluster_id=None,
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=8, novelty=8, substance=7),
            final_score=88.0,
            title_zh="标题",
            one_line_summary="s",
            summary_zh="s",
            reason_zh="r",
            action_zh="a",
            category="model_release",
            tags=[],
            selected=True,
            status="processed",
        )
        vector = [0.25] + [0.0] * 511

        with tempfile.TemporaryDirectory() as tmpdir:
            database_url = f"sqlite+pysqlite:///{tmpdir}/live.db"
            from sqlalchemy import create_engine

            from app.db.models import Base

            engine = create_engine(database_url, future=True)
            Base.metadata.create_all(engine)

            persist_single_article_to_database(
                database_url,
                article,
                processed,
                vector,
                embedding_model="bge",
                pipeline_run_id=None,
            )
            # 幂等:同一条再次写入不炸、不重复
            persist_single_article_to_database(
                database_url,
                article,
                processed,
                vector,
                embedding_model="bge",
                pipeline_run_id=None,
            )

            from sqlalchemy import text

            with engine.connect() as conn:
                raw_count = conn.execute(text("SELECT count(*) FROM raw_articles")).scalar()
                processed_row = conn.execute(
                    text("SELECT title_zh, final_score FROM processed_articles")
                ).first()
                embedding_count = conn.execute(
                    text("SELECT count(*) FROM article_embeddings")
                ).scalar()

        self.assertEqual(raw_count, 1)
        self.assertEqual(processed_row[0], "标题")
        self.assertEqual(embedding_count, 1)

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
    def __init__(
        self,
        *,
        inserted=0,
        updated=0,
        skipped=0,
        redirects=None,
        inserted_ids=None,
    ):
        self.inserted = inserted
        self.updated = updated
        self.skipped = skipped
        self.redirects = redirects or {}
        self.inserted_ids = inserted_ids or []


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.entries_written = None
        self.embeddings_written = []
        self.deleted_embeddings = []
        self.event_cluster_kwargs = None
        self.processed_articles_written = None
        self.cluster_redirects = {}
        self.pipeline_run_kwargs = None
        self.finished_run = None
        self.finished_run_kwargs = None
        self.daily_report_run_id = None
        # 模拟"库里已存在"的文章 id;其余全部插入(含非AI跳过标记行)
        self.raw_existing_ids = set()

    def upsert_sources(self, sources):
        self.calls.append("sources")
        return FakeWriteResult(inserted=len(sources))

    def upsert_raw_articles(self, articles, **kwargs):
        self.calls.append("raw_articles")
        inserted_ids = [
            article.id for article in articles if article.id not in self.raw_existing_ids
        ]
        return FakeWriteResult(inserted=len(inserted_ids), inserted_ids=inserted_ids)

    def upsert_article_embedding(
        self, raw_article_id, *, embedding_model, vector, source_hash, **kwargs
    ):
        self.calls.append("article_embeddings")
        self.embeddings_written.append((raw_article_id, embedding_model, vector, source_hash))

    def delete_article_embedding(self, raw_article_id):
        self.calls.append("delete_article_embedding")
        self.deleted_embeddings.append(raw_article_id)

    def upsert_daily_report(self, report, **kwargs):
        self.calls.append("daily_report")
        self.daily_report_run_id = kwargs.get("pipeline_run_id")
        return FakeWriteResult(updated=report.article_count + 1)

    def finish_pipeline_run(self, run_id, *, status, **kwargs):
        self.calls.append("finish_pipeline_run")
        self.finished_run = (run_id, status)
        self.finished_run_kwargs = kwargs
        return FakeWriteResult(updated=1)

    def replace_daily_report_entries(self, report_date, entries):
        self.calls.append("daily_report_entries")
        self.entries_written = (report_date, entries)

    def upsert_processed_articles(self, processed_articles, **kwargs):
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
