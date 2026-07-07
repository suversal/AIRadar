import argparse
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import DailyReport, PipelineResult, Source


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline_once.py"
SPEC = importlib.util.spec_from_file_location("run_pipeline_once", SCRIPT_PATH)
run_pipeline_once = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_pipeline_once)


class RunPipelineCLITests(unittest.TestCase):
    def test_persist_result_if_requested_is_noop_by_default(self):
        calls = []
        args = argparse.Namespace(persist_db=False, database_url=None)

        summary = run_pipeline_once.persist_result_if_requested(
            args,
            sources=[self._source()],
            result=self._result(),
            persister=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        self.assertIsNone(summary)
        self.assertEqual(calls, [])

    def test_persist_result_if_requested_requires_database_url(self):
        args = argparse.Namespace(persist_db=True, database_url=None)

        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(ValueError, "database url"):
            run_pipeline_once.persist_result_if_requested(
                args,
                sources=[self._source()],
                result=self._result(),
            )

    def test_persist_result_if_requested_calls_database_persister(self):
        calls = []
        args = argparse.Namespace(
            persist_db=True,
            database_url="sqlite+pysqlite:///:memory:",
        )

        summary = run_pipeline_once.persist_result_if_requested(
            args,
            sources=[self._source()],
            result=self._result(),
            persister=lambda database_url, sources, result: calls.append(
                (database_url, sources, result)
            )
            or "persisted",
        )

        self.assertEqual(summary, "persisted")
        self.assertEqual(calls[0][0], "sqlite+pysqlite:///:memory:")
        self.assertEqual(calls[0][1][0].id, "openai_blog")
        self.assertEqual(calls[0][2].daily_report.report_date, date(2026, 7, 1))

    def _source(self):
        return Source(
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

    def _result(self):
        return PipelineResult(
            raw_articles=[],
            processed_articles=[],
            event_clusters=[],
            daily_report=DailyReport(
                report_date=date(2026, 7, 1),
                markdown="# report",
                json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
                article_count=0,
            ),
            skipped_reasons={},
        )


if __name__ == "__main__":
    unittest.main()
