from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.topics import (
    TOPIC_GROUPS,
    build_topics_payload,
    item_matches_topic,
    topic_by_id,
)


def make_item(**overrides):
    item = {
        "event_id": "e1",
        "title": "OpenAI releases agent model",
        "category": "model",
        "tags": ["Agent"],
        "summary": "",
        "one_line_summary": "",
    }
    item.update(overrides)
    return item


class TopicRegistryTests(unittest.TestCase):
    def test_registry_has_four_discovery_groups_with_reasonable_sizes(self):
        groups = {group["id"]: group for group in TOPIC_GROUPS}

        self.assertEqual(
            list(groups), ["models", "products", "directions", "companies"]
        )
        self.assertGreaterEqual(len(groups["models"]["topics"]), 8)
        self.assertGreaterEqual(len(groups["products"]["topics"]), 8)
        self.assertGreaterEqual(len(groups["directions"]["topics"]), 8)
        self.assertGreaterEqual(len(groups["companies"]["topics"]), 10)
        # every topic id is unique across groups
        all_ids = [t["id"] for g in TOPIC_GROUPS for t in g["topics"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_title_and_tag_keywords_match_company_topics(self):
        openai = topic_by_id("openai")
        anthropic = topic_by_id("anthropic")

        self.assertTrue(item_matches_topic(make_item(), openai))
        self.assertFalse(item_matches_topic(make_item(), anthropic))
        self.assertTrue(
            item_matches_topic(
                make_item(title="新模型发布", tags=["Claude"]), anthropic
            )
        )

    def test_ascii_keywords_require_word_boundaries(self):
        meta = topic_by_id("meta")

        self.assertTrue(item_matches_topic(make_item(title="Meta ships Llama 5"), meta))
        # "metadata" must not match the Meta topic
        self.assertFalse(
            item_matches_topic(make_item(title="New metadata standard for RSS"), meta)
        )

    def test_chinese_keywords_match_by_substring(self):
        multimodal = topic_by_id("multimodal")

        self.assertTrue(
            item_matches_topic(make_item(summary="该模型支持多模态输入。"), multimodal)
        )

    def test_product_topic_matches_product_name(self):
        claude_code = topic_by_id("claude_code")

        self.assertTrue(
            item_matches_topic(make_item(title="Claude Code adds hooks"), claude_code)
        )
        self.assertFalse(
            item_matches_topic(make_item(title="Claude model evaluation"), claude_code)
        )


class TopicsPayloadTests(unittest.TestCase):
    def test_payload_groups_topics_with_counts(self):
        items = [
            make_item(event_id="e1", title="OpenAI releases agent model", tags=["Agent"]),
            make_item(event_id="e2", title="Claude 5 launches", tags=[]),
            make_item(event_id="e3", title="随便", category="research"),
        ]

        payload = build_topics_payload(items)

        self.assertEqual(
            [g["id"] for g in payload["groups"]],
            ["models", "products", "directions", "companies"],
        )
        companies = payload["groups"][3]
        by_id = {t["id"]: t for t in companies["topics"]}
        self.assertEqual(by_id["openai"]["count"], 1)
        self.assertEqual(by_id["anthropic"]["count"], 1)
        self.assertEqual(by_id["openai"]["name"], "OpenAI")
        self.assertEqual(payload["article_count"], 3)


if __name__ == "__main__":
    unittest.main()
