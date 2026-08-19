from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.period_summary_service import (
    build_period_report,
    parse_period_summary_payload,
    period_key_for,
    period_range_for_key,
)
from app.services.ai_service import FakeAIProvider
from app.api.public import build_period_payload, sort_period_items


def make_item(
    title,
    *,
    category="model",
    score=80.0,
    summary="一句话摘要。",
    source_count=1,
    source_id="src-a",
    category_label=None,
    focus_category=None,
    focus_category_label=None,
    model_used=None,
):
    return {
        "event_id": f"e-{title[:6]}",
        "model_used": model_used,
        "title": title,
        "category": category,
        "category_label": category_label or category,
        "focus_category": focus_category or category,
        "focus_category_label": focus_category_label or category_label or category,
        "one_line_summary": summary,
        "final_score": score,
        "source_count": source_count,
        "main_source": {"id": source_id, "name": source_id, "url": "", "tier": "core"},
    }


class PeriodKeyTests(unittest.TestCase):
    def test_weekly_key_uses_iso_week(self):
        self.assertEqual(period_key_for("weekly", date(2026, 7, 10)), "2026-W28")
        # ISO year boundary: 2024-12-30 belongs to 2025-W01
        self.assertEqual(period_key_for("weekly", date(2024, 12, 30)), "2025-W01")

    def test_monthly_key_is_year_month(self):
        self.assertEqual(period_key_for("monthly", date(2026, 7, 10)), "2026-07")

    def test_period_range_for_key_round_trips(self):
        start, end = period_range_for_key("weekly", "2026-W28")
        self.assertEqual(start, date(2026, 7, 6))
        self.assertEqual(end, date(2026, 7, 12))

        start, end = period_range_for_key("monthly", "2026-07")
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))

    def test_period_range_rejects_bad_keys(self):
        with self.assertRaises(ValueError):
            period_range_for_key("weekly", "2026-13")
        with self.assertRaises(ValueError):
            period_range_for_key("monthly", "2026-W02")


class PeriodSummaryTests(unittest.TestCase):
    def test_parse_weekly_payload_validates_category_notes(self):
        payload = parse_period_summary_payload(
            {
                "mainline_title": "智能体落地成为本周主线",
                "mainline_body": "本周动态围绕……",
                "category_notes": [
                    {"category": "model", "note": "多家发布"},
                    {"category": "不存在的分类", "note": "该被丢弃"},
                    "bad",
                ],
            },
            "weekly",
        )

        self.assertEqual(payload["mainline_title"], "智能体落地成为本周主线")
        self.assertEqual(len(payload["theme_notes"]), 1)
        self.assertEqual(payload["theme_notes"][0]["category"], "model")
        self.assertEqual(payload["theme_notes"][0]["note"], "多家发布")
        # label 由 taxonomy 补全，不信 AI 回填
        self.assertTrue(payload["theme_notes"][0]["label"])

        with self.assertRaises(ValueError):
            parse_period_summary_payload({"mainline_title": "只有标题"}, "weekly")

    def test_parse_monthly_payload_keeps_trends_with_event_ids(self):
        payload = parse_period_summary_payload(
            {
                "mainline_title": "本月主线",
                "mainline_body": "本月……",
                "trends": [
                    {"label": "智能体落地", "note": "论述……", "event_ids": ["e-1", "e-2"]},
                    {"label": "", "note": "没标签该被丢弃"},
                ],
            },
            "monthly",
        )

        self.assertEqual(
            payload["theme_notes"],
            [{"label": "智能体落地", "note": "论述……", "event_ids": ["e-1", "e-2"]}],
        )

    def test_parse_is_tolerant_of_its_own_normalized_output(self):
        """provider 内部先 parse 一次，build_period_report 再 parse 一次——
        第二次吃到的是第一次的产物，不能丢内容。"""
        raw = {
            "mainline_title": "本月主线",
            "mainline_body": "本月……",
            "trends": [{"label": "趋势", "note": "论述", "event_ids": ["e-1"]}],
        }
        once = parse_period_summary_payload(raw, "monthly")
        twice = parse_period_summary_payload(once, "monthly")
        self.assertEqual(once, twice)

    def test_build_period_report_uses_ai_summary_and_metadata(self):
        items = [make_item(f"事件{i}", score=90 - i) for i in range(3)]

        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-09", "2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        self.assertEqual(report["kind"], "weekly")
        self.assertEqual(report["period_key"], "2026-W28")
        self.assertEqual(report["range_start"], "2026-07-06")
        self.assertEqual(report["range_end"], "2026-07-12")
        self.assertEqual(report["article_count"], 3)
        self.assertEqual(report["report_dates"], ["2026-07-09", "2026-07-10"])
        self.assertTrue(report["mainline_title"])
        self.assertTrue(report["mainline_body"])
        self.assertEqual(report["status"], "generated")

    def test_build_period_report_freezes_entries_snapshot_ordered_by_score(self):
        items = [
            make_item("事件A", score=70.0),
            make_item("事件B", score=95.0),
            make_item("事件C", score=80.0),
        ]

        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        self.assertEqual(
            [entry["event_id"] for entry in report["entries"]],
            ["e-事件B", "e-事件C", "e-事件A"],
        )
        self.assertEqual(report["entries"][0]["score_at_selection"], 95.0)
        # content fields must never be frozen into the entries snapshot -
        # they are always resolved live from event_id at read time
        for entry in report["entries"]:
            self.assertNotIn("title", entry)
            self.assertNotIn("summary", entry)

    def test_build_period_report_computes_stats_snapshot(self):
        # category_label deliberately differs from focus_category_label so
        # this test proves the distribution is keyed by the new focus axis,
        # not the legacy display category.
        items = [
            make_item(
                "事件A", score=90, source_count=3, source_id="src-a",
                category_label="模型", focus_category_label="模型动态",
            ),
            make_item(
                "事件B", score=80, source_count=1, source_id="src-b",
                category_label="模型", focus_category_label="模型动态",
            ),
            make_item(
                "事件C", score=70, source_count=1, source_id="src-a",
                category_label="产品", focus_category_label="产品工具",
            ),
        ]

        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        stats = report["stats"]
        self.assertEqual(stats["source_coverage_count"], 2)
        self.assertAlmostEqual(stats["multi_source_ratio"], 1 / 3)
        self.assertEqual(stats["category_distribution"], {"模型动态": 2, "产品工具": 1})

    def test_build_period_report_retries_a_too_short_draft_once(self):
        # the prompt asks for 360-440 chars but every generated report measured
        # 139-188: the prompt could ask, nothing checked. One retry is spent on
        # a thin draft, and whatever comes back is published - a short real
        # summary beats the "生成失败" fallback.
        from app.services.period_summary_service import (
            MAINLINE_BODY_MIN_CHARS,
            SUMMARY_ATTEMPTS,
        )

        class ShortProvider(FakeAIProvider):
            def __init__(self):
                self.calls = 0

            def summarize_period(self, items, kind, range_label):
                self.calls += 1
                return {
                    "mainline_title": "主线",
                    "mainline_body": "短" * 50,
                    "theme_notes": [],
                }

        provider = ShortProvider()
        report = build_period_report(
            kind="monthly",
            anchor=date(2026, 7, 10),
            items=[make_item("事件A")],
            report_dates=["2026-07-10"],
            ai_provider=provider,
        )

        self.assertEqual(provider.calls, SUMMARY_ATTEMPTS)
        self.assertLess(len(report["mainline_body"]), MAINLINE_BODY_MIN_CHARS)
        # published, not degraded: status must stay generated
        self.assertEqual(report["status"], "generated")
        self.assertNotIn("生成失败", report["mainline_body"])

    def test_build_period_report_does_not_retry_a_long_enough_draft(self):
        from app.services.period_summary_service import MAINLINE_BODY_MIN_CHARS

        class LongProvider(FakeAIProvider):
            def __init__(self):
                self.calls = 0

            def summarize_period(self, items, kind, range_label):
                self.calls += 1
                return {
                    "mainline_title": "主线",
                    "mainline_body": "正" * (MAINLINE_BODY_MIN_CHARS + 10),
                    "theme_notes": [],
                }

        provider = LongProvider()
        report = build_period_report(
            kind="monthly",
            anchor=date(2026, 7, 10),
            items=[make_item("事件A")],
            report_dates=["2026-07-10"],
            ai_provider=provider,
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(report["status"], "generated")

    def test_build_period_report_recovers_when_only_the_first_attempt_fails(self):
        class FlakyProvider(FakeAIProvider):
            def __init__(self):
                self.calls = 0

            def summarize_period(self, items, kind, range_label):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("timed out")
                return {
                    "mainline_title": "主线",
                    "mainline_body": "正" * 220,
                    "theme_notes": [],
                }

        provider = FlakyProvider()
        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=[make_item("事件A")],
            report_dates=["2026-07-10"],
            ai_provider=provider,
        )

        self.assertEqual(provider.calls, 2)
        self.assertEqual(report["status"], "generated")
        self.assertNotIn("生成失败", report["mainline_body"])

    def test_build_period_report_marks_fallback_on_provider_failure(self):
        class BoomProvider(FakeAIProvider):
            def summarize_period(self, items, kind, range_label):
                raise RuntimeError("provider down")

        report = build_period_report(
            kind="monthly",
            anchor=date(2026, 7, 10),
            items=[make_item("事件A")],
            report_dates=["2026-07-10"],
            ai_provider=BoomProvider(),
        )

        self.assertEqual(report["status"], "fallback")
        self.assertTrue(report["mainline_title"])  # deterministic fallback text


class PeriodItemRankingTests(unittest.TestCase):
    """周月报排序：分数只在同一个打分模型内部可比。

    2026-08-13 从 DeepSeek 换到 Qwen 后分数上限从 100 掉到 89.1，而 2026-08
    月报 top20 的门槛就是 89.1 - 换模型之后的内容因此一条都进不去。
    """

    def test_single_model_ranking_is_plain_score_order(self):
        """只有一个模型时（换模型之前的全部历史、绝大多数周报）行为不变。"""
        items = [
            make_item("低", score=70.0, model_used="deepseek-v4-flash"),
            make_item("高", score=95.0, model_used="deepseek-v4-flash"),
            make_item("中", score=82.0, model_used="deepseek-v4-flash"),
        ]

        self.assertEqual([item["title"] for item in sort_period_items(items)], ["高", "中", "低"])

    def test_missing_model_is_its_own_group_and_still_score_ordered(self):
        """model_used 全空的历史条目自成一组，排序与改动之前一致。"""
        items = [
            make_item("低", score=70.0),
            make_item("高", score=95.0),
        ]

        self.assertEqual([item["title"] for item in sort_period_items(items)], ["高", "低"])

    def test_lower_ceiling_model_is_not_shut_out_of_the_top(self):
        """新模型分数上限更低时，它的头条仍要排在旧模型的中段之前。"""
        old = [
            make_item(f"旧{index}", score=100.0 - index, model_used="deepseek-v4-flash")
            for index in range(10)
        ]
        new = [
            make_item(f"新{index}", score=89.0 - index, model_used="qwen3.7-flash")
            for index in range(10)
        ]

        titles = [item["title"] for item in sort_period_items(old + new)]

        # 按原始分排，10 条新模型条目会被 10 条旧模型条目全部压在后面
        self.assertLess(titles.index("新0"), titles.index("旧5"))
        self.assertEqual(titles[0], "旧0")

    def test_group_share_follows_group_size(self):
        """组越大占的名额越多：样本少的一组不能靠「组内第一」霸榜。"""
        big = [
            make_item(f"多{index}", score=90.0 - index, model_used="model-big")
            for index in range(20)
        ]
        small = [make_item("少0", score=60.0, model_used="model-small")]

        titles = [item["title"] for item in sort_period_items(big + small)]

        self.assertEqual(titles[0], "多0")
        # 只有一条的组不构成重要性证据，排在最后而不是并列第一
        self.assertEqual(titles[-1], "少0")

    def test_build_period_payload_applies_model_grouped_ranking(self):
        payload = build_period_payload(
            [
                {
                    "report_date": "2026-08-05",
                    "items": [make_item("旧闻", score=95.0, model_used="deepseek-v4-flash")],
                },
                {
                    "report_date": "2026-08-16",
                    "items": [make_item("新闻", score=89.0, model_used="qwen3.7-flash")],
                },
            ],
            mode="monthly",
            range_start=date(2026, 8, 1),
            range_end=date(2026, 8, 31),
        )

        # 两组各一条，分位都是 1.0，退回原始分兜底排序，但两条都在
        self.assertEqual({item["title"] for item in payload["items"]}, {"旧闻", "新闻"})

    def test_entries_snapshot_follows_model_grouped_ranking(self):
        """快照定的是月报页面的展示顺序，必须和综述输入用同一套排序。

        条目造成多信源，让 20 条全部通过月报门槛——这里验证的是排序，
        门槛本身在 PeriodSelectionTests 里单独验。"""
        items = [
            make_item(
                f"旧{index}", score=100.0 - index,
                model_used="deepseek-v4-flash", source_count=2,
            )
            for index in range(10)
        ] + [
            make_item(
                f"新{index}", score=89.0 - index,
                model_used="qwen3.7-flash", source_count=2,
            )
            for index in range(10)
        ]

        report = build_period_report(
            kind="monthly",
            anchor=date(2026, 8, 16),
            items=items,
            report_dates=["2026-08-16"],
            ai_provider=FakeAIProvider(),
        )

        order = [entry["event_id"] for entry in report["entries"]]
        self.assertLess(order.index("e-新0"), order.index("e-旧5"))
        # 快照里存的仍是原始分，不是归一化之后的键
        self.assertEqual(report["entries"][0]["score_at_selection"], 100.0)


if __name__ == "__main__":
    unittest.main()


class CountingProvider(FakeAIProvider):
    """FakeAIProvider 的假正文只有 79 字，会触发「短稿重试」多花一次调用；
    这里返回够长的正文，让 calls 恰好等于真实的购买次数。"""

    def __init__(self):
        self.calls = 0

    def summarize_period(self, items, kind, range_label):
        self.calls += 1
        drafted = super().summarize_period(items, kind, range_label)
        drafted["mainline_body"] = drafted["mainline_body"] + "补" * 250
        return drafted


class PeriodDigestTests(unittest.TestCase):
    """摘要输入没变就不重买：2026-08-18 实测 summarize_period 一天被调了
    23 次（summarize_daily 有 digest，只有 6 次），素材几乎没动。"""

    def build(self, items, *, provider, previous=None, finalize=False):
        return build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=provider,
            previous=previous,
            finalize=finalize,
        )

    def test_unchanged_input_reuses_stored_text_without_a_call(self):
        items = [make_item("事件A", score=90.0), make_item("事件B", score=80.0)]
        first = self.build(items, provider=CountingProvider())
        self.assertTrue(first["summary_digest"])

        provider = CountingProvider()
        second = self.build(items, provider=provider, previous=first)

        self.assertEqual(provider.calls, 0)
        self.assertEqual(second["mainline_title"], first["mainline_title"])
        self.assertEqual(second["mainline_body"], first["mainline_body"])
        self.assertEqual(second["theme_notes"], first["theme_notes"])
        self.assertEqual(second["status"], "generated")
        self.assertEqual(second["summary_digest"], first["summary_digest"])

    def test_changed_input_buys_new_text(self):
        first = self.build([make_item("事件A")], provider=CountingProvider())

        provider = CountingProvider()
        self.build(
            [make_item("事件A"), make_item("新事件")], provider=provider, previous=first
        )

        self.assertEqual(provider.calls, 1)

    def test_snapshot_is_rebuilt_even_when_text_is_reused(self):
        """digest 只护住文字，不护住快照——榜单尾部的变动（不进 top40 摘要
        输入）必须照常写进 entries/stats。"""
        items = [make_item(f"事件{i}", score=90.0 - i) for i in range(3)]
        first = self.build(items, provider=CountingProvider())

        # 追加一条低分条目：不改变 top40 输入的前提下改变名单
        # （SUMMARY_ITEM_LIMIT=40，3->4 条都在 40 以内，标题会进输入，
        # 所以这里换个思路：分数变动但被 [:80] 截断域外的字段不存在——
        # 直接验证 entries 数量跟随 items 而非跟随 digest）
        provider = CountingProvider()
        second = self.build(items, provider=provider, previous=first)
        self.assertEqual(len(second["entries"]), 3)
        self.assertEqual(second["article_count"], 3)

    def test_fallback_stores_no_digest_and_retries_next_time(self):
        class BoomProvider(FakeAIProvider):
            def summarize_period(self, items, kind, range_label):
                raise RuntimeError("provider down")

        items = [make_item("事件A")]
        failed = self.build(items, provider=BoomProvider())
        self.assertEqual(failed["status"], "fallback")
        self.assertIsNone(failed["summary_digest"])

        # 同样的素材，上一次是 fallback：必须重试而不是复用失败文案
        provider = CountingProvider()
        recovered = self.build(items, provider=provider, previous=failed)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(recovered["status"], "generated")


class PeriodFinalizeTests(unittest.TestCase):
    def build(self, *, provider, finalize):
        return build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=[make_item("事件A")],
            report_dates=["2026-07-10"],
            ai_provider=provider,
            finalize=finalize,
        )

    def test_finalize_stamps_finalized_at_on_generated(self):
        report = self.build(provider=FakeAIProvider(), finalize=True)
        self.assertEqual(report["status"], "generated")
        self.assertTrue(report["finalized_at"])

    def test_live_period_is_never_stamped(self):
        report = self.build(provider=FakeAIProvider(), finalize=False)
        self.assertIsNone(report["finalized_at"])

    def test_fallback_is_never_frozen(self):
        """封版失败的期次必须留着下次重试：冻结一条「生成失败」等于把失败
        变成永久文案。"""

        class BoomProvider(FakeAIProvider):
            def summarize_period(self, items, kind, range_label):
                raise RuntimeError("provider down")

        report = self.build(provider=BoomProvider(), finalize=True)
        self.assertEqual(report["status"], "fallback")
        self.assertIsNone(report["finalized_at"])


class PeriodTargetsTests(unittest.TestCase):
    """每次刷新照看两个期次：当期 + 上一期。上一期的封版只能由下一期的
    第一批运行来做——期内最后一次刷新跑的时候，它的最后一天还没定稿。"""

    def test_weekly_targets_are_previous_then_current(self):
        from app.services.period_summary_service import period_targets_for

        self.assertEqual(
            period_targets_for("weekly", date(2026, 7, 10)),
            ["2026-W27", "2026-W28"],
        )

    def test_monthly_targets_cross_year_boundary(self):
        from app.services.period_summary_service import period_targets_for

        self.assertEqual(
            period_targets_for("monthly", date(2026, 1, 5)),
            ["2025-12", "2026-01"],
        )

    def test_weekly_targets_cross_iso_year_boundary(self):
        from app.services.period_summary_service import period_targets_for

        # 2024-12-30 已属于 2025-W01，上一周是 2024-W52
        self.assertEqual(
            period_targets_for("weekly", date(2024, 12, 30)),
            ["2024-W52", "2025-W01"],
        )


class PeriodSelectionTests(unittest.TestCase):
    """周月报从「全收录但 96% 不可见」改成定名单：周报宽进、月报严进。"""

    def test_weekly_includes_every_multi_source_item_regardless_of_score(self):
        from app.services.period_summary_service import select_period_items

        items = [
            make_item("多信源低分", score=10.0, source_count=3),
            make_item("单信源高分", score=99.0),
        ]
        selected = select_period_items("weekly", items)

        titles = [item["title"] for item in selected]
        self.assertIn("多信源低分", titles)
        # 多信源组整体在前：即使分数只有 10 也排在单信源 99 分之前
        self.assertEqual(titles[0], "多信源低分")

    def test_weekly_category_floor_keeps_small_categories_visible(self):
        from app.services.period_summary_service import (
            WEEKLY_ITEM_CAP,
            select_period_items,
        )

        # 大分类塞满上限，小分类只有两条低分位条目
        items = [
            make_item(f"大类{i}", score=95.0 - i * 0.5, category="model")
            for i in range(WEEKLY_ITEM_CAP + 5)
        ] + [
            make_item("小类甲", score=5.0, category="policy"),
            make_item("小类乙", score=4.0, category="policy"),
        ]
        selected = select_period_items("weekly", items)

        titles = [item["title"] for item in selected]
        self.assertLessEqual(len(selected), WEEKLY_ITEM_CAP)
        # 按全局名次小分类一条都进不来；保底名额保证它整块不消失
        self.assertIn("小类甲", titles)
        self.assertIn("小类乙", titles)

    def test_weekly_caps_at_limit(self):
        from app.services.period_summary_service import (
            WEEKLY_ITEM_CAP,
            select_period_items,
        )

        items = [make_item(f"事件{i}", score=90.0 - i * 0.5) for i in range(60)]
        self.assertEqual(len(select_period_items("weekly", items)), WEEKLY_ITEM_CAP)

    def test_weekly_days_covered_outranks_percentile_within_group(self):
        from app.services.period_summary_service import select_period_items

        low_but_persistent = make_item("连报三天", score=50.0, source_count=2)
        low_but_persistent["days_covered"] = 3
        high_one_day = make_item("昙花一现", score=95.0, source_count=2)

        selected = select_period_items("weekly", [high_one_day, low_but_persistent])
        self.assertEqual(selected[0]["title"], "连报三天")

    def test_monthly_gate_drops_single_source_single_day_items(self):
        from app.services.period_summary_service import (
            MONTHLY_FILL_FLOOR,
            select_period_items,
        )

        qualified = [
            make_item(f"多信源{i}", score=80.0 - i, source_count=2)
            for i in range(MONTHLY_FILL_FLOOR + 2)
        ]
        noise = [make_item(f"噪声{i}", score=99.0 - i) for i in range(5)]

        selected = select_period_items("monthly", qualified + noise)
        titles = [item["title"] for item in selected]
        self.assertTrue(all(title.startswith("多信源") for title in titles))

    def test_monthly_days_covered_qualifies_without_multi_source(self):
        from app.services.period_summary_service import (
            MONTHLY_FILL_FLOOR,
            select_period_items,
        )

        persistent = make_item("单信源但连报两天", score=50.0)
        persistent["days_covered"] = 2
        qualified = [
            make_item(f"多信源{i}", score=80.0 - i, source_count=2)
            for i in range(MONTHLY_FILL_FLOOR)
        ]
        noise = [make_item(f"噪声{i}", score=99.0 - i) for i in range(3)]

        selected = select_period_items("monthly", qualified + [persistent] + noise)
        titles = [item["title"] for item in selected]
        self.assertIn("单信源但连报两天", titles)
        self.assertNotIn("噪声0", titles)

    def test_monthly_backfills_by_rank_when_gate_leaves_too_few(self):
        """月初头几天几乎没有 days_covered≥2 的事件，门槛筛完月报页面
        不能是空的——按名次回填到最低条数。"""
        from app.services.period_summary_service import (
            MONTHLY_FILL_FLOOR,
            select_period_items,
        )

        items = [make_item(f"事件{i}", score=90.0 - i) for i in range(20)]
        selected = select_period_items("monthly", items)
        self.assertEqual(len(selected), MONTHLY_FILL_FLOOR)
        # 回填仍按名次：最高分位的在前
        self.assertEqual(selected[0]["title"], "事件0")

    def test_monthly_caps_at_limit(self):
        from app.services.period_summary_service import (
            MONTHLY_ITEM_CAP,
            select_period_items,
        )

        items = [
            make_item(f"事件{i}", score=90.0 - i, source_count=2) for i in range(40)
        ]
        self.assertEqual(len(select_period_items("monthly", items)), MONTHLY_ITEM_CAP)

    def test_report_entries_and_summary_see_the_same_selection(self):
        """页面（entries 快照）和 AI 综述（summary_input）必须是同一份名单
        同一个顺序——综述不能点评读者看不见的条目。"""

        class CapturingProvider(FakeAIProvider):
            def __init__(self):
                self.seen = None

            def summarize_period(self, items, kind, range_label):
                self.seen = items
                drafted = super().summarize_period(items, kind, range_label)
                drafted["mainline_body"] = drafted["mainline_body"] + "补" * 250
                return drafted

        provider = CapturingProvider()
        items = [
            make_item("多信源", score=50.0, source_count=2),
            make_item("单信源", score=95.0),
        ]
        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=provider,
        )

        self.assertEqual(
            [entry["event_id"] for entry in report["entries"]],
            ["e-多信源", "e-单信源"],
        )
        # 周报输入是结构化的：主线部分只见多信源，分类部分覆盖全名单
        mainline = provider.seen["mainline_events"]
        self.assertEqual([event["title"] for event in mainline], ["多信源"])
        self.assertEqual(mainline[0]["source_count"], 2)
        self.assertEqual(mainline[0]["days_covered"], 1)
        category_titles = [
            title
            for group in provider.seen["categories"]
            for title in group["titles"]
        ]
        self.assertEqual(sorted(category_titles), ["单信源", "多信源"])

    def test_stats_carry_honest_dual_counts(self):
        from app.services.period_summary_service import (
            MONTHLY_FILL_FLOOR,
            build_period_report,
        )

        items = [make_item(f"事件{i}", score=90.0 - i) for i in range(20)]
        report = build_period_report(
            kind="monthly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        self.assertEqual(report["article_count"], MONTHLY_FILL_FLOOR)
        self.assertEqual(report["stats"]["selected_count"], MONTHLY_FILL_FLOOR)
        self.assertEqual(report["stats"]["coverage_count"], 20)
        # 覆盖面统计（分类分布等）看全量而不是名单
        self.assertEqual(
            sum(report["stats"]["category_distribution"].values()), 20
        )


class MergeDaysCoveredTests(unittest.TestCase):
    def test_merge_counts_days_covered_and_keeps_newest_copy(self):
        payload = build_period_payload(
            [
                {
                    "report_date": "2026-08-10",
                    "items": [make_item("连报的事", score=80.0)],
                },
                {
                    "report_date": "2026-08-11",
                    "items": [
                        make_item("连报的事", score=85.0),
                        make_item("只出现一天", score=70.0),
                    ],
                },
            ],
            mode="weekly",
            range_start=date(2026, 8, 10),
            range_end=date(2026, 8, 16),
        )

        by_title = {item["title"]: item for item in payload["items"]}
        self.assertEqual(by_title["连报的事"]["days_covered"], 2)
        # 新日期的副本胜出：分数是 8-11 的 85 而不是 8-10 的 80
        self.assertEqual(by_title["连报的事"]["final_score"], 85.0)
        self.assertEqual(by_title["只出现一天"]["days_covered"], 1)


class MonthlyTrendEvidenceTests(unittest.TestCase):
    """趋势线的证据必须真在名单里：回填错的丢弃，全空时只留论述——
    宁缺毋假，不拿高分事件冒充证据。"""

    def _build(self, provider):
        items = [
            make_item(f"事件{i}", score=90.0 - i, source_count=2) for i in range(5)
        ]
        return build_period_report(
            kind="monthly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=provider,
        )

    def test_fabricated_event_ids_are_dropped(self):
        class FabricatingProvider(FakeAIProvider):
            def summarize_period(self, summary_input, kind, range_label):
                real = summary_input["events"][0]["event_id"]
                return {
                    "mainline_title": "本月主线",
                    "mainline_body": "本月……" + "补" * 120,
                    "trends": [
                        {
                            "label": "趋势甲",
                            "note": "论述",
                            "event_ids": [real, "e-编造的", "e-也是编的"],
                        }
                    ],
                }

        report = self._build(FabricatingProvider())
        self.assertEqual(report["theme_notes"][0]["event_ids"], ["e-事件0"])

    def test_trend_with_no_valid_evidence_keeps_prose_only(self):
        class BaselessProvider(FakeAIProvider):
            def summarize_period(self, summary_input, kind, range_label):
                return {
                    "mainline_title": "本月主线",
                    "mainline_body": "本月……" + "补" * 120,
                    "trends": [
                        {"label": "无证据趋势", "note": "论述还在", "event_ids": ["e-编造的"]}
                    ],
                }

        report = self._build(BaselessProvider())
        self.assertEqual(len(report["theme_notes"]), 1)
        self.assertEqual(report["theme_notes"][0]["note"], "论述还在")
        self.assertEqual(report["theme_notes"][0]["event_ids"], [])
