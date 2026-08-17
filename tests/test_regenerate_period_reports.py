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


if __name__ == "__main__":
    unittest.main()
