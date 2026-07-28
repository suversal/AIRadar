import sys
import threading
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import ContentValueDimensions, PrefilterResult, RawArticle, ScoringResult, Source
from app.pipeline.runner import (
    _text_blocks_for_translation,
    _translation_paragraphs_for,
    _translate_in_chunks,
    _translated_blocks_for,
    run_pipeline,
)
from app.services.ai_service import FakeAIProvider


class PipelineTests(unittest.TestCase):
    def test_pipeline_has_no_global_candidate_cap(self):
        # 2026-07-12 决策:总量由每个信源自己的 crawl_limit 在抓取层约束,
        # pipeline 不得再按全局上限静默跳过候选
        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="community",
            tier="T2",
            type="hn",
            category="community",
            url="https://news.ycombinator.com",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": f"https://news.ycombinator.com/item?id={index}",
                "title": f"AI model release update {index}",
                "content": f"AI model {index} ships new agent capabilities for developers.",
                "author": "hn",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(105)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"hacker_news": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertEqual(len(result.raw_articles), 105)
        self.assertEqual(len(result.processed_articles), 105)
        self.assertNotIn("candidate_limit", result.skipped_reasons)
        # 阶段计时:定位"AI 处理中"里的时间去向(评分/聚类/README/翻译/成报)
        for stage in ("ai_candidates", "clustering", "readme", "translation", "report"):
            self.assertIn(stage, result.stage_timings)
            self.assertGreaterEqual(result.stage_timings[stage], 0.0)

    def test_pipeline_filters_non_ai_and_generates_daily_report(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://openai.com/a",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases a new AI agent model for developers.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/b",
                "title": "Office lunch menu",
                "content": "Cafeteria update.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/c",
                "title": "Anthropic Claude Code improves agent workflows",
                "content": "AI coding assistant update for agent workflows.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
        )

        self.assertEqual(len(result.raw_articles), 3)
        self.assertEqual(len(result.processed_articles), 2)
        self.assertIn("Suversal AI Radar 日报", result.daily_report.markdown)
        self.assertNotIn("candidate_limit", result.skipped_reasons)
        self.assertEqual(result.skipped_reasons["not_ai_related"], 1)

    def test_title_only_articles_are_skipped_without_any_ai_call(self):
        # 流程重排(2026-07-12 晚):标题-only(HN 外链在 feed 阶段的常态)
        # 允许进预筛——标题足够判断 AI 相关性;但正文拉取失败后仍无内容的,
        # 绝不能进入完整评分(LLM 对着一句标题也能编出高分)
        class ExplodingProvider(FakeAIProvider):
            def score_article(self, title, content):
                raise AssertionError("score_article must not be called for title-only articles")

        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="hn",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
        )
        raw_items = [
            {
                "source_url": "https://example.com/spa-shell",
                "title": "New AI agent model ships for developers",
                # feed 阶段外链帖的常态:正文 = 标题,等待预筛通过后拉取
                "content": "New AI agent model ships for developers",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {"points": 42, "comments": 17},
                "metadata": {"body_fetch": "deferred"},
            }
        ]

        # 正文拉取失败(反爬/SPA):内容保持标题-only
        with patch("app.crawlers.page_content.prefer_full_page_content", lambda article, **kwargs: None):
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={"hacker_news": raw_items},
                ai_provider=ExplodingProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                top_n=12,
            )

        self.assertEqual(result.skipped_reasons.get("no_content"), 1)
        self.assertEqual(len(result.processed_articles), 0)
        skipped = result.raw_articles[0]
        self.assertEqual(skipped.status, "skipped")
        self.assertEqual(skipped.skipped_reason, "no_content")

    def test_pipeline_only_processes_articles_published_on_report_date(self):
        # 2026-07-12 深夜决策:feed 里的陈年存量一概不处理——只处理发布
        # 日期(上海时区)等于报告日期的文章;无发布时间的(聚合器)保留
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )

        def item(url_slug, published_at):
            return {
                "source_url": f"https://openai.com/{url_slug}",
                "title": f"AI model release {url_slug}",
                "content": f"AI model release story {url_slug} about agents.",
                "author": "OpenAI",
                "published_at": published_at,
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }

        raw_items = [
            # 上海时间 7/1 08:00 = UTC 00:00 → 当天,保留
            item("today", datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)),
            # UTC 6/30 15:00 = 上海 6/30 23:00 → 昨天,过滤
            item("yesterday", datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)),
            # 陈年存量,过滤
            item("ancient", datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)),
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        kept_urls = {article.source_url for article in result.raw_articles}
        self.assertEqual(kept_urls, {"https://openai.com/today"})

        # 防御分支:published_at 为 None 的文章(normalize 之前的形态)
        # 视为当前保留——生产上 normalize 会把 None 填成抓取时刻
        from dataclasses import replace as dc_replace

        from app.pipeline.runner import filter_articles_published_on

        undated = dc_replace(result.raw_articles[0], published_at=None)
        self.assertEqual(
            [a.source_url for a in filter_articles_published_on([undated], date(2026, 7, 1))],
            ["https://openai.com/today"],
        )

        # 豁免源(config.ingest_all_dates,如 attentionvc_x 的滚动趋势窗口):
        # 不筛当天,全部保留——判重仍由 url_hash 兜底。2026-07-15 起
        # AI HOT 的两个精选源改用 recent_days=0(见下一条用例),不再走
        # 这条 exempt_source_ids 路径,但该机制本身仍保留给其他场景使用
        ancient = dc_replace(
            result.raw_articles[0],
            source_id="attentionvc_x",
            published_at=datetime(2025, 1, 1, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [
                a.source_id
                for a in filter_articles_published_on(
                    [ancient], date(2026, 7, 1), exempt_source_ids={"attentionvc_x"}
                )
            ],
            ["attentionvc_x"],
        )

        # 2026-07-15:recent_days=0 表示不限日期,与 exempt_source_ids 是
        # 两条并存的豁免路径——AI HOT 的两个精选源统一走这条,不再依赖
        # 专属的 ingest_all_dates 开关
        ancient_unlimited = dc_replace(
            result.raw_articles[0],
            source_id="aihot_all",
            published_at=datetime(2025, 1, 1, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [
                a.source_id
                for a in filter_articles_published_on(
                    [ancient_unlimited],
                    date(2026, 7, 1),
                    recent_days_by_source={"aihot_all": 0},
                )
            ],
            ["aihot_all"],
        )

        # 2026-07-15:仅当天发布 → 按信源 config.recent_days 配置的最近 N
        # 天窗口过滤;窗口以外的仍出局,recent_days_by_source 里没有的
        # source_id 按 1(仅当天,与改造前一致)处理
        two_days_ago = dc_replace(
            result.raw_articles[0],
            published_at=datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc),
        )
        out_of_window = dc_replace(
            result.raw_articles[0],
            published_at=datetime(2026, 6, 28, 0, 0, tzinfo=timezone.utc),
        )
        kept = filter_articles_published_on(
            [two_days_ago, out_of_window],
            date(2026, 7, 1),
            recent_days_by_source={"openai_blog": 3},
        )
        self.assertEqual([a.published_at for a in kept], [two_days_ago.published_at])

    def test_source_recent_days_defaults_and_validates(self):
        # 2026-07-15:config.recent_days 缺失/非法一律回退到 1(仅当天),
        # 合法正整数原样使用,0 是合法值(不限日期),负数视为非法回退到 1
        from app.pipeline.runner import source_recent_days

        def source_with_config(config):
            return Source(
                id="s",
                name="s",
                source_role="authority",
                tier="T1",
                type="rss",
                category="official",
                url="https://example.com/rss.xml",
                homepage="https://example.com",
                allowed_domains=["example.com"],
                can_be_main_source=True,
                config=config,
            )

        self.assertEqual(source_recent_days(source_with_config({})), 1)
        self.assertEqual(source_recent_days(source_with_config({"recent_days": 5})), 5)
        self.assertEqual(source_recent_days(source_with_config({"recent_days": 0})), 0)
        self.assertEqual(source_recent_days(source_with_config({"recent_days": -3})), 1)
        self.assertEqual(source_recent_days(source_with_config({"recent_days": "not_a_number"})), 1)

    def test_default_aihot_sources_use_unlimited_recent_days(self):
        # 2026-07-15:AI HOT 的两个精选源(feed.xml 只返回最新 N 条,与发布
        # 日期无关)改用 recent_days=0 表达不限日期,取代原来专属的
        # ingest_all_dates 开关,与其他信源共用同一套可配置机制
        from app.data.default_sources import default_sources
        from app.pipeline.runner import source_recent_days

        sources_by_id = {source.id: source for source in default_sources()}
        self.assertEqual(source_recent_days(sources_by_id["aihot_feed"]), 0)
        self.assertEqual(source_recent_days(sources_by_id["aihot_all"]), 0)
        self.assertNotIn("ingest_all_dates", sources_by_id["aihot_feed"].config)
        self.assertNotIn("ingest_all_dates", sources_by_id["aihot_all"].config)

    def test_each_scored_article_triggers_immediate_persist_callback(self):
        # 2026-07-12 深夜决策:每成功评分一条立即回调保存,数据库持续
        # 增长;跳过类不回调;回调抛异常不得炸掉整轮
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://openai.com/a",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases a new AI agent model for developers.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/junk",
                "title": "Office lunch menu",
                "content": "Cafeteria update for staff members today.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
        ]

        saved: list[str] = []

        def exploding_callback(article, processed, embedding):
            saved.append(processed.raw_article_id)
            raise RuntimeError("db hiccup must not break the run")

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            on_article_processed=exploding_callback,
        )

        self.assertEqual(len(result.processed_articles), 1)
        self.assertEqual(saved, [result.processed_articles[0].raw_article_id])

    def test_non_ai_articles_never_trigger_body_fetch(self):
        # 预筛前置的核心收益:非 AI 文章零外站请求
        fetch_calls: list[str] = []

        def recording_fetch(article, **kwargs):
            fetch_calls.append(article.source_url)

        source = Source(
            id="ithome",
            name="IT之家",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://www.ithome.com/rss/",
            homepage="https://www.ithome.com",
            allowed_domains=["ithome.com"],
        )
        raw_items = [
            {
                "source_url": "https://www.ithome.com/junk",
                "title": "Office lunch menu",
                "content": "Office lunch menu\nCafeteria update for staff.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"body_fetch": "deferred"},
            },
            {
                "source_url": "https://www.ithome.com/ai-news",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases agent model\nAI model release teaser.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"body_fetch": "deferred"},
            },
        ]

        with patch("app.crawlers.page_content.prefer_full_page_content", recording_fetch):
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={"ithome": raw_items},
                ai_provider=FakeAIProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
            )

        # 非 AI 的 junk 没触发正文拉取;通过预筛的 ai-news 拉了
        self.assertEqual(fetch_calls, ["https://www.ithome.com/ai-news"])
        self.assertEqual(result.skipped_reasons.get("not_ai_related"), 1)
        self.assertEqual(len(result.processed_articles), 1)

    def test_all_selected_articles_are_clustered_not_just_top_n(self):
        # 产品决策（2026-07-11）：聚类范围 = 全部入选文章，事件表是完整的
        # 事件图谱；日报动态展示全部入选事件，不再限制数量
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": f"https://openai.com/full-{index}",
                "title": f"AI agent model release {index}",
                "content": f"Distinct AI model release story number {index} about agents.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(3)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=1,
        )

        selected = [p for p in result.processed_articles if p.selected]
        self.assertEqual(len(selected), 3)
        # 全部入选文章都有事件归属
        for processed in selected:
            self.assertIsNotNone(processed.event_cluster_id)
        # 互不相似的三篇 → 三个事件；旧 top_n 参数不再产生截断
        self.assertEqual(len(result.event_clusters), 3)
        self.assertEqual(result.daily_report.article_count, 3)

    def test_cluster_similarity_threshold_is_configurable(self):
        source_a = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        source_b = Source(
            id="anthropic_blog",
            name="Anthropic Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://anthropic.com/rss.xml",
            homepage="https://anthropic.com",
            allowed_domains=["anthropic.com"],
            can_be_main_source=True,
        )
        raw_items_by_source = {
            "openai_blog": [
                {
                    "source_url": "https://openai.com/marker-a",
                    "title": "marker-a story",
                    "content": "marker-a coverage of an AI model release.",
                    "author": "OpenAI",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {},
                }
            ],
            "anthropic_blog": [
                {
                    "source_url": "https://anthropic.com/marker-b",
                    "title": "marker-b story",
                    "content": "marker-b coverage of the same AI model release.",
                    "author": "Anthropic",
                    "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {},
                }
            ],
        }
        # vectors pinned to an exact cosine similarity of 0.7
        vector_a = [1.0] + [0.0] * 63
        vector_b = [0.7, 0.7141428429, 0.0] + [0.0] * 61
        provider = FixedVectorAIProvider(
            {"marker-a": vector_a, "marker-b": vector_b}
        )

        strict = run_pipeline(
            sources=[source_a, source_b],
            raw_items_by_source=raw_items_by_source,
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
            cluster_similarity_threshold=0.9,
        )
        lenient = run_pipeline(
            sources=[source_a, source_b],
            raw_items_by_source=raw_items_by_source,
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
            cluster_similarity_threshold=0.5,
        )

        self.assertEqual(len(strict.event_clusters), 2)
        self.assertEqual(len(lenient.event_clusters), 1)
        self.assertEqual(lenient.event_clusters[0].source_count, 2)
        # embeddings computed for clustering must also flow out on the result
        # so the persistence layer can save them for future cross-day matching
        self.assertEqual(len(strict.embeddings), 2)
        self.assertEqual(strict.embeddings[strict.raw_articles[0].id], vector_a)

    def test_pipeline_reuses_cached_results_without_ai_calls(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://openai.com/cached",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases a new AI agent model for developers.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/fresh",
                "title": "Anthropic ships AI coding agent",
                "content": "New AI coding agent release for developers.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/known-noise",
                "title": "Office lunch menu",
                "content": "Cafeteria update.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
        ]

        from app.crawlers.base import canonicalize_url, stable_hash

        cached_hash = stable_hash(canonicalize_url("https://openai.com/cached"))
        # 四步流程(2026-07-12 晚)恢复非AI入库作跳过标记:库里已判非AI的
        # 文章命中缓存直接跳过,不再重新预筛
        noise_hash = stable_hash(canonicalize_url("https://openai.com/known-noise"))
        cached_full_body = (
            "OpenAI releases a new AI agent model for developers. "
            "This is the stored full-page body from the first processing run, "
            "much longer than the feed teaser that re-crawls carry."
        )
        cached_vector = [0.5] + [0.0] * 511
        cached_results = {
            cached_hash: {
                "raw_article_id": "persisted-raw-id",
                "content": cached_full_body,
                "embedding": cached_vector,
                "scoring": {
                    "ai_focus": "primary",
                    "dimensions": {
                        "impact": 8,
                        "novelty": 8,
                        "substance": 7,
                    },
                    "category": "model_release",
                    "tags": ["Agent"],
                    "title_zh": "缓存的中文标题",
                    "one_line_summary": "缓存摘要。",
                    "summary_zh": "缓存核心摘要。",
                    "reason_zh": "缓存推荐理由。",
                    "action_zh": "缓存动作。",
                },
                "skipped_reason": None,
                "metadata": {
                    "translated_paragraphs": ["缓存译文段落"],
                    # hash of the article body that was translated; matching
                    # hash means the cached translation is still valid. 缓存
                    # 文章的正文以库里全文为准(流程重排),哈希也随之锚定全文
                    "translation_source_hash": __import__("app.pipeline.runner", fromlist=["translation_source_hash"]).translation_source_hash(
                        [cached_full_body]
                    ),
                },
            },
            noise_hash: {"scoring": None, "skipped_reason": "not_ai_related", "metadata": {}},
        }

        class CountingProvider(FakeAIProvider):
            def __init__(self):
                self.prefilter_calls = 0
                self.score_calls = 0
                self.embed_calls = 0

            def prefilter(self, text):
                self.prefilter_calls += 1
                return super().prefilter(text)

            def score_article(self, title, content):
                self.score_calls += 1
                return super().score_article(title, content)

            def embed_text(self, text):
                self.embed_calls += 1
                return super().embed_text(text)

        provider = CountingProvider()
        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
            cached_results=cached_results,
        )

        # 缓存命中的(含历史非AI判定)不进 AI;只有 fresh 真实预筛+评分
        self.assertEqual(provider.prefilter_calls, 1)
        self.assertEqual(provider.score_calls, 1)
        # 缓存文章复用库里的向量,不重算(feed 摘要算出的劣质向量会在
        # 落库时覆盖全文向量);全文也要带回,供翻译哈希/展示使用
        self.assertEqual(provider.embed_calls, 1)
        self.assertEqual(result.embeddings["persisted-raw-id"][0], 0.5)
        cached_processed = next(
            p
            for p in result.processed_articles
            if any(a.id == p.raw_article_id and a.url_hash == cached_hash for a in result.raw_articles)
        )
        self.assertEqual(cached_processed.title_zh, "缓存的中文标题")
        self.assertEqual(result.skipped_reasons["not_ai_related"], 1)
        cached_article = next(a for a in result.raw_articles if a.url_hash == cached_hash)
        self.assertEqual(cached_article.id, "persisted-raw-id")
        self.assertEqual(cached_article.content, cached_full_body)
        self.assertIn("persisted-raw-id", result.embeddings)
        self.assertEqual(cached_processed.raw_article_id, "persisted-raw-id")
        self.assertEqual(cached_article.metadata["translated_paragraphs"], ["缓存译文段落"])

    def test_terminal_cached_article_is_read_only_and_restores_persisted_snapshot(self):
        from app.crawlers.base import canonicalize_url, stable_hash

        source = Source(
            id="ifanr",
            name="爱范儿",
            source_role="context",
            tier="T3",
            type="rss",
            category="media",
            url="https://www.ifanr.com/feed",
            homepage="https://www.ifanr.com",
            allowed_domains=["ifanr.com"],
            language="zh",
        )
        url = "https://www.ifanr.com/1673165"
        url_hash = stable_hash(canonicalize_url(url))
        full_body = "爱范儿已经持久化的完整正文第一段。\n\n完整正文第二段。"
        full_blocks = [
            {"type": "paragraph", "text": "爱范儿已经持久化的完整正文第一段。"},
            {"type": "paragraph", "text": "完整正文第二段。"},
        ]
        raw_items = [{
            "source_url": url,
            "title": "爱范儿文章",
            "content": "本轮 RSS 的短摘要",
            "author": "爱范儿",
            "published_at": datetime(2026, 7, 27, 8, tzinfo=timezone.utc),
            "language": "zh",
            "raw_score": {},
            "metadata": {
                "body_fetch": "deferred",
                "original_text": "本轮 RSS 的短摘要",
                "original_paragraphs": ["本轮 RSS 的短摘要"],
                "original_blocks": [{"type": "paragraph", "text": "本轮 RSS 的短摘要"}],
            },
        }]
        cached_results = {url_hash: {
            "raw_article_id": "persisted-ifanr-id",
            "content": full_body,
            "scoring": {
                "ai_focus": "primary",
                "dimensions": {
                    "impact": 8,
                    "novelty": 8,
                    "substance": 8,
                },
                "category": "industry",
                "tags": ["AI"],
                "title_zh": "持久化的中文标题",
                "one_line_summary": "持久化摘要",
                "summary_zh": "持久化核心摘要",
                "reason_zh": "持久化推荐理由",
                "action_zh": "持久化动作",
            },
            "processed": {
                "raw_article_id": "persisted-ifanr-id",
                "event_cluster_id": "persisted-event-id",
                "ai_focus": "primary",
                "dimensions": {
                    "impact": 8,
                    "novelty": 8,
                    "substance": 8,
                },
                "final_score": 86.0,
                "evidence_score": 65.0,
                "title_zh": "持久化的中文标题",
                "one_line_summary": "持久化摘要",
                "summary_zh": "持久化核心摘要",
                "reason_zh": "持久化推荐理由",
                "action_zh": "持久化动作",
                "category": "industry",
                "focus_category": "industry",
                "tags": ["AI"],
                "selected": True,
                "status": "processed",
                "rejection_reason": None,
                "selection_origin": "score",
                "selection_reason": "final_score:86>=threshold",
            },
            "metadata": {
                "content_extraction_version": 2,
                "original_text": full_body,
                "original_paragraphs": [block["text"] for block in full_blocks],
                "original_blocks": full_blocks,
            },
            "raw_article": {
                "id": "persisted-ifanr-id",
                "source_url": url,
                "title": "爱范儿文章",
                "content": full_body,
                "author": "爱范儿",
                "published_at": datetime(2026, 7, 27, 8, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "content_extraction_version": 2,
                    "original_text": full_body,
                    "original_paragraphs": [block["text"] for block in full_blocks],
                    "original_blocks": full_blocks,
                },
                "title_hash": "persisted-title-hash",
                "url_hash": url_hash,
                "status": "processed",
                "skipped_reason": None,
            },
        }}

        class NoActionProvider(FakeAIProvider):
            def prefilter(self, text):
                raise AssertionError("terminal article must not be prefiltered")

            def score_article(self, title, content):
                raise AssertionError("terminal article must not be rescored")

            def embed_text(self, text):
                raise AssertionError("terminal article must not be re-embedded")

            def translate_paragraphs(self, paragraphs):
                raise AssertionError("terminal article must not be translated")

        callbacks: list[str] = []
        with patch(
            "app.crawlers.page_content.prefer_full_page_content",
            side_effect=AssertionError("terminal article must not refetch its body"),
        ):
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={source.id: raw_items},
                ai_provider=NoActionProvider(),
                now=datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 27),
                cached_results=cached_results,
                on_article_processed=lambda article, *_: callbacks.append(article.id),
            )

        article = result.raw_articles[0]
        self.assertEqual(article.id, "persisted-ifanr-id")
        self.assertEqual(article.content, full_body)
        self.assertEqual(article.metadata["original_blocks"], full_blocks)
        self.assertEqual(result.read_only_raw_article_ids, {"persisted-ifanr-id"})
        self.assertEqual(callbacks, [])
        self.assertEqual(result.daily_report.article_count, 1)

    def test_cached_original_blocks_survive_a_thin_rerun(self):
        # regression for the qbitai bug: a cached article already has a fully
        # extracted body (original_blocks non-empty), but this round's RSS
        # crawl only re-parsed a thin feed summary with no recognizable <p>/
        # <h*> tags - extract_article_content() still writes the keys, just
        # empty. That empty value must not blank out the cached good one.
        source = Source(
            id="qbitai",
            name="量子位",
            source_role="media",
            tier="T2",
            type="rss",
            category="media",
            url="https://www.qbitai.com/feed",
            homepage="https://www.qbitai.com",
            allowed_domains=["qbitai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://www.qbitai.com/2026/07/13/cached-article",
                "title": "趋境科技完成A轮融资",
                "content": "趋境科技完成A轮融资，半年内募资10亿",
                "author": "量子位",
                "published_at": datetime(2026, 7, 13, 8, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "original_paragraphs": [],
                    "original_blocks": [],
                    "original_text": "",
                    "original_images": [],
                },
            },
        ]

        from app.crawlers.base import canonicalize_url, stable_hash

        cached_hash = stable_hash(
            canonicalize_url("https://www.qbitai.com/2026/07/13/cached-article")
        )
        good_blocks = [
            {"type": "heading", "level": 1, "text": "高品质AI Token生产服务能力获产业和资本的双重认可"},
            {"type": "paragraph", "text": "7月13日，全球领先的高效能 AI Token 生产服务商正式宣布完成 A 轮融资。"},
            {"type": "paragraph", "text": "本轮融资由河南投资集团汇融基金重磅领投。"},
        ]
        cached_results = {
            cached_hash: {
                "raw_article_id": "persisted-qbitai-id",
                "content": "趋境科技完成A轮融资，半年内募资10亿",
                "embedding": [0.1] + [0.0] * 511,
                "scoring": {
                    "ai_focus": "contributing",
                    "dimensions": {
                        "impact": 6,
                        "novelty": 6,
                        "substance": 6,
                    },
                    "category": "funding",
                    "tags": ["融资"],
                    "title_zh": "趋境科技完成A轮融资",
                    "one_line_summary": "摘要。",
                    "summary_zh": "核心摘要。",
                    "reason_zh": "推荐理由。",
                    "action_zh": "动作。",
                },
                "skipped_reason": None,
                "metadata": {
                    "original_paragraphs": [block["text"] for block in good_blocks],
                    "original_blocks": good_blocks,
                    "original_text": "\n\n".join(block["text"] for block in good_blocks),
                    "original_images": [],
                },
            },
        }

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"qbitai": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 13, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 13),
            top_n=12,
            cached_results=cached_results,
        )

        cached_article = next(a for a in result.raw_articles if a.url_hash == cached_hash)
        self.assertEqual(cached_article.metadata["original_blocks"], good_blocks)
        self.assertTrue(cached_article.metadata["original_paragraphs"])
        self.assertIn("高品质AI Token", cached_article.metadata["original_text"])

    def test_cached_aihot_body_replaces_nonempty_rss_summary_structure(self):
        from app.crawlers.base import normalize_article
        from app.pipeline.runner import _hydrate_article_from_cache

        source = Source(
            id="aihot_feed",
            name="AI HOT 每日精选",
            source_role="aggregator",
            tier="T3",
            type="rss",
            category="media",
            url="https://aihot.virxact.com/feed.xml",
            homepage="https://aihot.virxact.com",
            allowed_domains=["aihot.virxact.com"],
            language="zh",
            can_be_main_source=False,
        )
        summary = "这是非空的 AI HOT RSS 摘要。"
        article = normalize_article(
            source=source,
            source_url="https://aihot.virxact.com/items/example",
            title="AI HOT 缓存正文测试",
            content=summary,
            author="AI HOT",
            published_at=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
            language="zh",
            raw_score={},
            metadata={
                "body_fetch": "deferred",
                "aihot_permalink": "https://aihot.virxact.com/items/example",
                "original_text": summary,
                "original_paragraphs": [summary],
                "original_blocks": [{"type": "paragraph", "text": summary}],
                "original_images": [],
            },
        )
        full_paragraphs = [
            "这是 AI HOT 条目页抓取到的完整正文第一段。" * 4,
            "这是完整正文第二段，不能被下一轮 RSS 摘要覆盖。" * 4,
        ]
        full_blocks = [
            {"type": "paragraph", "text": paragraph} for paragraph in full_paragraphs
        ]
        cached = {
            "raw_article_id": "persisted-aihot-id",
            "language": "zh",
            "content": "\n\n".join(full_paragraphs),
            "metadata": {
                "content_extraction_version": 2,
                "original_text": "\n\n".join(full_paragraphs),
                "original_paragraphs": full_paragraphs,
                "original_blocks": full_blocks,
                "original_images": [],
            },
        }

        _hydrate_article_from_cache(article, cached)

        self.assertEqual(article.id, "persisted-aihot-id")
        self.assertEqual(article.content, cached["content"])
        self.assertEqual(article.metadata["original_text"], cached["metadata"]["original_text"])
        self.assertEqual(article.metadata["original_paragraphs"], full_paragraphs)
        self.assertEqual(article.metadata["original_blocks"], full_blocks)
        self.assertEqual(article.metadata["original_images"], [])

    def test_github_blog_profile_upgrade_refetches_and_rescores_only_stale_body(self):
        from app.crawlers.base import canonicalize_url, stable_hash
        from app.pipeline.runner import translation_source_hash

        source = Source(
            id="github_ai_blog",
            name="GitHub AI & Copilot Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://github.blog/ai-and-ml/feed/",
            homepage="https://github.blog/ai-and-ml/",
            allowed_domains=["github.blog"],
            can_be_main_source=True,
        )
        url = "https://github.blog/ai-and-ml/github-copilot/example-post"
        real_body = "Real GitHub Blog body about Copilot code review tools and benchmark results."
        raw_items = [{
            "source_url": url,
            "title": "Requested GitHub Blog article",
            "content": "Short RSS teaser.",
            "author": "GitHub",
            "published_at": datetime(2026, 7, 16, 8, tzinfo=timezone.utc),
            "language": "en",
            "raw_score": {},
            "metadata": {"body_fetch": "deferred"},
        }]
        url_hash = stable_hash(canonicalize_url(url))
        cached_results = {url_hash: {
            "raw_article_id": "github-existing-id",
            "content": "Wrong recommendation card body.",
            "scoring": {
                "ai_focus": "contributing",
                "dimensions": {
                    "impact": 6, "novelty": 6, "substance": 5,
                },
                "category": "industry",
                "tags": ["Wrong"],
                "title_zh": "错误的推荐卡片标题",
                "one_line_summary": "错误摘要",
                "summary_zh": "错误正文摘要",
                "reason_zh": "错误推荐理由",
                "action_zh": "错误动作",
            },
            "metadata": {
                "content_extraction_version": 2,
                "content_profile": "generic-v2",
                "original_blocks": [{"type": "paragraph", "text": "Wrong recommendation card body."}],
                "translated_paragraphs": ["旧译文"],
                "translated_blocks": [
                    {"type": "byline", "author": {"name": "Stale Author"}},
                    {"type": "paragraph", "text": "旧译文"},
                ],
                # Deliberately match the replacement text: extractor-version
                # invalidation must rebuild block structure even when the
                # text-only translation hash itself still matches.
                "translation_source_hash": translation_source_hash([real_body]),
            },
        }}

        class CountingProvider(FakeAIProvider):
            def __init__(self):
                self.score_calls = 0

            def score_article(self, title, content):
                self.score_calls += 1
                self.asserted_content = content
                return super().score_article(title, content)

        def replace_with_full_page(article, **_kwargs):
            article.content = real_body
            article.metadata.update({
                "content_extraction_version": 4,
                "content_profile": "github-blog-v1",
                "original_blocks": [{"type": "paragraph", "text": article.content}],
                "original_paragraphs": [article.content],
                "original_text": article.content,
                "content_origin": "full_page",
            })

        provider = CountingProvider()
        with patch(
            "app.crawlers.page_content.prefer_full_page_content",
            side_effect=replace_with_full_page,
        ) as fetch:
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={source.id: raw_items},
                ai_provider=provider,
                now=datetime(2026, 7, 16, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 16),
                cached_results=cached_results,
                skip_prefilter=True,
            )

        fetch.assert_called_once()
        self.assertEqual(provider.score_calls, 1)
        self.assertIn("Real GitHub Blog body", provider.asserted_content)
        self.assertNotEqual(result.processed_articles[0].title_zh, "错误的推荐卡片标题")
        self.assertEqual(result.raw_articles[0].metadata["content_profile"], "github-blog-v1")
        self.assertEqual(result.read_only_raw_article_ids, set())
        self.assertFalse(any(
            block.get("type") == "byline"
            for block in result.raw_articles[0].metadata["translated_blocks"]
        ))

    def test_heading_blocks_survive_the_translation_round_trip(self):
        # a heading must be sent to translation alongside paragraphs (else
        # the translated article loses its title) and come back tagged as
        # "heading" with its original level - not silently demoted to a
        # plain paragraph.
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a1",
            title="Release notes",
            content="Release notes",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={
                "original_blocks": [
                    {"type": "heading", "level": 1, "text": "Release notes"},
                    {"type": "paragraph", "text": "Body text here."},
                ],
                "original_paragraphs": ["Release notes", "Body text here."],
            },
            title_hash="title-a1",
            url_hash="hash-a1",
        )

        text_blocks = _text_blocks_for_translation(article)
        self.assertEqual(
            [block["type"] for block in text_blocks], ["heading", "paragraph"]
        )

        translated_paragraphs = [f"译:{block['text']}" for block in text_blocks]
        translated_blocks = _translated_blocks_for(article, translated_paragraphs)

        self.assertEqual(
            translated_blocks,
            [
                {"type": "heading", "level": 1, "text": "译:Release notes"},
                {"type": "paragraph", "text": "译:Body text here."},
            ],
        )

    def test_video_blocks_survive_the_translation_round_trip(self):
        article = RawArticle(
            id="deepmind-video",
            source_id="deepmind_blog",
            source_name="Google DeepMind Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://deepmind.google/blog/example/",
            title="Example",
            content="Before.\n\nAfter.",
            author="Google DeepMind",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={
                "original_blocks": [
                    {"type": "paragraph", "text": "Before."},
                    {
                        "type": "video",
                        "provider": "youtube",
                        "url": "https://www.youtube-nocookie.com/embed/xJ94HFpGM4Y",
                        "title": "Overview",
                    },
                    {"type": "paragraph", "text": "After."},
                ]
            },
            title_hash="deepmind-video-title",
            url_hash="deepmind-video-url",
        )

        self.assertEqual(
            _translated_blocks_for(article, ["之前。", "之后。"]),
            [
                {"type": "paragraph", "text": "之前。"},
                {
                    "type": "video",
                    "provider": "youtube",
                    "url": "https://www.youtube-nocookie.com/embed/xJ94HFpGM4Y",
                    "title": "Overview",
                },
                {"type": "paragraph", "text": "之后。"},
            ],
        )

    def test_social_embed_survives_the_translation_round_trip(self):
        social = {
            "type": "social_embed",
            "provider": "x",
            "url": "https://x.com/Kimi_Moonshot/status/2077521842080817296",
            "author_name": "Kimi.ai",
            "username": "Kimi_Moonshot",
            "video_url": "https://video.twimg.com/media/demo.mp4",
            "video_mime_type": "video/mp4",
            "like_count": 11466,
        }
        article = RawArticle(
            id="latent-social",
            source_id="latent_space",
            source_name="Latent Space",
            source_role="context",
            source_tier="T2",
            source_url="https://www.latent.space/p/example",
            title="Example",
            content="Before.\n\nAfter.",
            author="Latent Space",
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={
                "original_blocks": [
                    {"type": "paragraph", "text": "Before."},
                    social,
                    {"type": "paragraph", "text": "After."},
                ]
            },
            title_hash="latent-social-title",
            url_hash="latent-social-url",
        )

        self.assertEqual(
            _translated_blocks_for(article, ["之前。", "之后。"]),
            [
                {"type": "paragraph", "text": "之前。"},
                social,
                {"type": "paragraph", "text": "之后。"},
            ],
        )

    def test_google_blog_code_blocks_are_preserved_without_translation(self):
        article = RawArticle(
            id="google-code",
            source_id="google_ai_blog",
            source_name="Google AI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://blog.google/innovation-and-ai/example",
            title="Managed Agents",
            content="Before.\n\nconst enabled = true;\n\nAfter.",
            author="Google",
            published_at=datetime(2026, 7, 7, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={
                "original_blocks": [
                    {"type": "paragraph", "text": "Before."},
                    {
                        "type": "code",
                        "language": "ts",
                        "text": "const enabled = true;",
                    },
                    {"type": "paragraph", "text": "After."},
                ]
            },
            title_hash="google-code-title",
            url_hash="google-code-url",
        )

        self.assertEqual(_translation_paragraphs_for(article), ["Before.", "After."])
        self.assertEqual(
            _translated_blocks_for(article, ["之前。", "之后。"]),
            [
                {"type": "paragraph", "text": "之前。"},
                {"type": "code", "text": "const enabled = true;", "language": "ts"},
                {"type": "paragraph", "text": "之后。"},
            ],
        )

    def test_translate_in_chunks_bounds_each_call_and_preserves_order(self):
        calls: list[list[str]] = []

        def translate(paragraphs):
            calls.append(paragraphs)
            return [f"译:{p}" for p in paragraphs]

        paragraphs = [f"{'x' * 500}-{index}" for index in range(6)]  # ~3000 chars total

        translated = _translate_in_chunks(translate, paragraphs, chunk_char_limit=1200)

        self.assertEqual(translated, [f"译:{p}" for p in paragraphs])
        self.assertGreater(len(calls), 1)
        for call in calls:
            self.assertLessEqual(sum(len(p) for p in call), 1200)

    def test_translate_in_chunks_splits_oversized_paragraph_and_rejoins(self):
        calls: list[list[str]] = []

        def translate(paragraphs):
            calls.append(paragraphs)
            return [f"[{p[:6]}]" for p in paragraphs]

        oversized = "Sentence one is long. " * 60  # ~1320 chars, sentence boundaries
        translated = _translate_in_chunks(translate, ["short", oversized], chunk_char_limit=600)

        self.assertEqual(len(translated), 2)  # rejoined into one paragraph per input
        for call in calls:
            self.assertLessEqual(sum(len(p) for p in call), 600)
        self.assertGreaterEqual(len(calls), 3)

    def test_translate_in_chunks_splits_boundaryless_oversized_paragraph(self):
        def translate(paragraphs):
            for p in paragraphs:
                if len(p) > 600:
                    raise ValueError("truncated")
            return [f"译{len(p)}" for p in paragraphs]

        oversized = "y" * 2000  # no sentence boundary at all
        translated = _translate_in_chunks(translate, [oversized], chunk_char_limit=600)

        self.assertEqual(len(translated), 1)

    def test_translate_in_chunks_retries_a_transiently_failing_chunk_once(self):
        # 真实案例：正文变长后一篇长文章要拆成十几次调用，其中一次偶发
        # "Chat response content is empty" 就会让全篇翻译作废。单次瞬时
        # 失败应该重试一次，而不是让整篇长文章白翻译。
        attempts: list[list[str]] = []

        def translate(paragraphs):
            attempts.append(paragraphs)
            if len(attempts) == 2:  # second chunk's first attempt fails
                raise RuntimeError("Chat response content is empty")
            return [f"译:{p}" for p in paragraphs]

        from unittest.mock import patch as mock_patch

        with mock_patch("app.pipeline.runner.time.sleep"):
            translated = _translate_in_chunks(
                translate, ["first chunk", "second chunk"], chunk_char_limit=20
            )

        self.assertEqual(translated, ["译:first chunk", "译:second chunk"])
        self.assertEqual(len(attempts), 3)  # chunk1, chunk2 (fails), chunk2 retry

    def test_translate_in_chunks_gives_up_after_retry_still_fails(self):
        def translate(paragraphs):
            raise RuntimeError("Chat response content is empty")

        from unittest.mock import patch as mock_patch

        with mock_patch("app.pipeline.runner.time.sleep"):
            with self.assertRaises(RuntimeError):
                _translate_in_chunks(translate, ["only chunk"], chunk_char_limit=20)

    def test_translate_in_chunks_falls_back_to_smaller_requests_after_retry(self):
        attempts: list[list[str]] = []

        def translate(paragraphs):
            attempts.append(paragraphs)
            if sum(len(paragraph) for paragraph in paragraphs) > 800:
                raise ValueError("Chat response was not valid JSON: truncated")
            return [f"译:{paragraph}" for paragraph in paragraphs]

        paragraphs = ["first " * 100, "second " * 100]
        from unittest.mock import patch as mock_patch

        with mock_patch("app.pipeline.runner.time.sleep"):
            translated = _translate_in_chunks(
                translate, paragraphs, chunk_char_limit=1600
            )

        self.assertEqual(translated, [f"译:{paragraph}" for paragraph in paragraphs])
        self.assertEqual(attempts[:2], [paragraphs, paragraphs])
        self.assertEqual(attempts[2:], [[paragraphs[0]], [paragraphs[1]]])

    def test_translate_in_chunks_backs_off_before_retrying(self):
        # 真实案例：一次刷新里 3 篇长文章的翻译全都撞上同一个
        # "Chat response content is empty"，说明大概率是短时间内大量顺序
        # 调用触发的限流/过载，立即重试大概率还是会撞上同一限流窗口；
        # 重试前应该先等一下，而不是无延迟立刻打第二次请求。
        from unittest.mock import patch as mock_patch

        def translate(paragraphs):
            if not translate.failed_once:
                translate.failed_once = True
                raise RuntimeError("Chat response content is empty")
            return [f"译:{p}" for p in paragraphs]

        translate.failed_once = False

        with mock_patch("app.pipeline.runner.time.sleep") as mock_sleep:
            translated = _translate_in_chunks(translate, ["only chunk"], chunk_char_limit=20)

        self.assertEqual(translated, ["译:only chunk"])
        mock_sleep.assert_called_once()
        self.assertGreater(mock_sleep.call_args[0][0], 0)

    def test_pipeline_translates_long_articles_through_chunked_calls(self):
        source = Source(
            id="anthropic_news",
            name="Anthropic News",
            source_role="authority",
            tier="T1",
            type="sitemap",
            category="official",
            url="https://www.anthropic.com/sitemap.xml",
            homepage="https://www.anthropic.com/news",
            allowed_domains=["anthropic.com"],
            can_be_main_source=True,
        )
        long_blocks = [
            {"type": "paragraph", "text": f"AI model paragraph {index} " + "detail " * 60}
            for index in range(12)
        ]
        raw_items = [
            {
                "source_url": "https://www.anthropic.com/news/long-post",
                "title": "OpenAI and Anthropic release new AI agent model",
                "content": "A long AI article.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"original_blocks": long_blocks},
            }
        ]

        class TokenLimitedProvider(FakeAIProvider):
            """Mimics a provider whose responses truncate beyond ~1600 input chars."""

            def translate_paragraphs(self, paragraphs):
                if sum(len(p) for p in paragraphs) > 1600:
                    raise ValueError("Chat response was not valid JSON: truncated")
                return [f"译:{p[:20]}" for p in paragraphs]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"anthropic_news": raw_items},
            ai_provider=TokenLimitedProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
        )

        article = result.raw_articles[0]
        translated = article.metadata.get("translated_paragraphs") or []
        self.assertEqual(len(translated), 12)
        self.assertNotIn("translation_status", article.metadata)

    def test_translation_failure_is_logged_and_stays_self_healing(self):
        # a translation failure must still leave the article retriable on
        # the next pipeline run (no translated_* written, has_translation
        # stays False) - the only change is that it's no longer silent, so
        # operators can see why a given refresh left some articles without
        # a 原文/译文 toggle
        source = Source(
            id="anthropic_news",
            name="Anthropic News",
            source_role="authority",
            tier="T1",
            type="sitemap",
            category="official",
            url="https://www.anthropic.com/sitemap.xml",
            homepage="https://www.anthropic.com/news",
            allowed_domains=["anthropic.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://www.anthropic.com/news/broken-translation",
                "title": "OpenAI and Anthropic release new AI agent model",
                "content": "A short AI article.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
        ]

        class AlwaysFailingProvider(FakeAIProvider):
            def translate_paragraphs(self, paragraphs):
                raise ValueError("provider rate limited")

        with self.assertLogs("app.pipeline.runner", level="WARNING") as logs:
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={"anthropic_news": raw_items},
                ai_provider=AlwaysFailingProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
            )

        article = result.raw_articles[0]
        self.assertEqual(article.metadata.get("translation_status"), "failed")
        self.assertNotIn("translated_paragraphs", article.metadata)
        self.assertNotIn("translation_source_hash", article.metadata)
        self.assertTrue(any("translation failed" in message for message in logs.output))

    def test_translation_is_not_capped_at_twelve_paragraphs_for_long_articles(self):
        # 真实案例：HuggingFace 一篇 97 段的长文章之前只有前 12 段（大多是
        # 小标题）译文，正文完全没翻译。段落数上限已经和字符总量控制重复，
        # 应该只用字符总量约束，不应该再叠加一个段落数硬上限。
        source = Source(
            id="huggingface_blog",
            name="Hugging Face Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://huggingface.co/blog/feed.xml",
            homepage="https://huggingface.co/blog",
            allowed_domains=["huggingface.co"],
            can_be_main_source=True,
        )
        # 40 段短段落（每段远小于字符上限），总量远低于 TRANSLATION_CHAR_LIMIT
        many_short_blocks = [
            {"type": "paragraph", "text": f"Paragraph {index} about attention profiling."}
            for index in range(40)
        ]
        raw_items = [
            {
                "source_url": "https://huggingface.co/blog/torch-attention-profile",
                "title": "Profiling in PyTorch (Part 3)",
                "content": "profiling article",
                "author": "hf",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"original_blocks": many_short_blocks},
            }
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"huggingface_blog": raw_items},
            ai_provider=TranslatingAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
        )

        translated = result.raw_articles[0].metadata.get("translated_paragraphs") or []
        self.assertEqual(len(translated), 40)

    # 注：原 test_below_threshold_article_with_only_title_as_content_still_gets_translated
    # 编码的是 2026-07-11 上午的旧决策（标题-only 文章仍展示并翻译）。当天下午
    # 产品决策反转：无正文的文章在任何 AI 调用前直接跳过、不再收录——见
    # test_title_only_articles_are_skipped_without_any_ai_call。

    def test_readme_enrichment_retries_when_zh_probe_failed(self):
        # 限流时降级存下的英文 README 会带 readme_zh_probe=failed 标记，
        # 下一轮必须重试（限流窗口已过就能换成中文版），而不是永久固化英文。
        from app.models.domain import RawArticle
        from app.pipeline.runner import _attach_github_readmes

        def github_article(article_id, repo, zh_probe):
            return RawArticle(
                id=article_id,
                source_id="github_trending_ai",
                source_name="GitHub Trending",
                source_role="signal",
                source_tier="T2",
                source_url=f"https://github.com/{repo}",
                title=f"GitHub Trending: {repo}",
                content="desc",
                author=None,
                published_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                language="en",
                raw_score={},
                metadata={
                    "source_type": "github_trending",
                    "repo": repo,
                    "readme_status": "ok",
                    "readme_language": "en",
                    "readme_zh_probe": zh_probe,
                },
                title_hash=f"th-{article_id}",
                url_hash=f"uh-{article_id}",
            )

        stale = github_article("g1", "tencent/example", "failed")
        settled = github_article("g2", "other/repo", "none")
        # 修复前入库的老数据没有 zh_probe 字段，同样要重试自愈
        legacy = github_article("g3", "legacy/repo", "none")
        del legacy.metadata["readme_zh_probe"]
        fetched = []

        def fake_fetch(repo_path, github_token=None):
            fetched.append(repo_path)
            return {
                "readme_status": "ok",
                "readme_language": "zh",
                "readme_selection": "preferred_zh_readme",
                "readme_zh_probe": "ok",
            }

        with patch("app.pipeline.runner.fetch_github_readme", side_effect=fake_fetch):
            _attach_github_readmes(articles=[stale, settled, legacy])

        self.assertEqual(fetched, ["tencent/example", "legacy/repo"])
        self.assertEqual(stale.metadata["readme_language"], "zh")
        self.assertEqual(settled.metadata["readme_language"], "en")
        self.assertEqual(legacy.metadata["readme_language"], "zh")

    def test_readme_enrichment_covers_unselected_github_articles(self):
        source = Source(
            id="github_trending_ai",
            name="GitHub Trending AI",
            source_role="signal",
            tier="T2",
            type="github",
            category="community",
            url="https://github.com/trending?since=daily",
            homepage="https://github.com/trending",
            allowed_domains=["github.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://github.com/example/hot-repo",
                "title": "GitHub Trending: example / hot-repo",
                "content": "An AI agent framework.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"source_type": "github_trending", "repo": "example/hot-repo"},
            },
            {
                "source_url": "https://github.com/example/small-repo",
                "title": "GitHub Trending: example / small-repo",
                "content": "A tiny AI helper library.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"source_type": "github_trending", "repo": "example/small-repo"},
            },
        ]

        class LowScoreProvider(FakeAIProvider):
            """small-repo scores below every threshold so it is never selected."""

            def score_article(self, title, content):
                result = super().score_article(title, content)
                if "small-repo" in title:
                    from dataclasses import replace as dc_replace

                    return dc_replace(
                        result,
                        dimensions=ContentValueDimensions(impact=2, novelty=2, substance=2),
                    )
                return result

        fetched: list[str] = []

        def fake_fetch_readme(repo_path):
            fetched.append(repo_path)
            return {
                "readme_status": "ok",
                "readme_language": "en",
                "original_markdown": f"# {repo_path}",
            }

        from unittest.mock import patch as mock_patch

        with mock_patch(
            "app.pipeline.runner.fetch_github_readme", side_effect=fake_fetch_readme
        ):
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={"github_trending_ai": raw_items},
                ai_provider=LowScoreProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                top_n=1,
            )

        # both repos get READMEs, including the low-score one outside the report
        self.assertEqual(sorted(fetched), ["example/hot-repo", "example/small-repo"])
        small = next(a for a in result.raw_articles if "small-repo" in a.title)
        self.assertEqual(small.metadata.get("original_markdown"), "# example/small-repo")

    def test_readme_enrichment_covers_github_links_from_non_github_sources(self):
        # 真实案例：一篇 Hacker News "Show HN" 帖子直接链到 GitHub 仓库
        # （source_id=hacker_news，不是 github_trending_ai），README 富化
        # 之前只认 github_trending_ai 信源，这类文章完全没有 README。
        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://github.com/kiliczsh/genui",
                "title": "Show HN: GenUI, native SwiftUI interfaces generated by AI agents",
                "content": "GenUI generates native SwiftUI interfaces.",
                "author": "hn",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {"points": 50, "comments": 10},
                "metadata": {"hn_object_id": "1"},
            },
        ]

        fetched: list[str] = []

        def fake_fetch_readme(repo_path):
            fetched.append(repo_path)
            return {
                "readme_status": "ok",
                "readme_language": "en",
                "original_markdown": f"# {repo_path}",
            }

        from unittest.mock import patch as mock_patch

        with mock_patch(
            "app.pipeline.runner.fetch_github_readme", side_effect=fake_fetch_readme
        ):
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={"hacker_news": raw_items},
                ai_provider=FakeAIProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                top_n=1,
            )

        self.assertEqual(fetched, ["kiliczsh/genui"])
        article = result.raw_articles[0]
        self.assertEqual(article.metadata.get("original_markdown"), "# kiliczsh/genui")

    def test_stale_cached_translation_is_replaced_when_content_upgrades(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        # fresh crawl now carries the full article body
        raw_items = [
            {
                "source_url": "https://openai.com/index/big-news",
                "title": "OpenAI ships new agent model",
                "content": "Full body. " * 60,
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {
                    "original_blocks": [
                        {"type": "paragraph", "text": f"AI paragraph {i} with details."}
                        for i in range(6)
                    ]
                },
            }
        ]

        from app.crawlers.base import canonicalize_url, stable_hash

        url_hash = stable_hash(canonicalize_url("https://openai.com/index/big-news"))
        cached_results = {
            url_hash: {
                "scoring": None,
                "skipped_reason": None,
                # translation of the OLD thin one-line description, no source hash
                "metadata": {
                    "translated_paragraphs": ["旧的单段译文。"],
                    "translated_blocks": [{"type": "paragraph", "text": "旧的单段译文。"}],
                },
            }
        }

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
            cached_results=cached_results,
        )

        article = result.raw_articles[0]
        translated = article.metadata.get("translated_paragraphs") or []
        # stale single-paragraph translation must be replaced by a fresh
        # translation covering the full body
        self.assertEqual(len(translated), 6)
        self.assertNotIn("旧的单段译文。", translated)
        self.assertTrue(article.metadata.get("translation_source_hash"))

    def test_cached_translation_with_matching_hash_is_reused(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        blocks = [
            {"type": "paragraph", "text": "AI paragraph 0 with details."},
            {
                "type": "image",
                "url": "https://openai.com/current-image.png",
                "alt": "Current image",
            },
            {"type": "paragraph", "text": "AI paragraph 1 with details."},
            {"type": "paragraph", "text": "AI paragraph 2 with details."},
        ]
        raw_items = [
            {
                "source_url": "https://openai.com/index/same-news",
                "title": "OpenAI ships new agent model",
                "content": "Full body. " * 60,
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {"original_blocks": blocks},
            }
        ]

        from app.crawlers.base import canonicalize_url, stable_hash
        from app.pipeline.runner import translation_source_hash

        url_hash = stable_hash(canonicalize_url("https://openai.com/index/same-news"))
        source_hash = translation_source_hash(
            [str(b["text"]) for b in blocks if b["type"] == "paragraph"]
        )
        cached_results = {
            url_hash: {
                "scoring": None,
                "skipped_reason": None,
                "metadata": {
                    "translated_paragraphs": ["缓存译文一", "缓存译文二", "缓存译文三"],
                    "translated_blocks": [
                        {"type": "paragraph", "text": "缓存译文一"},
                        {
                            "type": "image",
                            "url": "https://expired-proxy.example/old-image.png",
                            "alt": "Old image",
                        },
                        {"type": "paragraph", "text": "缓存译文二"},
                        {"type": "paragraph", "text": "缓存译文三"},
                    ],
                    "translation_source_hash": source_hash,
                },
            }
        }

        class NoTranslateProvider(FakeAIProvider):
            def translate_paragraphs(self, paragraphs):
                raise AssertionError("translation must not be called on hash match")

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=NoTranslateProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=12,
            cached_results=cached_results,
        )

        article = result.raw_articles[0]
        self.assertEqual(
            article.metadata.get("translated_paragraphs"),
            ["缓存译文一", "缓存译文二", "缓存译文三"],
        )
        self.assertEqual(
            article.metadata.get("translated_blocks"),
            [
                {"type": "paragraph", "text": "缓存译文一"},
                {
                    "type": "image",
                    "url": "https://openai.com/current-image.png",
                    "alt": "Current image",
                },
                {"type": "paragraph", "text": "缓存译文二"},
                {"type": "paragraph", "text": "缓存译文三"},
            ],
        )

    def test_pipeline_isolates_single_article_ai_failures(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://openai.com/good",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases a new AI agent model for developers.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/poison",
                "title": "Anthropic AI safety research update",
                "content": "AI safety research update triggers a provider glitch.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
        ]

        class FlakyProvider(FakeAIProvider):
            def score_article(self, title, content):
                if "safety" in title.lower():
                    raise ValueError("Chat response was not valid JSON")
                return super().score_article(title, content)

        for concurrency in [1, 4]:
            with self.subTest(concurrency=concurrency):
                result = run_pipeline(
                    sources=[source],
                    raw_items_by_source={"openai_blog": raw_items},
                    ai_provider=FlakyProvider(),
                    now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                    report_date=date(2026, 7, 1),
                    top_n=12,
                    ai_concurrency=concurrency,
                )

                self.assertEqual(result.skipped_reasons["ai_error"], 1)
                self.assertEqual(len(result.processed_articles), 1)
                poison = next(
                    article
                    for article in result.raw_articles
                    if article.source_url.endswith("/poison")
                )
                self.assertEqual(poison.status, "skipped")
                self.assertEqual(poison.skipped_reason, "ai_error")

    def test_embedding_failure_keeps_plain_source_as_standalone_selected_event(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://openai.com/embedding-outage",
                "title": "OpenAI releases a new agent model",
                "content": "OpenAI released a major AI agent model with new developer capabilities.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {},
            }
        ]

        class EmbeddingFailureProvider(FakeAIProvider):
            def score_article(self, title, content):
                return ScoringResult(
                    ai_focus="primary",
                    dimensions=ContentValueDimensions(impact=8, novelty=8, substance=8),
                    category="model_release",
                    tags=["Agent"],
                    title_zh="OpenAI 发布新智能体模型",
                    one_line_summary="OpenAI 发布面向开发者的新智能体模型。",
                    summary_zh="OpenAI 发布了具备新开发能力的智能体模型。",
                    reason_zh="这是一次重要模型发布。",
                    action_zh="阅读发布说明。",
                )

            def embed_text(self, text, dimensions=512):
                raise OSError("embedding model unavailable")

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: raw_items},
            ai_provider=EmbeddingFailureProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertNotIn("ai_error", result.skipped_reasons)
        self.assertEqual(result.embeddings, {})
        self.assertEqual(len(result.processed_articles), 1)
        processed = result.processed_articles[0]
        self.assertTrue(processed.selected)
        self.assertEqual(processed.status, "processed")
        self.assertEqual(len(result.event_clusters), 1)
        self.assertEqual(result.event_clusters[0].article_ids, [processed.raw_article_id])
        self.assertEqual(result.daily_report.article_count, 1)
        article = result.raw_articles[0]
        self.assertEqual(article.metadata["ai_fallback"], "embedding_error")
        self.assertIn("OSError: embedding model unavailable", article.metadata["embedding_error"])

    def test_embedding_failure_keeps_below_threshold_article_for_all_feed(self):
        source = Source(
            id="media",
            name="AI Media",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://media.example/feed.xml",
            homepage="https://media.example",
            allowed_domains=["media.example"],
            can_be_main_source=True,
        )
        raw_items = [
            {
                "source_url": "https://media.example/minor-update",
                "title": "Minor AI product update",
                "content": "A small AI feature update with limited practical impact.",
                "author": "AI Media",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {},
            }
        ]

        class LowScoreEmbeddingFailureProvider(FakeAIProvider):
            def score_article(self, title, content):
                return ScoringResult(
                    ai_focus="contributing",
                    dimensions=ContentValueDimensions(impact=3, novelty=3, substance=2.67),
                    category="product_release",
                    tags=["AI 产品"],
                    title_zh="一项小型 AI 产品更新",
                    one_line_summary="该产品增加了一项较小的 AI 功能。",
                    summary_zh="这是一项影响范围有限的 AI 产品功能更新。",
                    reason_zh="可作为产品动态了解。",
                    action_zh="按需查看详情。",
                )

            def embed_text(self, text, dimensions=512):
                raise RuntimeError("embedding service down")

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: raw_items},
            ai_provider=LowScoreEmbeddingFailureProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertNotIn("ai_error", result.skipped_reasons)
        self.assertEqual(len(result.processed_articles), 1)
        processed = result.processed_articles[0]
        self.assertFalse(processed.selected)
        self.assertEqual(processed.status, "rejected")
        self.assertTrue(processed.rejection_reason.startswith("final_score:"))
        # /all is sourced from processed_articles, including rejected rows.
        # Keeping this row is the public-dynamics visibility boundary.
        self.assertEqual(len(result.event_clusters), 1)
        self.assertEqual(result.event_clusters[0].article_ids, [processed.raw_article_id])
        self.assertEqual(result.daily_report.article_count, 0)
        article = result.raw_articles[0]
        self.assertNotEqual(article.status, "skipped")
        self.assertEqual(article.metadata["ai_fallback"], "embedding_error")

    def test_pipeline_does_not_fill_report_from_below_threshold_candidates(self):
        source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
        )
        raw_items = [
            {
                "source_url": f"https://example.com/{index}",
                "title": f"AI agent workflow update {index}",
                "content": "AI agent workflow update for builders.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(3)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"hn": raw_items},
            ai_provider=LowScoreAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=2,
        )

        self.assertEqual(result.skipped_reasons["final_score"], 3)
        self.assertEqual(len([item for item in result.processed_articles if item.selected]), 0)
        self.assertEqual(result.daily_report.article_count, 0)
        self.assertEqual(len(result.daily_report.json_data["items"]), 0)

    def test_pipeline_can_skip_prefilter_and_score_every_candidate(self):
        source = Source(
            id="mixed",
            name="Mixed Feed",
            source_role="signal",
            tier="T2",
            type="rss",
            category="community",
            url="https://example.com/feed",
            homepage="https://example.com",
            allowed_domains=["example.com"],
        )
        raw_items = [
            {
                "source_url": f"https://example.com/{index}",
                "title": f"General update {index}",
                "content": "This item has no explicit AI keyword.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(3)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"mixed": raw_items},
            ai_provider=NonAiPrefilterProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=3,
            skip_prefilter=True,
        )

        self.assertEqual(len(result.processed_articles), 3)
        self.assertEqual(result.daily_report.article_count, 3)
        self.assertNotIn("not_ai_related", result.skipped_reasons)

    def test_pipeline_can_process_ai_candidates_concurrently(self):
        source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
        )
        raw_items = [
            {
                "source_url": f"https://example.com/concurrent-{index}",
                "title": f"AI agent concurrent update {index}",
                "content": "AI agent workflow update for builders.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(4)
        ]
        provider = SlowConcurrentAIProvider()

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"hn": raw_items},
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=4,
            ai_concurrency=4,
        )

        self.assertGreater(provider.max_active, 1)
        self.assertEqual(result.daily_report.article_count, 4)

    def test_translation_phase_runs_concurrently_like_scoring(self):
        # 真实案例：一次刷新耗时 26 分钟——打分阶段有 ai_concurrency 并发，
        # 翻译阶段是纯顺序 for 循环。现在每篇 processed 文章都要翻译（不只
        # 日报入选的12篇），文章数量和单篇上限都提高后，顺序执行是主要
        # 耗时来源，应该复用同一个 ai_concurrency 并发。
        source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
        )
        raw_items = [
            {
                "source_url": f"https://example.com/translate-concurrent-{index}",
                "title": f"AI agent concurrent update {index}",
                "content": "AI agent workflow update for builders with plenty of detail.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(4)
        ]
        provider = SlowConcurrentTranslateOnlyProvider()

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"hn": raw_items},
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=4,
            ai_concurrency=4,
        )

        # isolates the translation phase specifically (scoring/prefilter are
        # instant in this provider) so this can't pass just because scoring
        # already happens to be concurrent
        self.assertGreater(provider.max_active, 1)
        for article in result.raw_articles:
            self.assertTrue(article.metadata.get("translated_paragraphs"))

    def test_pipeline_translates_all_processed_english_articles(self):
        english_source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
            language="en",
        )
        chinese_source = Source(
            id="ithome",
            name="IT之家",
            source_role="media",
            tier="T3",
            type="rss",
            category="media",
            url="https://www.ithome.com/rss/",
            homepage="https://www.ithome.com",
            allowed_domains=["ithome.com"],
            language="zh",
        )
        raw_items = {
            "hn": [
                {
                    "source_url": "https://example.com/english-ai-agent",
                    "title": "AI agent audit finds seven bugs",
                    "content": "AI agents found security bugs.\nDevelopers verified the fixes.",
                    "author": "HN",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "original_blocks": [
                            {"type": "paragraph", "text": "AI agents found security bugs."},
                            {
                                "type": "image",
                                "url": "https://example.com/audit.png",
                                "alt": "Audit diagram",
                                "caption": "",
                            },
                            {"type": "paragraph", "text": "Developers verified the fixes."},
                        ]
                    },
                },
                {
                    "source_url": "https://example.com/second-agent",
                    "title": "AI agent workflow update",
                    "content": "AI workflow update for builders.",
                    "author": "HN",
                    "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {},
                },
            ],
            "ithome": [
                {
                    "source_url": "https://ithome.com/ai",
                    "title": "AI 公司发布新工具",
                    "content": "这是一条中文 AI 新闻。",
                    "author": "IT之家",
                    "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                    "language": "zh",
                    "raw_score": {},
                    "metadata": {},
                }
            ],
        }
        provider = TranslatingAIProvider()

        result = run_pipeline(
            sources=[english_source, chinese_source],
            raw_items_by_source=raw_items,
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            top_n=1,
        )

        item = result.daily_report.json_data["items"][0]
        # /all 页展示全部 processed 文章，未入选日报（top_n=1 之外）的英文
        # 文章同样要有译文，而不是只翻译日报主文
        self.assertEqual(
            provider.translation_calls,
            [
                ["AI agents found security bugs.", "Developers verified the fixes."],
                ["AI workflow update for builders."],
            ],
        )
        self.assertEqual(item["source_language"], "en")
        self.assertEqual(item["translated_paragraphs"], ["译文：AI agents found security bugs.", "译文：Developers verified the fixes."])
        self.assertEqual(item["translated_blocks"][1]["type"], "image")
        self.assertEqual(item["translated_blocks"][1]["url"], "https://example.com/audit.png")

        unselected = next(
            article
            for article in result.raw_articles
            if article.source_url == "https://example.com/second-agent"
        )
        self.assertEqual(
            unselected.metadata["translated_paragraphs"],
            ["译文：AI workflow update for builders."],
        )

    def test_pipeline_attaches_readme_to_all_processed_github_articles(self):
        github_source = Source(
            id="github_trending_ai",
            name="GitHub Trending AI",
            source_role="signal",
            tier="T2",
            type="github",
            category="community",
            url="https://github.com/trending?since=daily",
            homepage="https://github.com/trending",
            allowed_domains=["github.com"],
            language="en",
        )
        hn_source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
            language="en",
        )
        raw_items = {
            "github_trending_ai": [
                {
                    "source_url": "https://github.com/MadsLorentzen/ai-job-search",
                    "title": "AI selected readme project",
                    "content": "Short trending description.",
                    "author": "MadsLorentzen",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "repo": "MadsLorentzen/ai-job-search",
                        "source_type": "github_trending",
                    },
                },
                {
                    "source_url": "https://github.com/example/unselected-agent",
                    "title": "AI low priority repo project",
                    "content": "Another short description.",
                    "author": "example",
                    "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "repo": "example/unselected-agent",
                        "source_type": "github_trending",
                    },
                },
            ],
            "hn": [
                {
                    "source_url": "https://example.com/non-github-agent",
                    "title": "AI non github selected story",
                    "content": "A non GitHub story that should not fetch README.",
                    "author": "hn",
                    "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {},
                }
            ],
        }
        provider = ReadmeAwareAIProvider()
        readme_payload = {
            "readme_status": "ok",
            "readme_url": "https://raw.githubusercontent.com/MadsLorentzen/ai-job-search/main/README.md",
            "original_content": "AI Job Search\n\nFull README details for the project.",
            "original_markdown": "# AI Job Search\n\nFull README details for the project.",
            "original_paragraphs": ["AI Job Search", "Full README details for the project."],
            "original_blocks": [
                {"type": "paragraph", "text": "AI Job Search"},
                {"type": "paragraph", "text": "Full README details for the project."},
            ],
            "original_images": [],
        }

        with patch("app.pipeline.runner.fetch_github_readme", return_value=readme_payload) as fetch_readme:
            result = run_pipeline(
                sources=[github_source, hn_source],
                raw_items_by_source=raw_items,
                ai_provider=provider,
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                top_n=2,
            )

        # every processed github article gets a README (below-threshold ones
        # are still browsable via /all), non-github articles never do
        called_repos = sorted(call.args[0] for call in fetch_readme.call_args_list)
        self.assertEqual(
            called_repos, ["MadsLorentzen/ai-job-search", "example/unselected-agent"]
        )
        github_item = next(
            item for item in result.daily_report.json_data["items"]
            if item["original_url"] == "https://github.com/MadsLorentzen/ai-job-search"
        )
        self.assertEqual(github_item["original_paragraphs"], readme_payload["original_paragraphs"])
        self.assertEqual(github_item["original_markdown"], readme_payload["original_markdown"])
        self.assertNotIn("translated_paragraphs", github_item)
        self.assertNotIn("translated_blocks", github_item)
        github_article = next(
            article for article in result.raw_articles
            if article.source_url == "https://github.com/MadsLorentzen/ai-job-search"
        )
        self.assertEqual(github_article.metadata["repo_description"], "Short trending description.")
        self.assertEqual(github_article.metadata["readme_status"], "ok")
        self.assertEqual(provider.translation_calls, [["A non GitHub story that should not fetch README."]])

    def test_pipeline_skips_translation_for_selected_chinese_readme(self):
        github_source = Source(
            id="github_trending_ai",
            name="GitHub Trending AI",
            source_role="signal",
            tier="T2",
            type="github",
            category="community",
            url="https://github.com/trending?since=daily",
            homepage="https://github.com/trending",
            allowed_domains=["github.com"],
            language="en",
        )
        raw_items = {
            "github_trending_ai": [
                {
                    "source_url": "https://github.com/TencentCloud/TencentDB-Agent-Memory",
                    "title": "AI selected readme zh project",
                    "content": "Short trending description.",
                    "author": "TencentCloud",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "repo": "TencentCloud/TencentDB-Agent-Memory",
                        "source_type": "github_trending",
                    },
                }
            ],
        }
        provider = ReadmeAwareAIProvider()
        readme_payload = {
            "readme_status": "ok",
            "readme_url": "https://raw.githubusercontent.com/TencentCloud/TencentDB-Agent-Memory/main/README_CN.md",
            "readme_name": "README_CN.md",
            "readme_language": "zh",
            "readme_selection": "preferred_zh_readme",
            "original_content": "中文说明\n\n这是中文 README。",
            "original_markdown": "# 中文说明\n\n这是中文 README。",
            "original_paragraphs": ["中文说明", "这是中文 README。"],
            "original_blocks": [
                {"type": "paragraph", "text": "中文说明"},
                {"type": "paragraph", "text": "这是中文 README。"},
            ],
            "original_images": [],
        }

        with patch("app.pipeline.runner.fetch_github_readme", return_value=readme_payload):
            result = run_pipeline(
                sources=[github_source],
                raw_items_by_source=raw_items,
                ai_provider=provider,
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                top_n=1,
            )

        github_item = result.daily_report.json_data["items"][0]
        self.assertEqual(github_item["readme_name"], "README_CN.md")
        self.assertEqual(github_item["readme_language"], "zh")
        self.assertEqual(github_item["readme_selection"], "preferred_zh_readme")
        self.assertEqual(github_item["original_markdown"], "# 中文说明\n\n这是中文 README。")
        self.assertNotIn("translated_paragraphs", github_item)
        self.assertNotIn("translated_blocks", github_item)
        self.assertEqual(provider.translation_calls, [])


class FixedVectorAIProvider(FakeAIProvider):
    """Returns caller-specified embeddings keyed by a substring of the input
    text, so tests can pin an exact cosine similarity between two articles.
    Always marks content AI-related with a fixed score so selection into the
    report is deterministic regardless of the fixture title/content wording."""

    def __init__(self, vectors_by_marker: dict[str, list[float]]):
        self.vectors_by_marker = vectors_by_marker

    def embed_text(self, text: str, dimensions: int = 64) -> list[float]:
        for marker, vector in self.vectors_by_marker.items():
            if marker in text:
                return vector
        raise AssertionError(f"no fixture vector for text: {text!r}")

    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        return ScoringResult(
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=8, novelty=8, substance=7),
            category="model_release",
            tags=["AI"],
            title_zh=title,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content}",
            reason_zh="固定测试评分。",
            action_zh="阅读原文。",
        )


class LowScoreAIProvider(FakeAIProvider):
    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        return ScoringResult(
            ai_focus="contributing",
            dimensions=ContentValueDimensions(impact=5, novelty=5, substance=4.33),
            category="industry",
            tags=["AI"],
            title_zh=title,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content}",
            reason_zh="低分候选仍可用于补足完整成果。",
            action_zh="阅读原文后再判断。",
        )


class NonAiPrefilterProvider(FakeAIProvider):
    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=False, confidence=0.9, reason="fixture")


class SlowConcurrentAIProvider(FakeAIProvider):
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def _enter_call(self):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        with self.lock:
            self.active -= 1

    def prefilter(self, text: str) -> PrefilterResult:
        self._enter_call()
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        self._enter_call()
        return super().score_article(title, content)

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        self._enter_call()
        return super().translate_paragraphs(paragraphs)


class SlowConcurrentTranslateOnlyProvider(FakeAIProvider):
    """Only translate_paragraphs is slow/tracked; prefilter and scoring are
    instant, isolating the translation phase's own concurrency signal from
    the scoring phase's (already-proven) concurrency."""

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def translate_paragraphs(self, paragraphs: list[str]) -> list[str]:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        with self.lock:
            self.active -= 1
        return super().translate_paragraphs(paragraphs)


class TranslatingAIProvider(FakeAIProvider):
    def __init__(self):
        self.translation_calls = []

    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        score = 9 if "seven bugs" in title else 6
        return ScoringResult(
            ai_focus="primary" if score >= 9 else "contributing",
            dimensions=ContentValueDimensions(impact=score, novelty=score, substance=score),
            category="industry",
            tags=["AI"],
            title_zh=title,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content}",
            reason_zh="用于验证英文原文译文生成。",
            action_zh="对照阅读原文和译文。",
        )

    def translate_paragraphs(self, paragraphs):
        self.translation_calls.append(list(paragraphs))
        return [f"译文：{paragraph}" for paragraph in paragraphs]


class ReadmeAwareAIProvider(TranslatingAIProvider):
    def score_article(self, title: str, content: str) -> ScoringResult:
        if "selected readme" in title:
            score = 9
        elif "non github selected" in title:
            score = 8
        else:
            score = 5
        return ScoringResult(
            ai_focus="primary" if score >= 9 else "contributing",
            dimensions=ContentValueDimensions(impact=score, novelty=score, substance=score),
            category="industry",
            tags=["AI"],
            title_zh=title,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content}",
            reason_zh="用于验证 GitHub README 原文。",
            action_zh="对照阅读 README。",
        )


if __name__ == "__main__":
    unittest.main()
