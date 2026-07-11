import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import (
    DailyReport,
    PipelineResult,
    ProcessedArticle,
    RawArticle,
    ScoreDimensions,
)
from app.services.refresh_service import _build_auto_crawl_results


def _article(article_id: str, source_id: str) -> RawArticle:
    return RawArticle(
        id=article_id,
        source_id=source_id,
        source_name=source_id,
        source_role="context",
        source_tier="T2",
        source_url=f"https://example.com/{article_id}",
        title=f"title-{article_id}",
        content="content",
        author=None,
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        language="en",
        raw_score={},
        metadata={},
        title_hash=f"t-{article_id}",
        url_hash=f"u-{article_id}",
    )


def _processed(article_id: str, *, selected: bool) -> ProcessedArticle:
    return ProcessedArticle(
        raw_article_id=article_id,
        event_cluster_id=None,
        dimensions=ScoreDimensions(9, 8, 8, 7, 7, 6),
        base_score=7.8,
        final_score=88.0 if selected else 40.0,
        title_zh=f"标题-{article_id}",
        one_line_summary="s",
        summary_zh="s",
        reason_zh="r",
        action_zh="a",
        category="model_release",
        tags=[],
        selected=selected,
        status="processed" if selected else "rejected",
        rejection_reason=None if selected else "below_threshold:65",
        selection_reason="final_score:88.0>=threshold:65" if selected else None,
    )


def _daily_report() -> DailyReport:
    return DailyReport(
        report_date=date(2026, 7, 1),
        markdown="# report",
        json_data={"report_date": "2026-07-01", "items": [], "article_count": 0},
        article_count=0,
    )


class BuildAutoCrawlResultsTests(unittest.TestCase):
    def test_reflects_real_saved_and_rejected_outcomes_not_just_fetch_count(self):
        # the crawl-stage report only knows "3 articles accepted into the
        # batch" - the real saved/rejected verdict only exists after AI
        # scoring, which is what this function must surface instead
        crawl_report = {
            "per_source": {
                "good_source": {"status": "ok", "duration_ms": 123.0},
            }
        }
        raw_articles = [_article("a1", "good_source"), _article("a2", "good_source"), _article("a3", "good_source")]
        processed = [_processed("a1", selected=True), _processed("a2", selected=False)]
        result = PipelineResult(
            raw_articles=raw_articles,
            processed_articles=processed,
            event_clusters=[],
            daily_report=_daily_report(),
            skipped_reasons={"not_ai_related": 1},
            skipped_reason_by_raw_id={"a3": "not_ai_related"},
        )

        merged = _build_auto_crawl_results(
            crawl_report, result, now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        )

        entry = merged["good_source"]
        self.assertEqual(entry["origin"], "auto")
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["fetched_count"], 3)
        # only a1 was actually selected/saved - not the fetched/accepted-into-batch count of 3
        self.assertEqual(entry["accepted_count"], 1)
        by_id = {a["url"]: a for a in entry["articles"]}
        saved = by_id["https://example.com/a1"]
        rejected = by_id["https://example.com/a2"]
        skipped = by_id["https://example.com/a3"]
        self.assertEqual(saved["outcome"], "saved")
        self.assertTrue(saved["selected"])
        self.assertEqual(rejected["outcome"], "rejected")
        self.assertEqual(rejected["reason"], "below_threshold:65")
        self.assertEqual(skipped["outcome"], "rejected")
        self.assertEqual(skipped["reason"], "not_ai_related")

    def test_passes_through_failed_crawl_stage_sources_without_articles(self):
        crawl_report = {
            "per_source": {
                "bad_source": {"status": "skipped", "error": "HTTP 429", "duration_ms": 50.0},
            }
        }
        result = PipelineResult(
            raw_articles=[],
            processed_articles=[],
            event_clusters=[],
            daily_report=_daily_report(),
            skipped_reasons={},
        )

        merged = _build_auto_crawl_results(
            crawl_report, result, now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        )

        entry = merged["bad_source"]
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["error"], "HTTP 429")
        self.assertEqual(entry["fetched_count"], 0)
        self.assertEqual(entry["accepted_count"], 0)
        self.assertEqual(entry["articles"], [])


if __name__ == "__main__":
    unittest.main()
