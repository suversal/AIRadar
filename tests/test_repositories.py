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

    def test_upsert_updates_language_when_recrawl_detects_different_script(self):
        # aihot 场景：首轮存的是 zh 摘要，后续全文抓取到英文原文并在内存里
        # 把 language 翻转为 en——更新分支必须把它持久化，否则译文开关和
        # source_language 展示会一直用错误的旧值
        from dataclasses import replace as dc_replace

        from app.db.models import RawArticleModel
        from app.repositories.radar_repository import RadarRepository

        first = dc_replace(
            self._article(article_id="a1", title="Frontier AI report", url_hash="u1"),
            language="zh",
        )
        recrawled = dc_replace(
            first,
            content="Long English body fetched from the original page." * 3,
            language="en",
        )

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([first])
            repository.upsert_raw_articles([recrawled])
            session.commit()

            stored = session.scalar(select(RawArticleModel).where(RawArticleModel.id == "a1"))

        self.assertEqual(stored.language, "en")

    def test_reprocessing_never_clobbers_event_link_with_none(self):
        # 事件成员关系是永久的：文章后续轮次没进聚类（processed 带 None）
        # 也不能把上一轮写好的事件链接盖掉——这是 /all 重复/丢失的根因之一
        from dataclasses import replace as dc_replace

        from app.db.models import ProcessedArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="主文", url_hash="u1")])
            repository.upsert_processed_articles(
                [dc_replace(self._processed("a1"), event_cluster_id="e-keep")]
            )
            repository.upsert_event_clusters([self._cluster("e-keep", main_article_id="a1")])
            session.commit()

            # 模拟后一轮：同一文章重新处理，本轮未入聚类 → event_cluster_id=None
            repository.upsert_processed_articles([self._processed("a1")])
            session.commit()

            stored = session.scalar(
                select(ProcessedArticleModel).where(ProcessedArticleModel.raw_article_id == "a1")
            )

        self.assertEqual(stored.event_cluster_id, "e-keep")

    def test_all_listing_uses_membership_table_despite_link_drift(self):
        # 回归（实测生产库 14/48 链接漂移）：即使 processed 缓存列被覆写成
        # NULL，/all 也必须以成员表为事实源——事件只出现一次（主文代表），
        # 非主文成员不以独立文章身份重复出现，event_id 和 source_count 正确
        from dataclasses import replace as dc_replace

        from app.db.models import ProcessedArticleModel
        from app.models.domain import RawArticle
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="事件主文", url_hash="u1"),
                    RawArticle(
                        id="b1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/b1",
                        title="同事件另一来源",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-b1",
                        url_hash="u2",
                    ),
                ]
            )
            repository.upsert_processed_articles(
                [
                    dc_replace(self._processed("a1"), event_cluster_id="e-drift"),
                    dc_replace(self._processed("b1"), event_cluster_id="e-drift"),
                ]
            )
            cluster = self._cluster("e-drift", main_article_id="a1")
            cluster.article_ids = ["a1", "b1"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            # 模拟链接漂移：两篇的缓存列都被后续运行覆写成 NULL
            for row in session.scalars(select(ProcessedArticleModel)):
                row.event_cluster_id = None
            session.commit()

            listed = repository.get_all_event_items_between(date(2026, 7, 1), date(2026, 7, 1))

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["event_id"], "e-drift")
        self.assertEqual(listed[0]["source_count"], 2)

    def test_pipeline_run_state_machine_running_to_finished(self):
        # 运行开始即落 running 行（回答"现在有没有任务在跑"），
        # 结束后更新同一行——不是插入第二行
        from app.db.models import PipelineRunModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            run_id = repository.start_pipeline_run()
            session.commit()

            running = session.get(PipelineRunModel, run_id)
            self.assertEqual(running.status, "running")
            self.assertIsNone(running.finished_at)

            repository.finish_pipeline_run(
                run_id,
                status="succeeded",
                raw_count=3,
                processed_count=2,
                cluster_count=1,
                skipped_reasons={"below_threshold": 1},
            )
            session.commit()

            done = session.get(PipelineRunModel, run_id)
            total = session.scalar(select(func.count()).select_from(PipelineRunModel))

        self.assertEqual(done.status, "succeeded")
        self.assertIsNotNone(done.finished_at)
        self.assertEqual(done.raw_count, 3)
        self.assertEqual(total, 1)

    def test_non_ai_articles_are_stored_as_skip_markers(self):
        # 四步流程(2026-07-12 晚):非AI文章保留行(status=skipped)作为
        # "已存在跳过"标记——同一篇非AI文章永远只判一次
        from app.db.models import RawArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            non_ai_new = self._article(article_id="junk1", title="数码促销", url_hash="hash-junk")
            non_ai_new.status = "skipped"
            non_ai_new.skipped_reason = "not_ai_related"
            kept_new = self._article(article_id="good1", title="AI 新文章", url_hash="hash-good")

            result = repository.upsert_raw_articles([non_ai_new, kept_new])
            session.commit()

            stored_junk = session.scalar(
                select(RawArticleModel).where(RawArticleModel.url_hash == "hash-junk")
            )

        self.assertIsNotNone(stored_junk)
        self.assertEqual(stored_junk.status, "skipped")
        self.assertEqual(stored_junk.skipped_reason, "not_ai_related")
        self.assertEqual(sorted(result.inserted_ids), ["good1", "junk1"])

    def test_insert_missing_raw_articles_is_insert_only_intake(self):
        # 抓取后立即落库(默认未入选):只插入库里没有的,已存在的完全
        # 跳过——不合并不更新,让"内容管理可见"先于 AI 处理发生
        from app.db.models import RawArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            existing = self._article(article_id="old1", title="旧标题", url_hash="hash-old")
            repository.upsert_raw_articles([existing])
            session.commit()

            re_crawled = self._article(article_id="old1", title="新标题不应覆盖", url_hash="hash-old")
            fresh = self._article(article_id="new1", title="新文章", url_hash="hash-new")
            result = repository.insert_missing_raw_articles([re_crawled, fresh])
            session.commit()

            old_row = session.scalar(
                select(RawArticleModel).where(RawArticleModel.url_hash == "hash-old")
            )
            total = session.scalar(select(func.count()).select_from(RawArticleModel))

        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.inserted_ids, ["new1"])
        self.assertEqual(old_row.title, "旧标题")  # 已存在的行原样不动
        self.assertEqual(total, 2)

    def test_upsert_raw_articles_reports_which_ids_were_newly_inserted(self):
        # 台账"新入库/重复"指标的数据源:上层需要知道本轮哪些文章是首次入库
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_raw_articles(
                [self._article(article_id="old1", title="已存在文章", url_hash="hash-old")]
            )
            session.commit()

            result = repository.upsert_raw_articles(
                [
                    self._article(article_id="old1", title="已存在文章 更新", url_hash="hash-old"),
                    self._article(article_id="new1", title="新文章一", url_hash="hash-new1"),
                    self._article(article_id="new2", title="新文章二", url_hash="hash-new2"),
                ]
            )
            session.commit()

        self.assertEqual(result.inserted, 2)
        self.assertEqual(sorted(result.inserted_ids), ["new1", "new2"])

    def test_pipeline_run_persists_and_exposes_new_ingest_metrics(self):
        # 台账指标重构(2026-07-12):精选=本轮新入库且入选;重复在读取时
        # 由 raw_count - new_raw_count 派生;历史行(NULL)必须返回 None 而非 0
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            legacy_id = repository.start_pipeline_run()
            repository.finish_pipeline_run(
                legacy_id,
                status="succeeded",
                raw_count=100,
                processed_count=90,
                cluster_count=80,
                skipped_reasons={},
            )
            new_id = repository.start_pipeline_run()
            repository.finish_pipeline_run(
                new_id,
                status="succeeded",
                raw_count=175,
                processed_count=152,
                cluster_count=142,
                skipped_reasons={"not_ai_related": 23},
                new_raw_count=18,
                new_selected_count=3,
                non_ai_dropped_count=12,
            )
            session.commit()

            runs = {run["id"]: run for run in repository.get_recent_pipeline_runs()}

        fresh = runs[new_id]
        self.assertEqual(fresh["new_raw_count"], 18)
        self.assertEqual(fresh["new_selected_count"], 3)
        self.assertEqual(fresh["non_ai_dropped_count"], 12)
        # 恒等式:抓取 = 重复 + 非AI + 入库 → 重复 = 175 - 18 - 12
        self.assertEqual(fresh["duplicate_count"], 175 - 18 - 12)
        legacy = runs[legacy_id]
        self.assertIsNone(legacy["new_raw_count"])
        self.assertIsNone(legacy["new_selected_count"])
        self.assertIsNone(legacy["non_ai_dropped_count"])
        self.assertIsNone(legacy["duplicate_count"])

    def test_active_run_guard_and_stale_sweep(self):
        # DB 级防重入：running 行是跨进程的"有任务在跑"事实源；
        # 进程死掉留下的超龄 running 行必须能被清扫，否则护栏永久卡死
        from datetime import timedelta

        from app.db.models import PipelineRunModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            run_id = repository.start_pipeline_run()
            session.commit()

            active = repository.get_active_pipeline_run()
            self.assertIsNotNone(active)
            self.assertEqual(active["id"], run_id)

            # 回拨 started_at 模拟进程死亡留下的孤儿行
            session.get(PipelineRunModel, run_id).started_at = datetime.now(
                timezone.utc
            ) - timedelta(hours=4)
            session.commit()

            swept = repository.sweep_stale_pipeline_runs(max_age_minutes=180)
            session.commit()

            self.assertEqual(swept, 1)
            self.assertIsNone(repository.get_active_pipeline_run())
            stale = session.get(PipelineRunModel, run_id)

        self.assertEqual(stale.status, "failed")
        self.assertIn("stale", (stale.error or "").lower())
        self.assertIsNotNone(stale.finished_at)

    def test_update_pipeline_run_progress_records_phase_and_source_report(self):
        # 监控需求：运行中要能看到当前阶段和每个信源的实际抓取结果
        from app.repositories.radar_repository import RadarRepository

        report = {
            "openai_blog": {
                "status": "ok",
                "article_count": 5,
                "fetched_count": 8,
                "duration_ms": 1200.5,
                "error": None,
            },
            "reddit_ml": {
                "status": "skipped",
                "article_count": 0,
                "duration_ms": 30.1,
                "error": "HTTP 403",
            },
        }

        with self.Session() as session:
            repository = RadarRepository(session)
            run_id = repository.start_pipeline_run()
            repository.update_pipeline_run_progress(
                run_id, phase="scoring", raw_count=42, source_report=report
            )
            session.commit()

            runs = repository.get_recent_pipeline_runs(limit=1)

        self.assertEqual(runs[0]["phase"], "scoring")
        self.assertEqual(runs[0]["raw_count"], 42)
        self.assertEqual(runs[0]["source_report"]["reddit_ml"]["error"], "HTTP 403")

    def test_upserts_stamp_pipeline_run_id_lineage(self):
        # 派生数据必须能回答"由哪次运行生成"
        from app.db.models import (
            ArticleEmbeddingModel,
            ArticleTranslationModel,
            DailyReportModel,
            ProcessedArticleModel,
        )
        from app.repositories.radar_repository import RadarRepository

        article = self._article(article_id="a1", title="主文", url_hash="u1")
        article.metadata = {
            "origin": "fixture",
            "translated_paragraphs": ["翻译段落"],
            "translation_source_hash": "th",
            "translation_status": "completed",
        }

        with self.Session() as session:
            repository = RadarRepository(session)
            run_id = repository.start_pipeline_run()
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([article], pipeline_run_id=run_id)
            repository.upsert_processed_articles([self._processed("a1")], pipeline_run_id=run_id)
            repository.upsert_article_embedding(
                "a1",
                embedding_model="m",
                vector=self._vec([1.0]),
                source_hash="h",
                pipeline_run_id=run_id,
            )
            repository.upsert_daily_report(
                self._report(date(2026, 7, 1), article_count=1), pipeline_run_id=run_id
            )
            session.commit()

            processed = session.scalar(select(ProcessedArticleModel))
            embedding = session.scalar(select(ArticleEmbeddingModel))
            translation = session.scalar(select(ArticleTranslationModel))
            report = session.scalar(select(DailyReportModel))

        for row in (processed, embedding, translation, report):
            self.assertEqual(row.pipeline_run_id, run_id)

    def test_similarity_score_allows_null_for_unknown_evidence(self):
        # 遗留成员行的相似度是"未知"而非真实的 0——列必须可空以区分两者
        from app.db.models import EventClusterArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="主文", url_hash="u1")])
            repository.upsert_event_clusters([self._cluster("e-null", main_article_id="a1")])
            session.commit()

            session.add(
                EventClusterArticleModel(
                    event_cluster_id="e-null",
                    raw_article_id="b-legacy",
                    similarity_score=None,
                )
            )
            # b-legacy 无 raw 行也能插（SQLite 默认不查 FK），重点是可空性
            session.flush()
            stored = session.scalar(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == "b-legacy"
                )
            )

        self.assertIsNone(stored.similarity_score)

    def test_duplicate_event_membership_is_rejected_by_constraint(self):
        # 数据库层必须兜底：同一文章不能在同一事件中出现两行
        from sqlalchemy.exc import IntegrityError

        from app.db.models import EventClusterArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="主文", url_hash="u1")])
            repository.upsert_event_clusters([self._cluster("e-dup", main_article_id="a1")])
            session.commit()

            session.add(
                EventClusterArticleModel(
                    event_cluster_id="e-dup", raw_article_id="a1", is_main=False
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_second_main_membership_is_rejected_by_constraint(self):
        # 每个事件只能有一个主文成员行
        from sqlalchemy.exc import IntegrityError

        from app.db.models import EventClusterArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="主文", url_hash="u1"),
                    self._article(article_id="b1", title="成员", url_hash="u2"),
                ]
            )
            cluster = self._cluster("e-main", main_article_id="a1")
            cluster.article_ids = ["a1", "b1"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            member = session.scalar(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == "b1"
                )
            )
            member.is_main = True
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_event_moderation_survives_main_article_change(self):
        # 人工修改针对的是"这个事件"，不是"当时恰好是主文的那篇文章"。
        # 跨天合并可能换主文；换主文后人工标题/隐藏必须继续生效。
        from dataclasses import replace as dc_replace

        from app.db.models import EventClusterModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="原主文", url_hash="u1"),
                    self._article(article_id="b1", title="新主文", url_hash="u2"),
                ]
            )
            repository.upsert_processed_articles(
                [
                    dc_replace(self._processed("a1"), event_cluster_id="e-mod"),
                    dc_replace(self._processed("b1"), event_cluster_id="e-mod"),
                ]
            )
            cluster = self._cluster("e-mod", main_article_id="a1")
            cluster.article_ids = ["a1", "b1"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            repository.update_event_moderation("e-mod", {"title_zh": "人工事件标题"})
            session.commit()

            # 模拟跨天合并后更高分文章接管主文槽位
            session.get(EventClusterModel, "e-mod").main_article_id = "b1"
            session.commit()

            items = repository.get_event_items_by_ids(["e-mod"])

        self.assertEqual(items[0]["title"], "人工事件标题")

    def test_event_moderation_hidden_survives_main_article_change(self):
        from dataclasses import replace as dc_replace

        from app.db.models import EventClusterModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="原主文", url_hash="u1"),
                    self._article(article_id="b1", title="新主文", url_hash="u2"),
                ]
            )
            repository.upsert_processed_articles(
                [
                    dc_replace(self._processed("a1"), event_cluster_id="e-hide"),
                    dc_replace(self._processed("b1"), event_cluster_id="e-hide"),
                ]
            )
            cluster = self._cluster("e-hide", main_article_id="a1")
            cluster.article_ids = ["a1", "b1"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            repository.update_event_moderation("e-hide", {"hidden": True})
            session.commit()

            session.get(EventClusterModel, "e-hide").main_article_id = "b1"
            session.commit()

            by_id = repository.get_event_items_by_ids(["e-hide"])
            listed = repository.get_all_event_items_between(date(2026, 7, 1), date(2026, 7, 1))

        self.assertEqual(by_id, [])
        self.assertNotIn("e-hide", {item["event_id"] for item in listed})

    def test_cross_day_merge_records_similarity_to_target_event(self):
        # 跨天并入历史事件的成员，落库的相似度必须是"对目标事件主文"的
        # 真实余弦（触发合并的证据）——不是对自身 bucket 的 1.0
        from app.db.models import EventClusterArticleModel
        from app.models.domain import RawArticle
        from app.repositories.radar_repository import RadarRepository
        from app.services.clustering_service import cosine_similarity

        old_seen = datetime(2026, 7, 8, 9, tzinfo=timezone.utc)
        new_seen = datetime(2026, 7, 11, 9, tzinfo=timezone.utc)
        vec_old = self._vec([1.0, 0.0])
        vec_new = self._vec([0.97, 0.2])

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
                "old1", embedding_model="m", vector=vec_old, source_hash="h-old"
            )
            repository.upsert_article_embedding(
                "new1", embedding_model="m", vector=vec_new, source_hash="h-new"
            )
            existing_cluster = self._cluster("e-old", main_article_id="old1")
            existing_cluster.first_seen_at = old_seen
            existing_cluster.last_seen_at = old_seen
            repository.upsert_event_clusters([existing_cluster])
            session.commit()

            new_cluster = self._cluster("e-new-bucket", main_article_id="new1")
            new_cluster.article_ids = ["new1"]
            new_cluster.article_similarities = {"new1": 1.0}  # 对自身 bucket 恒 1.0
            new_cluster.final_score = 50.0
            new_cluster.first_seen_at = new_seen
            new_cluster.last_seen_at = new_seen
            repository.upsert_event_clusters(
                [new_cluster], cluster_window_hours=168, similarity_threshold=0.9
            )
            session.commit()

            membership = session.scalar(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == "new1"
                )
            )

        expected = cosine_similarity(vec_new, vec_old)
        self.assertLess(expected, 0.999)  # 用例本身保证两个值可区分
        self.assertAlmostEqual(membership.similarity_score, expected, places=4)

    def test_upsert_event_clusters_persists_member_similarity(self):
        # 聚类证据落库：成员行的 similarity_score 来自聚类时的真实计算值
        from app.db.models import EventClusterArticleModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="主文", url_hash="u1"),
                    self._article(article_id="b1", title="同事件成员", url_hash="u2"),
                ]
            )
            cluster = self._cluster("e-sim", main_article_id="a1")
            cluster.article_ids = ["a1", "b1"]
            cluster.article_similarities = {"a1": 1.0, "b1": 0.93}
            repository.upsert_event_clusters([cluster])
            session.commit()

            scores = {
                m.raw_article_id: m.similarity_score
                for m in session.scalars(
                    select(EventClusterArticleModel).where(
                        EventClusterArticleModel.event_cluster_id == "e-sim"
                    )
                )
            }

        self.assertEqual(scores, {"a1": 1.0, "b1": 0.93})

    def test_event_items_report_real_source_count(self):
        # payload 的 source_count 必须来自事件的真实去重来源数，
        # 不能固定为 1（回归：DB 里 6 来源的事件前端显示 1）
        from dataclasses import replace as dc_replace

        from app.models.domain import RawArticle
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="主文", url_hash="u1"),
                    RawArticle(
                        id="b1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/b1",
                        title="同一事件的另一来源报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-b1",
                        url_hash="u2",
                    ),
                ]
            )
            repository.upsert_processed_articles(
                [dc_replace(self._processed("a1"), event_cluster_id="e-multi")]
            )
            cluster = self._cluster("e-multi", main_article_id="a1")
            cluster.article_ids = ["a1", "b1"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            by_id = repository.get_event_items_by_ids(["e-multi"])
            detail = repository.get_event_item("e-multi")
            listed = repository.get_all_event_items_between(date(2026, 7, 1), date(2026, 7, 1))

        self.assertEqual(by_id[0]["source_count"], 2)
        self.assertEqual(detail["source_count"], 2)
        listed_counts = {item["event_id"]: item["source_count"] for item in listed}
        self.assertEqual(listed_counts["e-multi"], 2)

    def test_event_item_includes_coverage_from_every_clustered_source(self):
        # 事件详情页"同一事件·N家报道"板块的数据来源：event_cluster_articles
        # 里的每个成员都要出现，隐藏的成员要被排除，且不是 dedup 用途。
        from dataclasses import replace as dc_replace

        from app.models.domain import RawArticle
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="主文", url_hash="u1"),
                    RawArticle(
                        id="b1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/b1",
                        title="同一事件的另一来源报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 11, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-b1",
                        url_hash="u2",
                    ),
                    RawArticle(
                        id="c1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/c1",
                        title="将被隐藏的第三家报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-c1",
                        url_hash="u3",
                    ),
                ]
            )
            repository.upsert_processed_articles(
                [
                    dc_replace(self._processed("a1"), event_cluster_id="e-multi"),
                    dc_replace(self._processed("b1"), event_cluster_id="e-multi"),
                    dc_replace(self._processed("c1"), event_cluster_id="e-multi"),
                ]
            )
            cluster = self._cluster("e-multi", main_article_id="a1")
            cluster.article_ids = ["a1", "b1", "c1"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            from app.db.models import EditorialOverrideModel

            session.add(EditorialOverrideModel(raw_article_id="c1", hidden=True))
            session.commit()

            detail = repository.get_event_item("e-multi")

        coverage = detail["coverage"]
        # c1 is hidden and must not appear; b1 (11:00) sorts before a1 (09:00
        # per _article() fixture default published_at)
        self.assertEqual([c["raw_article_id"] for c in coverage], ["b1", "a1"])
        self.assertTrue(coverage[1]["is_main"])
        self.assertFalse(coverage[0]["is_main"])
        self.assertEqual(coverage[0]["source_name"], "TechCrunch")

    def test_moderation_can_clear_tags_with_empty_list(self):
        # 编辑把标签清空是一个真实的治理动作：tags=[] 必须覆盖掉机器标签，
        # 只有从未动过标签（override.tags 为 NULL）才回退到机器值。
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="a1", title="待清标签")])
            repository.upsert_processed_articles([self._processed("a1")])
            session.commit()

            repository.update_event_moderation("aa1", {"tags": []})
            session.commit()

            items = repository.get_event_items_by_ids(["aa1"])

        self.assertEqual(items[0]["tags"], [])

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
        # callers (persistence layer) must remap any processed_articles /
        # daily_report_entries that reference the original "e-new-bucket" id -
        # that row was never created, only "e-old" absorbed the new article
        self.assertEqual(result.redirects, {"e-new-bucket": "e-old"})
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
        # 非AI行是"已存在跳过"标记(2026-07-12 晚):缓存必须带出历史
        # 非AI判定,让下一轮直接跳过、不再预筛
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
            repository.upsert_article_embedding(
                "a1",
                embedding_model="bge",
                vector=self._vec([0.5, 0.25]),
                source_hash="h-a1",
            )
            session.commit()

            cached = repository.get_cached_results_by_url_hash(
                [article.url_hash, skipped.url_hash, "unknown-hash"]
            )

        self.assertEqual(set(cached), {article.url_hash, skipped.url_hash})
        miss = cached[skipped.url_hash]
        self.assertIsNone(miss["scoring"])
        self.assertEqual(miss["skipped_reason"], "not_ai_related")
        hit = cached[article.url_hash]
        self.assertEqual(hit["raw_article_id"], "a1")
        self.assertEqual(hit["scoring"]["title_zh"], "中文标题")
        self.assertEqual(hit["scoring"]["category"], "model_release")
        self.assertEqual(hit["scoring"]["dimensions"]["ai_relevance"], 9)
        self.assertEqual(hit["metadata"]["translated_paragraphs"], ["中文段落"])
        # README 状态必须跨轮回填，否则每轮刷新都重抓全部 README（打光
        # GitHub 匿名限额），限流自愈标记也传不到下一轮
        self.assertEqual(hit["metadata"]["readme_status"], "ok")
        self.assertEqual(hit["metadata"]["readme_zh_probe"], "failed")
        # 流程重排(2026-07-12 晚)后缓存文章不再拉正文:必须带回库里的
        # 全文和既有向量,否则 pipeline 会用 feed 摘要重算 embedding,
        # 把全文向量覆盖成劣质向量(34 号运行险些造成的事故)
        self.assertEqual(hit["content"], "AI model release")
        self.assertEqual(hit["embedding"][0], 0.5)
        self.assertEqual(hit["embedding"][1], 0.25)

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

    def test_all_events_listing_shows_one_row_per_event_not_per_member_article(self):
        # regression, found via real-data verification: once an event has
        # multiple source members (cross-day multi-source aggregation), a
        # naive per-processed-article listing shows the same event_id once
        # per member - confirmed live on /api/public/events (duplicate
        # event_id entries, each with a different member's own title).
        from app.repositories.radar_repository import RadarRepository

        main = self._article(article_id="a1", title="主报道", url_hash="hash-a1")
        member = self._article(article_id="a2", title="另一家的报道", url_hash="hash-a2")
        standalone = self._article(article_id="a3", title="独立文章", url_hash="hash-a3")

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([main, member, standalone])
            cluster = self._cluster("e-multi", main_article_id="a1")
            cluster.article_ids = ["a1", "a2"]
            repository.upsert_event_clusters([cluster])
            selected = self._processed("a1", final_score=88.0)
            selected.event_cluster_id = "e-multi"
            second = self._processed("a2", final_score=70.0)
            second.event_cluster_id = "e-multi"
            solo = self._processed("a3", final_score=60.0)
            repository.upsert_processed_articles([selected, second, solo])
            session.commit()

            items = repository.get_all_event_items_between(date(2026, 6, 30), date(2026, 7, 2))

        event_ids = [item["event_id"] for item in items]
        self.assertEqual(len(event_ids), 2)  # one for the event, one standalone
        self.assertEqual(event_ids.count("e-multi"), 1)
        multi_item = next(item for item in items if item["event_id"] == "e-multi")
        # the surviving row must be the main article's own processed record,
        # not whichever member happened to be iterated
        self.assertEqual(multi_item["final_score"], 88.0)

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
            selected_items = repository.get_all_event_items_between(
                date(2026, 6, 30), date(2026, 7, 2), selected_only=True
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
        self.assertEqual(selected_item["main_source"]["id"], "openai_blog")
        self.assertEqual(
            selected_item["original_images"][0]["url"], "https://openai.com/a.png"
        )
        self.assertNotIn("original_paragraphs", selected_item)
        rejected_item = next(item for item in items if item["event_id"] != "e-abc123")
        self.assertTrue(rejected_item["event_id"].startswith("a"))
        self.assertEqual([item["event_id"] for item in selected_items], ["e-abc123"])

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
            "entries": [{"event_id": "c-event-1", "score_at_selection": 92.5}],
            "stats": {"source_coverage_count": 4, "multi_source_ratio": 0.5},
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
        self.assertEqual(
            fetched["entries"], [{"event_id": "c-event-1", "score_at_selection": 92.5}]
        )
        self.assertEqual(fetched["stats"]["source_coverage_count"], 4)
        self.assertIsNone(missing)
        self.assertEqual(
            [entry["period_key"] for entry in archive], ["2026-W28", "2026-W27"]
        )

    def test_regenerate_period_reports_only_includes_published_daily_entries(self):
        """A period report is a rollup of the days' actual daily reports, not
        an independent re-selection - an article that was scored/clustered
        but never made any day's daily report must not leak into the
        weekly/monthly snapshot just because it falls in the date window."""
        import app.db.session as db_session_module
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import FakeAIProvider
        from app.services.refresh_service import _regenerate_period_reports

        report_date = date(2026, 7, 11)
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="a1", title="发布过的日报事件", url_hash="u1"),
                    self._article(article_id="a2", title="评分过但从未上过日报", url_hash="u2"),
                ]
            )
            repository.upsert_processed_articles(
                [self._processed("a1"), self._processed("a2", final_score=90.0)]
            )
            repository.upsert_event_clusters([self._cluster("e-orphan", main_article_id="a2")])
            repository.upsert_daily_report(self._report(report_date, article_count=1))
            repository.replace_daily_report_entries(
                report_date,
                [{"event_id": "aa1", "raw_article_id": "a1", "reason": "入选理由", "final_score": 88.0}],
            )
            session.commit()

        # _regenerate_period_reports opens its own session via
        # build_session_factory(database_url) - point it at this test's
        # in-memory engine instead of a real database
        original_build_session_factory = db_session_module.build_session_factory
        db_session_module.build_session_factory = lambda url: self.Session
        try:
            _regenerate_period_reports("sqlite://unused", report_date, FakeAIProvider())
        finally:
            db_session_module.build_session_factory = original_build_session_factory

        with self.Session() as session:
            repository = RadarRepository(session)
            weekly = repository.get_period_report("weekly", "2026-W28")

        self.assertIsNotNone(weekly)
        self.assertEqual(len(weekly["entries"]), 1)
        self.assertEqual(weekly["entries"][0]["event_id"], "aa1")
        self.assertEqual(weekly["article_count"], 1)

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
