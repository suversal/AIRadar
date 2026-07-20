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
    OpenAIProvider,
    parse_chat_json,
    parse_prefilter_payload,
    parse_scoring_payload,
    prefilter_system_prompt,
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


class ScoringPromptTests(unittest.TestCase):
    def test_scoring_system_prompt_constrains_category_enum_and_tags(self):
        from app.services.ai_service import scoring_system_prompt

        prompt = scoring_system_prompt()

        for category in [
            "model_release",
            "product_release",
            "open_source",
            "research",
            "industry",
            "funding",
            "opinion",
            "tutorial",
        ]:
            self.assertIn(category, prompt)
        # controlled tag vocabulary guidance
        self.assertIn("Agent", prompt)
        self.assertIn("多模态", prompt)
        self.assertIn("strict JSON", prompt)

    def test_scoring_system_prompt_enforces_reason_and_summary_quality(self):
        # 用户规格（2026-07-11）：推荐理由与核心摘要必须有字数区间、结构
        # 要求、禁语清单和"不得编造"约束——之前的提示词对这两个字段
        # 没有任何要求，产出普遍是套话
        from app.services.ai_service import scoring_system_prompt

        prompt = scoring_system_prompt()

        # reason_zh：字数区间 + 禁止套话 + 不复述摘要
        self.assertIn("60", prompt)
        self.assertIn("100", prompt)
        self.assertIn("值得关注", prompt)  # 作为被点名禁止的套话出现
        self.assertIn("可能产生深远影响", prompt)
        self.assertIn("对开发者有价值", prompt)
        # summary_zh：字数区间 + 组织结构 + 事实边界
        self.assertIn("180", prompt)
        self.assertIn("260", prompt)
        self.assertIn("核心事件", prompt)
        self.assertIn("关键细节", prompt)
        self.assertIn("限制", prompt)
        # 共同底线：不得补写原文没有的内容
        self.assertTrue("编造" in prompt or "补写" in prompt)

    def test_scoring_system_prompt_constrains_title_accuracy(self):
        # 用户反馈（2026-07-14）：标题不准确——之前的提示词对 title_zh
        # 没有任何事实性约束，只给了个 "中文标题" 的 schema 提示
        from app.services.ai_service import scoring_system_prompt

        prompt = scoring_system_prompt()

        self.assertIn("title_zh", prompt)
        self.assertIn("12", prompt)
        self.assertIn("30", prompt)
        self.assertIn("忠实于原文标题与正文事实", prompt)
        self.assertIn("公司、产品或模型名称", prompt)
        # 禁止编造 + 禁止夸张渲染词，双重约束准确性
        self.assertIn("禁止编造", prompt)
        self.assertIn("震惊", prompt)
        self.assertIn("重磅", prompt)

    def test_scoring_system_prompt_includes_dimension_rubric_anchors(self):
        # 2026-07-20 诊断：六维评分此前完全没有 0-10 分锚点，模型只能凭感觉打
        # 分——这里锁定每个维度都带有具体的分档说明，防止回归成裸的字段名列表
        from app.services.ai_service import scoring_system_prompt

        prompt = scoring_system_prompt()

        for dimension_keyword in (
            "ai_relevance",
            "novelty",
            "impact",
            "information_density",
            "actionability",
            "creator_value",
        ):
            self.assertIn(dimension_keyword, prompt)
        # 具体锚点用词，确保不是只列了维度名而没有分档标准
        self.assertIn("刷新SOTA", prompt)
        self.assertIn("增量迭代", prompt)
        self.assertIn("benchmark", prompt)
        self.assertIn("不得因为想输出", prompt)  # 信息不足时不得编造高分

    def test_scoring_system_prompt_includes_category_boundary_examples(self):
        # 2026-07-20 诊断：8 个分类之前只是裸的英文枚举，model_release/
        # product_release/open_source 和 industry/funding/opinion 高度重叠，
        # 这里锁定边界规则与 few-shot 示例文本存在
        from app.services.ai_service import scoring_system_prompt

        prompt = scoring_system_prompt()

        self.assertIn("边界示例", prompt)
        self.assertIn("强调开源属性", prompt)
        self.assertIn("具体金额和轮次", prompt)
        self.assertIn("主观判断和预测", prompt)

    def test_deepseek_scoring_uses_shared_system_prompt(self):
        from app.services.ai_service import scoring_system_prompt

        provider = DeepSeekProvider(api_key="test-key")
        captured: dict = {}

        def fake_post(url, payload):
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "dimensions": {
                                        "ai_relevance": 9,
                                        "novelty": 8,
                                        "impact": 8,
                                        "information_density": 7,
                                        "actionability": 7,
                                        "creator_value": 6,
                                    },
                                    "category": "model_release",
                                    "tags": ["Agent"],
                                    "title_zh": "标题",
                                    "one_line_summary": "摘要",
                                    "summary_zh": "核心",
                                    "reason_zh": "理由",
                                    "action_zh": "动作",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        with patch.object(provider, "_post_json", side_effect=fake_post):
            provider.score_article("t", "c")

        system_message = captured["payload"]["messages"][0]["content"]
        self.assertEqual(system_message, scoring_system_prompt())
        self.assertEqual(captured["payload"]["temperature"], 0.2)


class PrefilterPromptTests(unittest.TestCase):
    def test_prefilter_system_prompt_uses_core_topic_principle(self):
        # 2026-07-20 用户反馈：汽车行业等"提及AI但核心不是AI"的文章被误判为
        # 相关。修复原则是"核心主题优先于关键词命中"，而不是逐行业列举反例
        prompt = prefilter_system_prompt()

        self.assertIn("is_ai_related", prompt)
        self.assertIn("核心主题", prompt)
        self.assertIn("主体事件", prompt)
        self.assertIn("去掉AI相关的字眼", prompt)

    def test_all_providers_share_the_same_prefilter_prompt(self):
        # 三个 provider 曾经各自内联同一段英文字符串，容易改一份漏改另外两
        # 份；这里锁定它们都调用同一个共享函数
        openai_provider = OpenAIProvider(api_key="test-key")
        kimi_provider = KimiProvider("test-key")
        deepseek_provider = DeepSeekProvider("test-key")

        for provider, url in (
            (openai_provider, "https://api.openai.com/v1/chat/completions"),
            (kimi_provider, "https://api.moonshot.cn/v1/chat/completions"),
            (deepseek_provider, "https://api.deepseek.com/chat/completions"),
        ):
            captured: dict = {}

            def fake_post(_url, payload, _captured=captured):
                _captured["payload"] = payload
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "is_ai_related": True,
                                        "confidence": 0.9,
                                        "reason": "AI 相关",
                                    }
                                )
                            }
                        }
                    ]
                }

            with patch.object(provider, "_post_json", side_effect=fake_post):
                provider.prefilter("some AI text")

            system_message = captured["payload"]["messages"][0]["content"]
            self.assertEqual(system_message, prefilter_system_prompt())
            self.assertEqual(captured["payload"]["temperature"], 0.2)


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

    def test_parse_scoring_payload_logs_warning_for_off_enum_category(self):
        # 2026-07-20 诊断：模型偶尔吐出枚举外的 category（如
        # "research_insight"），此前完全静默走兜底，无法追溯。这里只要求可
        # 观测（记日志），不要求抛异常——保持现有兜底健壮性不变
        base_payload = {
            "dimensions": {
                "ai_relevance": 8,
                "novelty": 7,
                "impact": 7,
                "information_density": 7,
                "actionability": 6,
                "creator_value": 6,
            },
            "category": "research_insight",
            "tags": ["Research"],
            "title_zh": "某研究新发现",
            "one_line_summary": "一句话",
            "summary_zh": "摘要",
            "reason_zh": "理由",
            "action_zh": "阅读原文",
        }

        with self.assertLogs("app.services.ai_service", level="WARNING") as ctx:
            parsed = parse_scoring_payload(base_payload)

        self.assertEqual(parsed.category, "research_insight")  # 兜底行为不变
        self.assertTrue(any("research_insight" in message for message in ctx.output))

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
        self.assertEqual(calls[0][1]["temperature"], 0.2)

    def test_kimi_provider_uses_local_real_embedding_model(self):
        provider = KimiProvider("test-key")

        self.assertEqual(provider.embed_text("same text"), provider.embed_text("same text"))
        # real bge-small-zh embeddings are fixed at 512 dims; the dimensions
        # param no longer reshapes output the way the old hash fallback did
        self.assertEqual(len(provider.embed_text("same text")), 512)

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
        self.assertEqual(calls[0][1]["max_tokens"], 4096)
        self.assertEqual(calls[0][1]["temperature"], 0.2)

    def test_deepseek_scoring_retries_a_truncated_json_response(self):
        provider = DeepSeekProvider("test-key", max_tokens=2048)
        calls = []
        valid = {
            "dimensions": {
                "ai_relevance": 9,
                "novelty": 8,
                "impact": 7,
                "information_density": 8,
                "actionability": 7,
                "creator_value": 6,
            },
            "category": "tutorial",
            "tags": ["开源"],
            "title_zh": "完整标题",
            "one_line_summary": "一句话摘要",
            "summary_zh": "完整摘要",
            "reason_zh": "推荐理由",
            "action_zh": "下一步动作",
        }

        def fake_post_json(_url, payload):
            calls.append(payload)
            if len(calls) == 1:
                return {
                    "choices": [{
                        "finish_reason": "length",
                        "message": {"content": '{"dimensions":{"ai_relevance":0},"tags":["开源'},
                    }]
                }
            return {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(valid, ensure_ascii=False)},
                }]
            }

        provider._post_json = fake_post_json

        result = provider.score_article("标题", "正文")

        self.assertEqual(result.title_zh, "完整标题")
        self.assertEqual([call["max_tokens"] for call in calls], [4096, 8192])
        self.assertIn("Do not include reasoning", calls[1]["messages"][0]["content"])

    def test_deepseek_provider_uses_local_real_embedding_model(self):
        provider = DeepSeekProvider("test-key")

        self.assertEqual(provider.embed_text("same text"), provider.embed_text("same text"))
        # real bge-small-zh embeddings are fixed at 512 dims; the dimensions
        # param no longer reshapes output the way the old hash fallback did
        self.assertEqual(len(provider.embed_text("same text")), 512)

    def test_fake_provider_embeddings_match_vector_column_width(self):
        # --fake-ai --persist-db 必须与 article_embeddings 的 vector(512)
        # 列兼容，否则本地端到端验证无法写库
        self.assertEqual(len(FakeAIProvider().embed_text("any text")), 512)

    def test_composite_providers_expose_embedding_model_name(self):
        # article_embeddings.embedding_model 落库时取自 provider；组合 provider
        # （远程 chat + 本地 bge 向量）必须报告真实向量模型名而非 "unknown"
        from app.pipeline.runner import _embedding_model_name

        for provider in (KimiProvider("test-key"), DeepSeekProvider("test-key")):
            self.assertEqual(_embedding_model_name(provider), "BAAI/bge-small-zh-v1.5")
        self.assertEqual(_embedding_model_name(FakeAIProvider()), "fake-embedding")

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
