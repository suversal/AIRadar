import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.ai_service import (
    DeepSeekProvider,
    FakeAIProvider,
    KimiProvider,
    parse_chat_json,
    parse_prefilter_payload,
    parse_scoring_payload,
    provider_from_env,
)


class ParseChatJsonTests(unittest.TestCase):
    def test_parses_plain_json_object(self):
        self.assertEqual(parse_chat_json('{"a": 1}'), {"a": 1})

    def test_parses_json_wrapped_in_markdown_fences(self):
        content = '```json\n{"is_ai_related": true, "confidence": 0.9}\n```'
        self.assertEqual(
            parse_chat_json(content),
            {"is_ai_related": True, "confidence": 0.9},
        )

    def test_parses_json_with_leading_and_trailing_prose(self):
        content = 'Here is the result:\n{"score": 8}\nHope this helps!'
        self.assertEqual(parse_chat_json(content), {"score": 8})

    def test_raises_value_error_with_snippet_for_garbage(self):
        with self.assertRaises(ValueError) as ctx:
            parse_chat_json("I cannot answer that.")
        self.assertIn("I cannot answer", str(ctx.exception))

    def test_raises_value_error_for_empty_content(self):
        with self.assertRaises(ValueError):
            parse_chat_json("")


class AIProviderTests(unittest.TestCase):
    def test_parse_prefilter_payload_rejects_missing_required_fields(self):
        with self.assertRaises(ValueError):
            parse_prefilter_payload({"is_ai_related": True})

    def test_parse_prefilter_payload_handles_non_numeric_confidence(self):
        parsed = parse_prefilter_payload(
            {
                "is_ai_related": True,
                "confidence": "high",
                "reason": "明显是 AI 相关内容。",
            }
        )

        self.assertTrue(parsed.is_ai_related)
        self.assertEqual(parsed.confidence, 0.0)

    def test_parse_scoring_payload_clamps_dimension_scores(self):
        parsed = parse_scoring_payload(
            {
                "dimensions": {
                    "ai_relevance": 12,
                    "novelty": -1,
                    "impact": 7,
                    "information_density": 8,
                    "actionability": 6,
                    "creator_value": 5,
                },
                "category": "model_release",
                "tags": ["Agent", "OpenAI"],
                "title_zh": "模型发布",
                "one_line_summary": "一句话",
                "summary_zh": "摘要",
                "reason_zh": "理由",
                "action_zh": "阅读原文",
            }
        )

        self.assertEqual(parsed.dimensions.ai_relevance, 10)
        self.assertEqual(parsed.dimensions.novelty, 0)

    def test_fake_provider_marks_ai_content_related_and_embeds_deterministically(self):
        provider = FakeAIProvider()

        self.assertTrue(provider.prefilter("OpenAI releases a new agent model").is_ai_related)
        self.assertEqual(
            provider.embed_text("same text"),
            provider.embed_text("same text"),
        )

    def test_kimi_provider_scores_article_via_json_chat_completion(self):
        provider = KimiProvider("test-key")
        calls = []

        def fake_post_json(url, payload):
            calls.append((url, payload))
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "dimensions": {
                                        "ai_relevance": 9,
                                        "novelty": 8,
                                        "impact": 7,
                                        "information_density": 8,
                                        "actionability": 7,
                                        "creator_value": 6,
                                    },
                                    "category": "agent_tooling",
                                    "tags": ["Agent", "Kimi"],
                                    "title_zh": "Kimi 生成 AI 摘要",
                                    "one_line_summary": "Kimi 为 AI Radar 生成中文摘要。",
                                    "summary_zh": "Kimi 根据原文输出结构化中文摘要。",
                                    "reason_zh": "这能验证真实 AI 总结链路。",
                                    "action_zh": "用小批量数据检查摘要质量。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        provider._post_json = fake_post_json

        result = provider.score_article("Kimi summary test", "Kimi summarizes one AI article.")

        self.assertEqual(result.title_zh, "Kimi 生成 AI 摘要")
        self.assertEqual(calls[0][0], "https://api.moonshot.cn/v1/chat/completions")
        self.assertEqual(calls[0][1]["model"], "kimi-k2.7-code")
        self.assertEqual(calls[0][1]["response_format"], {"type": "json_object"})

    def test_kimi_provider_uses_local_deterministic_embedding_fallback(self):
        provider = KimiProvider("test-key")

        self.assertEqual(provider.embed_text("same text"), provider.embed_text("same text"))
        self.assertEqual(len(provider.embed_text("same text", dimensions=16)), 16)

    def test_deepseek_provider_scores_article_via_openai_compatible_chat_completion(self):
        provider = DeepSeekProvider("test-key", user_id="ai-radar-test", max_tokens=1234)
        calls = []

        def fake_post_json(url, payload):
            calls.append((url, payload))
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "dimensions": {
                                        "ai_relevance": 9,
                                        "novelty": 8,
                                        "impact": 7,
                                        "information_density": 8,
                                        "actionability": 7,
                                        "creator_value": 6,
                                    },
                                    "category": "agent_tooling",
                                    "tags": ["Agent", "DeepSeek"],
                                    "title_zh": "DeepSeek 生成 AI 摘要",
                                    "one_line_summary": "DeepSeek 为 AI Radar 生成中文摘要。",
                                    "summary_zh": "DeepSeek 根据原文输出结构化中文摘要。",
                                    "reason_zh": "这能验证真实 AI 总结链路。",
                                    "action_zh": "用小批量数据检查摘要质量。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        provider._post_json = fake_post_json

        result = provider.score_article("DeepSeek summary test", "DeepSeek summarizes one AI article.")

        self.assertEqual(result.title_zh, "DeepSeek 生成 AI 摘要")
        self.assertEqual(calls[0][0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(calls[0][1]["model"], "deepseek-v4-flash")
        self.assertEqual(calls[0][1]["response_format"], {"type": "json_object"})
        self.assertEqual(calls[0][1]["user_id"], "ai-radar-test")
        self.assertEqual(calls[0][1]["max_tokens"], 1234)

    def test_deepseek_provider_uses_local_deterministic_embedding_fallback(self):
        provider = DeepSeekProvider("test-key")

        self.assertEqual(provider.embed_text("same text"), provider.embed_text("same text"))
        self.assertEqual(len(provider.embed_text("same text", dimensions=16)), 16)

    def test_provider_from_env_selects_kimi_without_committing_secrets(self):
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "kimi",
                "MOONSHOT_API_KEY": "test-key",
                "KIMI_MODEL": "kimi-test",
                "KIMI_BASE_URL": "https://example.test/v1",
            },
            clear=True,
        ):
            provider = provider_from_env()

        self.assertIsInstance(provider, KimiProvider)
        self.assertEqual(provider.model, "kimi-test")
        self.assertEqual(provider.base_url, "https://example.test/v1")

    def test_provider_from_env_selects_deepseek_without_committing_secrets(self):
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-test",
                "DEEPSEEK_BASE_URL": "https://example.test",
                "DEEPSEEK_USER_ID": "ai-radar-test",
                "DEEPSEEK_MAX_TOKENS": "1024",
            },
            clear=True,
        ):
            provider = provider_from_env()

        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.model, "deepseek-test")
        self.assertEqual(provider.base_url, "https://example.test")
        self.assertEqual(provider.user_id, "ai-radar-test")
        self.assertEqual(provider.max_tokens, 1024)

    def test_provider_from_env_uses_official_moonshot_base_url_by_default(self):
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "kimi",
                "MOONSHOT_API_KEY": "test-key",
            },
            clear=True,
        ):
            provider = provider_from_env()

        self.assertIsInstance(provider, KimiProvider)
        self.assertEqual(provider.base_url, "https://api.moonshot.cn/v1")

    def test_provider_from_env_uses_official_deepseek_defaults(self):
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "test-key",
            },
            clear=True,
        ):
            provider = provider_from_env()

        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.model, "deepseek-v4-flash")
        self.assertEqual(provider.base_url, "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()
