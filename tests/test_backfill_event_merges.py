"""Tests for scripts/backfill_event_merges.py.

The fixture reproduces the shape this backfill exists for: one real event whose
coverage arrived across two pipeline runs and was therefore stored as two
events. Vector-wise the second report lands in the recall band against the
first event (0.866 on its centroid, 0.766 against its weakest member), which is
below the 0.90 complete-linkage gate - so only the verifier can join them.
"""
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:  # pragma: no cover
    create_engine = None

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backfill_event_merges.py"
SPEC = importlib.util.spec_from_file_location("backfill_event_merges", SCRIPT_PATH)
backfill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backfill)

SINCE = datetime(2026, 8, 3, tzinfo=timezone.utc)
UNTIL = datetime(2026, 8, 4, tzinfo=timezone.utc)


def _vec(leading: list[float]) -> list[float]:
    return list(leading) + [0.0] * (512 - len(leading))


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class BackfillEventMergesTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def _source(self, source_id="ithome", *, can_be_main=True):
        from app.models.domain import Source

        return Source(
            id=source_id,
            name=source_id,
            source_role="signal",
            tier="T2",
            type="rss",
            category="news",
            url=f"https://{source_id}.example/rss.xml",
            homepage=f"https://{source_id}.example",
            allowed_domains=[f"{source_id}.example"],
            can_be_main_source=can_be_main,
            config={},
        )

    def _article(self, article_id, *, source_id, title, hour):
        from app.models.domain import RawArticle

        return RawArticle(
            id=article_id,
            source_id=source_id,
            source_name=source_id,
            source_role="signal",
            source_tier="T2",
            source_url=f"https://{source_id}.example/{article_id}",
            title=title,
            content=f"{title} 正文",
            author=None,
            published_at=datetime(2026, 8, 3, hour, tzinfo=timezone.utc),
            language="zh",
            raw_score={},
            metadata={},
            title_hash=f"t-{article_id}",
            url_hash=f"u-{article_id}",
        )

    def _processed(self, article_id, event_id, score):
        from app.models.domain import ContentValueDimensions, ProcessedArticle

        return ProcessedArticle(
            raw_article_id=article_id,
            event_cluster_id=event_id,
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=8, novelty=8, substance=7),
            final_score=score,
            title_zh=f"标题-{article_id}",
            one_line_summary="一句话",
            summary_zh="摘要",
            reason_zh="理由",
            action_zh="动作",
            category="model_release",
            tags=["模型"],
            selected=True,
            status="processed",
        )

    def _cluster(self, event_id, *, main_article_id, article_ids, score, sources):
        from app.models.domain import EventCluster

        return EventCluster(
            id=event_id,
            main_article_id=main_article_id,
            article_ids=list(article_ids),
            event_title=f"事件-{event_id}",
            event_summary="摘要",
            category="model_release",
            tags=["模型"],
            final_score=score,
            source_count=sources,
            first_seen_at=SINCE,
            last_seen_at=SINCE,
            article_similarities={article_id: 1.0 for article_id in article_ids},
        )

    def _seed_split_event(self, session):
        """Two stored events that are really one: e-first holds two reports
        (0 and 20 degrees), e-second holds the third at -20 degrees."""
        from app.repositories.radar_repository import RadarRepository

        repository = RadarRepository(session)
        repository.upsert_sources([self._source("ithome"), self._source("infoq")])
        repository.upsert_raw_articles(
            [
                self._article("a1", source_id="ithome", title="阿里发布Qwen3.8-Max", hour=2),
                self._article("a2", source_id="infoq", title="千问Qwen3.8-Max上线", hour=3),
                self._article("a3", source_id="ithome", title="Qwen3.8-Max正式发布", hour=4),
            ]
        )
        repository.upsert_processed_articles(
            [
                self._processed("a1", "e-first", 90.0),
                self._processed("a2", "e-first", 80.0),
                self._processed("a3", "e-second", 70.0),
            ]
        )
        for article_id, vector in (
            ("a1", _vec([1.0, 0.0])),
            ("a2", _vec([0.940, 0.342])),
            ("a3", _vec([0.940, -0.342])),
        ):
            repository.upsert_article_embedding(
                article_id, embedding_model="m", vector=vector, source_hash=f"h-{article_id}"
            )
        repository.upsert_event_clusters(
            [
                self._cluster(
                    "e-first", main_article_id="a1", article_ids=["a1", "a2"], score=90.0, sources=2
                ),
                self._cluster(
                    "e-second", main_article_id="a3", article_ids=["a3"], score=70.0, sources=1
                ),
            ]
        )
        session.commit()
        return repository

    def _plan(self, session, verifier):
        return backfill.plan_merges(
            session,
            since=SINCE,
            until=UNTIL,
            threshold=0.90,
            window_hours=48,
            same_event_verifier=verifier,
        )

    def test_plan_groups_the_split_event_when_the_verifier_confirms(self):
        with self.Session() as session:
            self._seed_split_event(session)

            groups = self._plan(session, lambda _left, _right: True)

        self.assertEqual(groups, [["e-first", "e-second"]])

    def test_plan_is_empty_without_a_verifier(self):
        # merge-only backfill must never act on vector similarity alone
        with self.Session() as session:
            self._seed_split_event(session)

            self.assertEqual(self._plan(session, None), [])

    def test_plan_is_empty_when_the_verifier_rejects(self):
        with self.Session() as session:
            self._seed_split_event(session)

            self.assertEqual(self._plan(session, lambda _left, _right: False), [])

    def test_plan_ignores_articles_outside_the_range(self):
        with self.Session() as session:
            self._seed_split_event(session)

            groups = backfill.plan_merges(
                session,
                since=datetime(2026, 8, 10, tzinfo=timezone.utc),
                until=datetime(2026, 8, 11, tzinfo=timezone.utc),
                threshold=0.90,
                window_hours=48,
                same_event_verifier=lambda _left, _right: True,
            )

        self.assertEqual(groups, [])

    def test_apply_folds_into_the_highest_ranked_event_and_redirects(self):
        from app.db.models import (
            EventClusterArticleModel,
            EventClusterModel,
            EventClusterRedirectModel,
        )

        with self.Session() as session:
            self._seed_split_event(session)

            result = backfill.apply_merges(session, [["e-first", "e-second"]], commit=True)

            self.assertEqual(result["merged_groups"], 1)
            self.assertEqual(result["merged_events"], 1)
            # e-first outranks e-second on score and source count
            self.assertIsNotNone(session.get(EventClusterModel, "e-first"))
            self.assertIsNone(session.get(EventClusterModel, "e-second"))
            members = set(
                session.scalars(
                    select(EventClusterArticleModel.raw_article_id).where(
                        EventClusterArticleModel.event_cluster_id == "e-first"
                    )
                ).all()
            )
            self.assertEqual(members, {"a1", "a2", "a3"})
            # source_count is recomputed from real membership, not incremented
            self.assertEqual(session.get(EventClusterModel, "e-first").source_count, 2)
            redirect = session.get(EventClusterRedirectModel, "e-second")
            self.assertIsNotNone(redirect)
            self.assertEqual(redirect.target_event_id, "e-first")

    def test_apply_rolls_back_when_not_committing(self):
        from app.db.models import EventClusterModel

        with self.Session() as session:
            self._seed_split_event(session)

            result = backfill.apply_merges(session, [["e-first", "e-second"]], commit=False)

            self.assertEqual(result["merged_groups"], 1)

        with self.Session() as session:
            # the rehearsal must leave both events exactly as they were
            self.assertIsNotNone(session.get(EventClusterModel, "e-first"))
            self.assertIsNotNone(session.get(EventClusterModel, "e-second"))

    def test_apply_skips_groups_already_consolidated(self):
        with self.Session() as session:
            self._seed_split_event(session)

            backfill.apply_merges(session, [["e-first", "e-second"]], commit=True)
            again = backfill.apply_merges(session, [["e-first", "e-second"]], commit=True)

        # second pass has nothing live left to fold - must be a no-op, not an error
        self.assertEqual(again["merged_groups"], 0)
        self.assertEqual(again["merged_events"], 0)

    def test_apply_never_splits_an_existing_event(self):
        from app.db.models import EventClusterArticleModel

        with self.Session() as session:
            self._seed_split_event(session)

            backfill.apply_merges(session, [["e-first", "e-second"]], commit=True)

            # a1 and a2 shared an event before the backfill and still do
            surviving = session.scalar(
                select(EventClusterArticleModel.event_cluster_id).where(
                    EventClusterArticleModel.raw_article_id == "a1"
                )
            )
            partner = session.scalar(
                select(EventClusterArticleModel.event_cluster_id).where(
                    EventClusterArticleModel.raw_article_id == "a2"
                )
            )

        self.assertEqual(surviving, partner)


if __name__ == "__main__":
    unittest.main()
