from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from datetime import datetime, timezone

from app.services.topics import (
    TOPIC_GROUPS,
    build_topic_detail_payload,
    build_topics_payload,
    derive_topic_ids,
    group_of_topic,
    item_matches_topic,
    normalize_topic_ids,
    shape_storylines,
    topic_by_id,
)

TODAY = date(2026, 8, 20)


def make_item(**overrides):
    item = {
        "event_id": "e1",
        "title": "OpenAI releases agent model",
        "category": "model",
        "tags": ["Agent"],
        "summary": "",
        "one_line_summary": "",
        "selected": True,
        "is_main": True,
        "source_count": 1,
        "published_at": "2026-08-19T06:00:00+00:00",
    }
    item.update(overrides)
    return item


class TopicRegistryTests(unittest.TestCase):
    def test_registry_has_two_groups_entities_and_directions(self):
        groups = {group["id"]: group for group in TOPIC_GROUPS}

        self.assertEqual(list(groups), ["entities", "directions"])
        self.assertGreaterEqual(len(groups["entities"]["topics"]), 15)
        self.assertGreaterEqual(len(groups["directions"]["topics"]), 8)
        # every topic id is unique across groups
        all_ids = [t["id"] for g in TOPIC_GROUPS for t in g["topics"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        # 每个主题都要有编辑描述——索引页卡片靠它回答"为什么值得关注"
        for group in TOPIC_GROUPS:
            for topic in group["topics"]:
                self.assertTrue(topic["description"], f"{topic['id']} 缺描述")

    def test_entity_topics_merge_company_and_model_keywords(self):
        anthropic = topic_by_id("anthropic")

        # 公司名、模型名都归到同一张实体卡
        self.assertTrue(item_matches_topic(make_item(title="Anthropic 完成新一轮融资"), anthropic))
        self.assertTrue(item_matches_topic(make_item(title="Claude 5 发布"), anthropic))
        self.assertFalse(item_matches_topic(make_item(title="Gemini 3 上线"), anthropic))

    def test_legacy_four_group_ids_redirect_to_merged_topics(self):
        # 旧 /all?topic= 链接可能被外部收藏,四组时代的 id 不能静默失效
        self.assertEqual(topic_by_id("claude")["id"], "anthropic")
        self.assertEqual(topic_by_id("gpt")["id"], "openai")
        self.assertEqual(topic_by_id("claude_code")["id"], "anthropic")
        self.assertEqual(topic_by_id("robotics")["id"], "embodied")
        self.assertIsNone(topic_by_id("cn_models"))
        self.assertEqual(group_of_topic("claude")["id"], "entities")

    def test_ascii_keywords_require_word_boundaries(self):
        meta = topic_by_id("meta")

        self.assertTrue(item_matches_topic(make_item(title="Meta ships Llama 5"), meta))
        # "metadata" must not match the Meta topic
        self.assertFalse(
            item_matches_topic(make_item(title="New metadata standard for RSS"), meta)
        )

    def test_summary_mentions_no_longer_count_as_membership(self):
        # 匹配语义是"关于 X"不是"提到过 X":全文摘要里顺嘴一句不算
        anthropic = topic_by_id("anthropic")

        self.assertFalse(
            item_matches_topic(
                make_item(title="OpenAI 发布新模型", summary="评测中顺带对比了 Claude。"),
                anthropic,
            )
        )
        # 一句话提要仍参与匹配——它承载"这条主要在讲什么"
        self.assertTrue(
            item_matches_topic(
                make_item(title="新模型发布", one_line_summary="Claude 5 上线"), anthropic
            )
        )


class TopicIdsAuthorityTests(unittest.TestCase):
    def test_stored_topic_ids_win_over_keywords(self):
        anthropic = topic_by_id("anthropic")

        # 标题明明写着 Claude,但入库判定说它不属于任何主题 → 尊重入库判定
        self.assertFalse(
            item_matches_topic(make_item(title="Claude 5 发布", topic_ids=[]), anthropic)
        )
        # 标题没有关键词,但入库判定归给 anthropic → 命中
        self.assertTrue(
            item_matches_topic(
                make_item(title="某实验室发布新模型", topic_ids=["anthropic"]), anthropic
            )
        )
        # None(未回填的存量行)回退关键词
        self.assertTrue(
            item_matches_topic(make_item(title="Claude 5 发布", topic_ids=None), anthropic)
        )

    def test_derive_topic_ids_uses_keywords_in_registry_order(self):
        derived = derive_topic_ids(
            make_item(title="Anthropic 发布 Claude Agent 框架", tags=["Agent"])
        )

        self.assertIn("anthropic", derived)
        self.assertIn("agents", derived)
        self.assertNotIn("openai", derived)

    def test_normalize_topic_ids_resolves_aliases_and_drops_unknown(self):
        # 别名解析 + 未知丢弃 + 去重保序;空列表原样保留;非列表 → None
        self.assertEqual(
            normalize_topic_ids(["claude", "anthropic", "nope", "AGENTS"]),
            ["anthropic", "agents"],
        )
        self.assertEqual(normalize_topic_ids([]), [])
        self.assertIsNone(normalize_topic_ids("anthropic"))
        self.assertIsNone(normalize_topic_ids(None))


class StorylineShapingTests(unittest.TestCase):
    def _cluster(self, event_id, sources, first, last, title="事件"):
        return {
            "event_id": event_id,
            "title": title,
            "source_count": sources,
            "first_seen_at": datetime.fromisoformat(first).replace(tzinfo=timezone.utc),
            "last_seen_at": datetime.fromisoformat(last).replace(tzinfo=timezone.utc),
        }

    def test_requires_multi_day_span_and_sorts_by_heat(self):
        clusters = [
            # 同一天多源(上海 09:00→18:00)→ 不是故事线,是单日热点
            self._cluster("same-day", 5, "2026-08-19T01:00:00", "2026-08-19T10:00:00"),
            self._cluster("hot", 6, "2026-08-17T01:00:00", "2026-08-19T01:00:00"),
            self._cluster("long", 3, "2026-08-10T01:00:00", "2026-08-19T01:00:00"),
            self._cluster("small", 2, "2026-08-18T01:00:00", "2026-08-19T01:00:00"),
        ]

        shaped = shape_storylines(clusters)

        self.assertEqual([s["event_id"] for s in shaped], ["hot", "long", "small"])
        self.assertEqual(shaped[0]["days"], 3)
        self.assertEqual(shaped[0]["source_count"], 6)
        self.assertEqual(shaped[1]["days"], 10)

    def test_span_uses_shanghai_calendar_days(self):
        # UTC 16:00 = 上海次日 00:00:UTC 看是同一天,上海已跨天 → 算故事线
        clusters = [
            self._cluster("cross", 2, "2026-08-19T01:00:00", "2026-08-19T17:00:00"),
        ]

        shaped = shape_storylines(clusters)

        self.assertEqual([s["event_id"] for s in shaped], ["cross"])
        self.assertEqual(shaped[0]["days"], 2)

    def test_caps_at_limit(self):
        clusters = [
            self._cluster(f"e{n}", 2 + n, "2026-08-17T01:00:00", "2026-08-19T01:00:00")
            for n in range(8)
        ]

        shaped = shape_storylines(clusters)

        self.assertEqual(len(shaped), 5)
        # 信源多的排前面
        self.assertEqual(shaped[0]["event_id"], "e7")


class TopicsPayloadTests(unittest.TestCase):
    def test_payload_counts_selected_only_with_week_windows(self):
        items = [
            make_item(event_id="e1", title="Claude 5 launches", published_at="2026-08-19T06:00:00+00:00"),
            make_item(event_id="e2", title="Claude Code adds hooks", published_at="2026-08-10T06:00:00+00:00"),
            make_item(event_id="e3", title="Claude rumor", selected=False),
            make_item(event_id="e4", title="随便一条", tags=[]),
        ]

        payload = build_topics_payload(items, today=TODAY)

        self.assertEqual([g["id"] for g in payload["groups"]], ["entities", "directions"])
        entities = {t["id"]: t for t in payload["groups"][0]["topics"]}
        anthropic = entities["anthropic"]
        self.assertEqual(anthropic["count"], 2)
        self.assertEqual(anthropic["week_count"], 1)  # 8-19 落在近 7 天窗口
        self.assertEqual(anthropic["prev_week_count"], 1)  # 8-10 落在上一个 7 天窗口
        self.assertEqual(anthropic["latest_published_at"], "2026-08-19")
        # article_count 是精选口径
        self.assertEqual(payload["article_count"], 3)


class TopicDetailPayloadTests(unittest.TestCase):
    def test_detail_separates_archive_counts_from_selected_timeline(self):
        items = [
            make_item(event_id="e1", title="Claude 5 launches"),
            make_item(event_id="e2", title="Claude rumor", selected=False),
            make_item(event_id="e3", title="OpenAI news"),
        ]

        payload = build_topic_detail_payload("anthropic", items, today=TODAY)

        self.assertEqual(payload["topic"]["name"], "Anthropic / Claude")
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual([i["event_id"] for i in payload["items"]], ["e1"])

    def test_detail_focus_requires_recent_multi_source_main_items(self):
        items = [
            # 多源、近 14 天、代表条 → 进焦点
            make_item(event_id="hot", title="Claude 5 launches", source_count=4),
            # 单源 → 不进焦点
            make_item(event_id="single", title="Claude tips", published_at="2026-08-18T06:00:00+00:00"),
            # 多源但超出 14 天窗口 → 不进焦点
            make_item(
                event_id="old",
                title="Claude 4.5 recap",
                source_count=3,
                published_at="2026-07-20T06:00:00+00:00",
            ),
            # 多源但不是事件代表条 → 不进焦点(避免同一事件刷屏)
            make_item(
                event_id="member",
                title="Claude 5 独家解读",
                source_count=4,
                is_main=False,
            ),
        ]

        payload = build_topic_detail_payload("anthropic", items, today=TODAY)

        self.assertEqual([i["event_id"] for i in payload["focus"]], ["hot"])

    def test_detail_paginates_selected_timeline(self):
        items = [
            make_item(
                event_id=f"e{n}",
                title=f"Claude update {n}",
                published_at=f"2026-08-{10 + n:02d}T06:00:00+00:00",
            )
            for n in range(1, 6)
        ]

        payload = build_topic_detail_payload("anthropic", items, today=TODAY, limit=2, offset=2)

        self.assertEqual(payload["selected_count"], 5)
        # 时间线按发布时间倒序:全序列 e5..e1,offset=2 取 e3、e2
        self.assertEqual([i["event_id"] for i in payload["items"]], ["e3", "e2"])

    def test_detail_returns_none_for_unknown_topic(self):
        self.assertIsNone(build_topic_detail_payload("nope", [], today=TODAY))


if __name__ == "__main__":
    unittest.main()
