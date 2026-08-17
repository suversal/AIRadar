import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.ai_service import (
    AIUsage,
    DeepSeekProvider,
    FakeAIProvider,
    KimiProvider,
    OpenAIProvider,
    QwenProvider,
    UsageCollector,
    embedding_input,
    scoring_system_prompt,
    usage_from_response,
    parse_event_match_payload,
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
        for focus in ["model", "product", "technology", "industry"]:
            self.assertIn(focus, prompt)
        self.assertIn("focus_category", prompt)

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
        # 2026-07-28 重构：ai_relevance 不再是六维加权里的一个分量，改为独立
        # 的三态 ai_focus 分类层(primary/contributing/tangential)；剩余的
        # information_density/actionability/creator_value 三个重叠维度合并
        # 为 substance。这里锁定新的字段名和分档锚点仍然带有具体说明，防止
        # 回归成裸的字段名列表
        from app.services.ai_service import scoring_system_prompt

        prompt = scoring_system_prompt()

        for keyword in ("primary", "contributing", "tangential"):
            self.assertIn(keyword, prompt)
        for dimension_keyword in ("impact", "novelty", "substance"):
            self.assertIn(dimension_keyword, prompt)
        # 具体锚点用词，确保不是只列了维度名而没有分档标准
        self.assertIn("刷新SOTA", prompt)
        self.assertIn("增量迭代", prompt)
        self.assertIn("benchmark", prompt)
        self.assertIn("不得因为想输出", prompt)  # 信息不足时不得编造高分
        # 车企OTA反例是这次重构直接命中的误判案例，必须锁定在rubric里
        self.assertIn("智驾", prompt)
        self.assertIn("OTA", prompt)

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

        def fake_post(url, payload, **_kwargs):
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "ai_focus": "primary",
                                    "dimensions": {
                                        "impact": 8,
                                        "novelty": 8,
                                        "substance": 7,
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

            def fake_post(_url, payload, _captured=captured, **_kwargs):
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
    def test_event_match_payload_fails_closed_below_confidence_threshold(self):
        decision = parse_event_match_payload(
            {
                "same_event": True,
                "confidence": 0.79,
                "reason": "主题相似，但具体动作证据不足。",
            }
        )

        self.assertFalse(decision.confirmed)

    def test_event_match_payload_requires_real_boolean(self):
        with self.assertRaises(ValueError):
            parse_event_match_payload(
                {
                    "same_event": "false",
                    "confidence": 0.99,
                    "reason": "不是同一事件。",
                }
            )

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
                "ai_focus": "primary",
                "dimensions": {
                    "impact": 12,
                    "novelty": -1,
                    "substance": 7,
                },
                "category": "model_release",
                "focus_category": "model",
                "tags": ["Agent", "OpenAI"],
                "title_zh": "模型发布",
                "one_line_summary": "一句话",
                "summary_zh": "摘要",
                "reason_zh": "理由",
                "action_zh": "阅读原文",
            }
        )

        self.assertEqual(parsed.ai_focus, "primary")
        self.assertEqual(parsed.dimensions.impact, 10)
        self.assertEqual(parsed.dimensions.novelty, 0)
        self.assertEqual(parsed.focus_category, "model")

    def test_parse_scoring_payload_rejects_invalid_ai_focus(self):
        with self.assertRaises(ValueError):
            parse_scoring_payload(
                {
                    "ai_focus": "somewhat_related",
                    "dimensions": {"impact": 5, "novelty": 5, "substance": 5},
                    "category": "industry",
                    "tags": [],
                    "title_zh": "标题",
                    "one_line_summary": "摘要",
                    "summary_zh": "摘要",
                    "reason_zh": "理由",
                    "action_zh": "行动",
                }
            )

    def test_parse_scoring_payload_logs_warning_for_off_enum_category(self):
        # 2026-07-20 诊断：模型偶尔吐出枚举外的 category（如
        # "research_insight"），此前完全静默走兜底，无法追溯。这里只要求可
        # 观测（记日志），不要求抛异常——保持现有兜底健壮性不变
        base_payload = {
            "ai_focus": "primary",
            "dimensions": {
                "impact": 7,
                "novelty": 7,
                "substance": 7,
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

        def fake_post_json(url, payload, **_kwargs):
            calls.append((url, payload))
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "ai_focus": "primary",
                                    "dimensions": {
                                        "impact": 7,
                                        "novelty": 8,
                                        "substance": 8,
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

        def fake_post_json(url, payload, **_kwargs):
            calls.append((url, payload))
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "ai_focus": "primary",
                                    "dimensions": {
                                        "impact": 7,
                                        "novelty": 8,
                                        "substance": 8,
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
            "ai_focus": "primary",
            "dimensions": {
                "impact": 7,
                "novelty": 8,
                "substance": 8,
            },
            "category": "tutorial",
            "tags": ["开源"],
            "title_zh": "完整标题",
            "one_line_summary": "一句话摘要",
            "summary_zh": "完整摘要",
            "reason_zh": "推荐理由",
            "action_zh": "下一步动作",
        }

        def fake_post_json(_url, payload, **_kwargs):
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


class EmbeddingInputTests(unittest.TestCase):
    def test_embedding_input_repeats_title_to_weight_it_over_content(self):
        # short wire-style articles can open with a near-identical dateline/
        # attribution sentence when the same spokesperson covers two
        # different topics on the same day - that boilerplate must not
        # dominate a short article's embedding over the (usually more
        # distinguishing) title
        result = embedding_input("标题A", "正文内容")

        self.assertEqual(result, "标题A\n标题A\n正文内容")
        self.assertEqual(result.count("标题A"), 2)


SCORING_PAYLOAD = {
    "ai_focus": "primary",
    "dimensions": {"impact": 7, "novelty": 8, "substance": 8},
    "category": "model_release",
    "tags": ["Agent"],
    "title_zh": "标题",
    "one_line_summary": "一句话",
    "summary_zh": "摘要",
    "reason_zh": "理由",
    "action_zh": "动作",
}


def _chat_response(content, usage=None):
    response = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    if usage is not None:
        response["usage"] = usage
    return response


class DeepSeekThinkingModeTests(unittest.TestCase):
    """DeepSeek bills thinking tokens at the output rate and defaults to
    thinking=enabled + reasoning_effort=high, so every call must state its
    intent explicitly rather than inherit the expensive default."""

    def _capture(self, provider):
        calls = []

        def fake_post_json(_url, payload, **_kwargs):
            calls.append(payload)
            content = json.dumps(
                {
                    **SCORING_PAYLOAD,
                    "is_ai_related": True,
                    "confidence": 0.9,
                    "reason": "reason",
                    "same_event": False,
                    "paragraphs_zh": ["译文"],
                    "mainline_title": "主线",
                    "mainline_body": "正文",
                    "theme_notes": [{"label": "模型", "note": "动向"}],
                },
                ensure_ascii=False,
            )
            return _chat_response(content)

        provider._post_json = fake_post_json
        return calls

    def test_classification_and_translation_calls_disable_thinking(self):
        provider = DeepSeekProvider("test-key")
        calls = self._capture(provider)

        provider.prefilter("标题\n正文")
        provider.verify_same_event({"id": "a", "title": "t"}, {"id": "b", "title": "t"})
        provider.translate_paragraphs(["hello"])

        self.assertEqual([call["thinking"] for call in calls], [{"type": "disabled"}] * 3)
        for call in calls:
            self.assertNotIn("reasoning_effort", call)

    def test_scoring_thinks_at_the_configured_effort(self):
        provider = DeepSeekProvider("test-key")
        calls = self._capture(provider)

        provider.score_article("标题", "正文")

        self.assertEqual(calls[0]["thinking"], {"type": "enabled"})
        self.assertEqual(calls[0]["reasoning_effort"], "low")

    def test_scoring_effort_off_disables_thinking_entirely(self):
        provider = DeepSeekProvider("test-key", scoring_reasoning_effort="off")
        calls = self._capture(provider)

        provider.score_article("标题", "正文")

        self.assertEqual(calls[0]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", calls[0])

    def test_period_summary_keeps_thinking(self):
        # runs once per week/month, and is the only call that synthesizes
        # across dozens of events rather than classifying one
        provider = DeepSeekProvider("test-key")
        calls = self._capture(provider)

        provider.summarize_period([{"title": "事件"}], "weekly", "2026-08-10 ~ 2026-08-16")

        self.assertEqual(calls[0]["thinking"], {"type": "enabled"})

    def test_rejects_an_unknown_effort_setting(self):
        with self.assertRaises(ValueError):
            DeepSeekProvider("test-key", scoring_reasoning_effort="medium-ish")


class UsageAccountingTests(unittest.TestCase):
    def test_reads_deepseek_cache_split_and_reasoning_tokens(self):
        usage = usage_from_response(
            {
                "usage": {
                    "prompt_tokens": 3000,
                    "prompt_cache_hit_tokens": 2400,
                    "prompt_cache_miss_tokens": 600,
                    "completion_tokens": 900,
                    "completion_tokens_details": {"reasoning_tokens": 700},
                }
            },
            operation="score_article",
            model="deepseek-v4-flash",
        )

        self.assertEqual(usage.cache_hit_tokens, 2400)
        self.assertEqual(usage.cache_miss_tokens, 600)
        self.assertEqual(usage.reasoning_tokens, 700)
        self.assertEqual(usage.calls, 1)

    def test_reads_the_openai_cached_tokens_spelling(self):
        usage = usage_from_response(
            {
                "usage": {
                    "prompt_tokens": 1000,
                    "prompt_tokens_details": {"cached_tokens": 400},
                    "completion_tokens": 120,
                }
            },
            operation="prefilter",
            model="gpt-4.1-mini",
        )

        self.assertEqual(usage.cache_hit_tokens, 400)
        # derived, because OpenAI reports no explicit miss count
        self.assertEqual(usage.cache_miss_tokens, 600)
        self.assertEqual(usage.reasoning_tokens, 0)

    def test_returns_none_when_the_provider_reports_no_usage(self):
        self.assertIsNone(
            usage_from_response({"choices": []}, operation="prefilter", model="m")
        )

    def test_collector_merges_by_model_and_operation(self):
        collector = UsageCollector()
        for _ in range(3):
            collector.record(
                AIUsage(operation="prefilter", model="m", prompt_tokens=100, completion_tokens=10)
            )
        collector.record(
            AIUsage(operation="score_article", model="m", prompt_tokens=4000, reasoning_tokens=900)
        )

        totals = {item.operation: item for item in collector.snapshot()}

        self.assertEqual(totals["prefilter"].calls, 3)
        self.assertEqual(totals["prefilter"].prompt_tokens, 300)
        self.assertEqual(totals["score_article"].reasoning_tokens, 900)

    def test_drain_resets_so_the_next_run_cannot_double_count(self):
        collector = UsageCollector()
        collector.record(AIUsage(operation="prefilter", model="m", prompt_tokens=100))

        self.assertEqual(len(collector.drain()), 1)
        self.assertEqual(collector.drain(), [])

    def test_provider_records_usage_under_the_calling_operation(self):
        collector = UsageCollector()
        provider = DeepSeekProvider("test-key", usage_collector=collector)

        def fake_post_json(_url, _payload, **_kwargs):
            return _chat_response(
                json.dumps(SCORING_PAYLOAD, ensure_ascii=False),
                usage={
                    "prompt_tokens": 5000,
                    "prompt_cache_hit_tokens": 2560,
                    "prompt_cache_miss_tokens": 2440,
                    "completion_tokens": 1200,
                    "completion_tokens_details": {"reasoning_tokens": 800},
                },
            )

        provider._post_json = fake_post_json
        provider.score_article("标题", "正文")

        recorded = collector.snapshot()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].operation, "score_article")
        self.assertEqual(recorded[0].model, "deepseek-v4-flash")
        self.assertEqual(recorded[0].reasoning_tokens, 800)

    def test_a_provider_without_a_collector_still_works(self):
        provider = DeepSeekProvider("test-key")
        provider._post_json = lambda _url, _payload: _chat_response(
            json.dumps(SCORING_PAYLOAD, ensure_ascii=False), usage={"prompt_tokens": 10}
        )

        self.assertEqual(provider.score_article("标题", "正文").title_zh, "标题")


class QwenProviderTests(unittest.TestCase):
    """Bailian's dialect differs from DeepSeek's in two ways that cost real
    money when got wrong, both established by measurement against the API."""

    def _capture(self, provider):
        calls = []

        def fake_post_json(_url, payload, **_kwargs):
            calls.append(payload)
            return _chat_response(
                json.dumps(
                    {
                        **SCORING_PAYLOAD,
                        "is_ai_related": True,
                        "confidence": 0.9,
                        "reason": "reason",
                        "same_event": False,
                        "paragraphs_zh": ["译文"],
                        "mainline_title": "主线",
                        "mainline_body": "正文",
                        "theme_notes": [{"label": "模型", "note": "动向"}],
                    },
                    ensure_ascii=False,
                )
            )

        provider._post_json = fake_post_json
        return calls

    def test_never_sends_deepseek_thinking_fields(self):
        # qwen3.7 silently ignores reasoning_effort (it only applies to
        # glm-5.x / deepseek-v4 / kimi-k3 on Bailian). Sending it leaves the
        # model at full reasoning strength - measured at 53% MORE expensive
        # than DeepSeek - while looking like it was configured correctly.
        provider = QwenProvider("test-key")
        calls = self._capture(provider)

        provider.prefilter("标题\n正文")
        provider.score_article("标题", "正文")
        provider.summarize_period([{"title": "事件"}], "weekly", "范围")

        for call in calls:
            self.assertNotIn("reasoning_effort", call)
            self.assertNotIn("thinking", call)

    def test_classification_and_translation_disable_thinking(self):
        provider = QwenProvider("test-key")
        calls = self._capture(provider)

        provider.prefilter("标题\n正文")
        provider.verify_same_event({"id": "a"}, {"id": "b"})
        provider.translate_paragraphs(["hello"])

        self.assertEqual([call["enable_thinking"] for call in calls], [False, False, False])
        for call in calls:
            self.assertNotIn("thinking_budget", call)

    def test_scoring_spends_the_configured_thinking_budget(self):
        provider = QwenProvider("test-key", thinking_budget=50)
        calls = self._capture(provider)

        provider.score_article("标题", "正文")

        self.assertIs(calls[0]["enable_thinking"], True)
        self.assertEqual(calls[0]["thinking_budget"], 50)

    def test_zero_budget_turns_scoring_thinking_off(self):
        provider = QwenProvider("test-key", thinking_budget=0)
        calls = self._capture(provider)

        provider.score_article("标题", "正文")

        self.assertIs(calls[0]["enable_thinking"], False)
        self.assertNotIn("thinking_budget", calls[0])

    def test_period_summary_thinks_without_a_budget_cap(self):
        provider = QwenProvider("test-key", thinking_budget=50)
        calls = self._capture(provider)

        provider.summarize_period([{"title": "事件"}], "weekly", "范围")

        self.assertIs(calls[0]["enable_thinking"], True)
        self.assertNotIn("thinking_budget", calls[0])

    def test_rejects_a_negative_budget(self):
        with self.assertRaises(ValueError):
            QwenProvider("test-key", thinking_budget=-1)

    def test_long_system_prompt_carries_an_explicit_cache_marker(self):
        # Bailian's implicit cache never hit in testing; the explicit marker
        # measured a 67% input-cache hit rate on the scoring prefix
        provider = QwenProvider("test-key")
        calls = self._capture(provider)

        provider.score_article("标题", "正文")

        system = calls[0]["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIsInstance(system["content"], list)
        self.assertEqual(system["content"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(system["content"][0]["text"], scoring_system_prompt())
        # the per-article half must stay a plain string, or it would be
        # cached too and the block would never match the next article
        self.assertIsInstance(calls[0]["messages"][1]["content"], str)

    def test_short_system_prompt_is_left_unmarked(self):
        # below Bailian's 1024-token minimum the marker cannot create a block,
        # so prefilter (a ~278-token prompt) must not pay for the attempt
        provider = QwenProvider("test-key")
        calls = self._capture(provider)

        provider.prefilter("标题\n正文")

        self.assertIsInstance(calls[0]["messages"][0]["content"], str)

    def test_does_not_send_the_deepseek_user_id_field(self):
        provider = QwenProvider("test-key")
        calls = self._capture(provider)

        provider.prefilter("标题\n正文")

        self.assertNotIn("user_id", calls[0])

    def test_records_usage_like_every_other_provider(self):
        collector = UsageCollector()
        provider = QwenProvider("test-key", usage_collector=collector)
        provider._post_json = lambda _u, _p: _chat_response(
            json.dumps(SCORING_PAYLOAD, ensure_ascii=False),
            usage={
                "prompt_tokens": 2820,
                "prompt_tokens_details": {"cached_tokens": 1894},
                "completion_tokens": 410,
            },
        )

        provider.score_article("标题", "正文")

        recorded = collector.snapshot()[0]
        self.assertEqual(recorded.operation, "score_article")
        self.assertEqual(recorded.model, "qwen3.7-flash")
        self.assertEqual(recorded.cache_hit_tokens, 1894)
        self.assertEqual(recorded.cache_miss_tokens, 926)


class ProviderSelectionTests(unittest.TestCase):
    def test_ali_key_selects_qwen(self):
        with patch.dict(
            os.environ,
            {"ALI_API_KEY": "sk-ali", "AI_PROVIDER": "", "DEEPSEEK_API_KEY": ""},
            clear=False,
        ):
            provider = provider_from_env()

        self.assertIsInstance(provider, QwenProvider)
        self.assertEqual(provider.model, "qwen3.7-flash")
        self.assertEqual(provider.thinking_budget, 50)

    def test_explicit_provider_name_and_overrides(self):
        with patch.dict(
            os.environ,
            {
                "ALI_API_KEY": "sk-ali",
                "AI_PROVIDER": "bailian",
                "QWEN_MODEL": "qwen3.7-plus",
                "QWEN_THINKING_BUDGET": "0",
            },
            clear=False,
        ):
            provider = provider_from_env()

        self.assertEqual(provider.model, "qwen3.7-plus")
        self.assertEqual(provider.thinking_budget, 0)

    def test_qwen_without_a_key_fails_loudly(self):
        with patch.dict(
            os.environ,
            {"AI_PROVIDER": "qwen", "ALI_API_KEY": "", "DASHSCOPE_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                provider_from_env()


class RequestTimeoutAndRetryTests(unittest.TestCase):
    """2026-W33 and 2026-08 both degraded to 「本期 AI 综述生成失败」because the
    period summary - the one call that has to emit 360-440 characters of prose
    in a single shot - shared the 60s timeout with short scoring calls and had
    no retry at all."""

    def _summary_response(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "mainline_title": "主线标题",
                                "mainline_body": "正文",
                                "theme_notes": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    def test_period_summary_gets_the_long_form_timeout(self):
        from app.services.ai_service import LONG_FORM_TIMEOUT_SECONDS

        provider = QwenProvider(api_key="k")
        seen: dict = {}

        def fake_post(_url, _payload, *, timeout=None):
            seen["timeout"] = timeout
            return self._summary_response()

        with patch.object(provider, "_post_json", side_effect=fake_post):
            provider.summarize_period([{"title": "t"}], "monthly", "2026-08-01 ~ 2026-08-31")

        self.assertEqual(seen["timeout"], LONG_FORM_TIMEOUT_SECONDS)
        self.assertGreater(LONG_FORM_TIMEOUT_SECONDS, 60)

    def test_short_calls_keep_the_default_timeout(self):
        from app.services.ai_service import DEFAULT_TIMEOUT_SECONDS

        provider = QwenProvider(api_key="k")
        seen: dict = {}

        def fake_post(_url, _payload, *, timeout=None):
            seen["timeout"] = timeout
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "same_event": True,
                                    "confidence": 0.9,
                                    "reason": "同一发布",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

        with patch.object(provider, "_post_json", side_effect=fake_post):
            provider.verify_same_event({"id": "a"}, {"id": "b"})

        self.assertEqual(seen["timeout"], DEFAULT_TIMEOUT_SECONDS)

    def test_retry_recovers_from_a_transport_timeout(self):
        import urllib.error

        from app.services.ai_service import urlopen_json_with_retry

        attempts = {"n": 0}

        def flaky(_request, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise urllib.error.URLError("timed out")

            class _Response:
                def read(self):
                    return b'{"ok": true}'

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Response()

        with patch("urllib.request.urlopen", side_effect=flaky):
            with patch("time.sleep"):
                result = urlopen_json_with_retry(object(), timeout=1, label="test")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts["n"], 2)

    def test_client_errors_are_not_retried(self):
        import urllib.error

        from app.services.ai_service import urlopen_json_with_retry

        attempts = {"n": 0}

        def bad_request(_request, timeout=None):
            attempts["n"] += 1
            raise urllib.error.HTTPError("u", 400, "Bad Request", {}, None)

        with patch("urllib.request.urlopen", side_effect=bad_request):
            with patch("time.sleep"):
                with self.assertRaises(urllib.error.HTTPError):
                    urlopen_json_with_retry(object(), timeout=1, label="test")

        # a malformed request gets the same answer every time - retrying it
        # only burns tokens and wall clock
        self.assertEqual(attempts["n"], 1)

    def test_server_errors_are_retried_then_reraised(self):
        import urllib.error

        from app.services.ai_service import NETWORK_RETRY_ATTEMPTS, urlopen_json_with_retry

        attempts = {"n": 0}

        def server_error(_request, timeout=None):
            attempts["n"] += 1
            raise urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None)

        with patch("urllib.request.urlopen", side_effect=server_error):
            with patch("time.sleep"):
                with self.assertRaises(urllib.error.HTTPError):
                    urlopen_json_with_retry(object(), timeout=1, label="test")

        # the final failure must still surface, so callers that fall back to
        # deterministic copy can log the real reason
        self.assertEqual(attempts["n"], NETWORK_RETRY_ATTEMPTS + 1)


if __name__ == "__main__":
    unittest.main()
