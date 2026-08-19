"""Tests for scripts/regenerate_period_reports.py."""
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:  # pragma: no cover
    create_engine = None

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "regenerate_period_reports.py"
SPEC = importlib.util.spec_from_file_location("regenerate_period_reports", SCRIPT_PATH)
regenerate_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(regenerate_module)


class TargetsForTests(unittest.TestCase):
    def test_each_period_appears_exactly_once(self):
        # the reason this script exists: looping refresh_service's
        # _regenerate_period_reports over every date would rewrite the same
        # monthly report once per day, paying for a long-form AI call each time
        targets = regenerate_module.targets_for(date(2026, 8, 1), date(2026, 8, 18))

        self.assertEqual(targets.count(("monthly", "2026-08")), 1)
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(
            [key for kind, key in targets if kind == "weekly"],
            ["2026-W31", "2026-W32", "2026-W33", "2026-W34"],
        )

    def test_range_end_is_exclusive(self):
        # 2026-09-01 belongs to 2026-09; an exclusive end keeps a
        # --since/--until pair for August from touching September's report
        targets = regenerate_module.targets_for(date(2026, 8, 31), date(2026, 9, 1))

        self.assertEqual([key for kind, key in targets if kind == "monthly"], ["2026-08"])

    def test_spans_a_month_boundary_when_asked(self):
        targets = regenerate_module.targets_for(date(2026, 8, 30), date(2026, 9, 2))

        self.assertEqual(
            [key for kind, key in targets if kind == "monthly"], ["2026-08", "2026-09"]
        )


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class RegenerateTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def test_periods_without_published_items_are_skipped_not_faked(self):
        # a period with no daily reports must not get a generated row at all -
        # writing an empty one would show readers a report that says nothing
        class BoomProvider:
            def summarize_period(self, *_args, **_kwargs):
                raise AssertionError("must not be called for an empty period")

        with self.Session() as session:
            results = regenerate_module.regenerate(
                session,
                [("weekly", "2026-W32"), ("monthly", "2026-08")],
                ai_provider=BoomProvider(),
                apply=True,
            )

        self.assertEqual([row["status"] for row in results], ["skipped-empty"] * 2)

    def test_dry_run_never_calls_the_provider(self):
        class BoomProvider:
            def summarize_period(self, *_args, **_kwargs):
                raise AssertionError("dry run must not call the provider")

        with self.Session() as session:
            results = regenerate_module.regenerate(
                session,
                [("monthly", "2026-08")],
                ai_provider=BoomProvider(),
                apply=False,
            )

        self.assertEqual(results[0]["status"], "skipped-empty")



@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class RegenerateFinalizeTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def _seed_daily_report(self, session):
        """一份 2026-08-08（W32 周六）的真实日报链路：source → raw →
        processed → daily_report → entries，走仓储正规写入。"""
        from datetime import datetime, timezone

        from app.models.domain import (
            ContentValueDimensions,
            DailyReport,
            ProcessedArticle,
            RawArticle,
            Source,
        )
        from app.repositories.radar_repository import RadarRepository

        repository = RadarRepository(session)
        repository.upsert_sources(
            [
                Source(
                    id="openai_blog",
                    name="OpenAI Blog",
                    source_role="authority",
                    tier="T1",
                    type="rss",
                    category="official",
                    url="https://openai.com/rss.xml",
                    homepage="https://openai.com",
                    allowed_domains=["openai.com"],
                    can_be_main_source=True,
                    config={},
                )
            ]
        )
        repository.upsert_raw_articles(
            [
                RawArticle(
                    id="a1",
                    source_id="openai_blog",
                    source_name="OpenAI Blog",
                    source_role="authority",
                    source_tier="T1",
                    source_url="https://openai.com/a1",
                    title="事件",
                    content="AI model release",
                    author="OpenAI",
                    published_at=datetime(2026, 8, 8, 9, tzinfo=timezone.utc),
                    language="en",
                    raw_score={"score": 1},
                    metadata={},
                    title_hash="title-a1",
                    url_hash="u1",
                )
            ]
        )
        repository.upsert_processed_articles(
            [
                ProcessedArticle(
                    raw_article_id="a1",
                    event_cluster_id=None,
                    ai_focus="primary",
                    dimensions=ContentValueDimensions(impact=8, novelty=8, substance=7),
                    final_score=88.0,
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
            ]
        )
        repository.upsert_daily_report(
            DailyReport(
                report_date=date(2026, 8, 8),
                markdown="# 2026-08-08",
                json_data={
                    "report_date": "2026-08-08",
                    "title": "日报",
                    "summary": "精选 1 条。",
                    "items": [{"title": "事件"}],
                    "sections": {},
                    "article_count": 1,
                },
                article_count=1,
            )
        )
        repository.replace_daily_report_entries(
            date(2026, 8, 8),
            [{"event_id": "aa1", "raw_article_id": "a1", "reason": "入选理由", "final_score": 88.0}],
        )
        session.commit()

    def _seed_finalized_week(self, session):
        from app.repositories.radar_repository import RadarRepository

        repository = RadarRepository(session)
        repository.upsert_period_report(
            {
                "kind": "weekly",
                "period_key": "2026-W32",
                "range_start": "2026-08-03",
                "range_end": "2026-08-09",
                "mainline_title": "定稿主线",
                "mainline_body": "定稿正文",
                "theme_notes": [],
                "article_count": 5,
                "report_dates": ["2026-08-08"],
                "entries": [],
                "stats": {},
                "generated_at": "2026-08-10T00:05:00+00:00",
                "status": "generated",
                "summary_digest": "abc",
                "finalized_at": "2026-08-10T00:05:00+00:00",
            }
        )
        session.commit()

    def test_finalized_periods_are_skipped_without_force(self):
        class BoomProvider:
            def summarize_period(self, *_args, **_kwargs):
                raise AssertionError("finalized period must not be regenerated")

        with self.Session() as session:
            self._seed_finalized_week(session)
            results = regenerate_module.regenerate(
                session,
                [("weekly", "2026-W32")],
                ai_provider=BoomProvider(),
                apply=True,
            )

        self.assertEqual(results[0]["status"], "skipped-finalized")

    def test_force_regenerates_and_keeps_it_finalized(self):
        from app.repositories.radar_repository import RadarRepository

        class LongProvider:
            def summarize_period(self, summary_input, kind, range_label):
                return {
                    "mainline_title": "重写后的主线",
                    "mainline_body": "重" * 260,
                    "category_notes": [{"category": "model", "note": "本周模型动向"}],
                }

        with self.Session() as session:
            self._seed_finalized_week(session)
            # 给这周造一份日报，让 --force 有素材可以重写
            self._seed_daily_report(session)

            results = regenerate_module.regenerate(
                session,
                [("weekly", "2026-W32")],
                ai_provider=LongProvider(),
                apply=True,
                force=True,
                today=date(2026, 8, 19),
            )
            refreshed = RadarRepository(session).get_period_report("weekly", "2026-W32")

        self.assertEqual(results[0]["status"], "generated")
        self.assertTrue(results[0]["finalized"])
        self.assertEqual(refreshed["mainline_title"], "重写后的主线")
        self.assertTrue(refreshed["finalized_at"])

    def test_ended_period_gets_finalized_on_apply(self):
        from app.repositories.radar_repository import RadarRepository

        class LongProvider:
            def summarize_period(self, summary_input, kind, range_label):
                return {
                    "mainline_title": "主线",
                    "mainline_body": "正" * 260,
                    "category_notes": [{"category": "model", "note": "本周模型动向"}],
                }

        with self.Session() as session:
            self._seed_daily_report(session)

            results = regenerate_module.regenerate(
                session,
                [("weekly", "2026-W32")],
                ai_provider=LongProvider(),
                apply=True,
                today=date(2026, 8, 19),
            )
            stored = RadarRepository(session).get_period_report("weekly", "2026-W32")

        self.assertTrue(results[0]["finalized"])
        self.assertTrue(stored["finalized_at"])

if __name__ == "__main__":
    unittest.main()
