import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"


class WebAppStructureTests(unittest.TestCase):
    def test_next_app_router_project_files_exist(self):
        expected_files = [
            "package.json",
            "next.config.ts",
            "postcss.config.mjs",
            "tsconfig.json",
            "app/globals.css",
            "app/layout.tsx",
            "app/icon.svg",
            "app/page.tsx",
            "app/latest/page.tsx",
            "app/admin/refresh-report-button.tsx",
            "app/admin/schedule-panel.tsx",
            "app/admin/page.tsx",
            "app/admin/login/page.tsx",
            "middleware.ts",
            "app/api/refresh-latest/route.ts",
            "app/all/page.tsx",
            "app/search/page.tsx",
            "app/daily/page.tsx",
            "app/daily/[date]/page.tsx",
            "app/daily/report-view.tsx",
            "app/daily/copy-markdown-button.tsx",
            "app/reports/report-shell.tsx",
            "app/reports/report-data.ts",
            "app/reports/period-report-page.tsx",
            "app/weekly/page.tsx",
            "app/monthly/page.tsx",
            "app/event/[id]/page.tsx",
            "app/event/[id]/article-reading-toggle.tsx",
            "lib/api.ts",
            "lib/events.ts",
            "lib/markdown.ts",
        ]

        for relative_path in expected_files:
            self.assertTrue((WEB / relative_path).exists(), relative_path)

    def test_package_declares_next_react_tailwind_and_scripts(self):
        package_json = json.loads((WEB / "package.json").read_text(encoding="utf-8"))

        self.assertEqual(package_json["scripts"]["dev"], "next dev")
        self.assertEqual(package_json["scripts"]["build"], "next build")
        self.assertEqual(package_json["scripts"]["typecheck"], "tsc --noEmit")
        self.assertIn("next", package_json["dependencies"])
        self.assertIn("react", package_json["dependencies"])
        self.assertIn("react-dom", package_json["dependencies"])
        self.assertIn("tailwindcss", package_json["devDependencies"])
        self.assertIn("@tailwindcss/postcss", package_json["devDependencies"])

    def test_latest_page_fetches_from_public_api_and_renders_core_fields(self):
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("/api/public/latest", api_source)
        self.assertIn("AI_RADAR_API_BASE_URL", api_source)
        self.assertIn("getLatestReport", latest_page)
        self.assertIn("推荐理由", latest_page)
        self.assertIn("当前热点", latest_page)
        self.assertIn("groupEventsByDate", latest_page)
        self.assertIn("<details", latest_page)
        self.assertIn('name="q"', latest_page)
        self.assertIn("搜索标题/摘要", latest_page)

    def test_latest_hotspots_come_from_dedicated_api_not_feed_slice(self):
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("/api/public/hotspots", api_source)
        self.assertIn("getHotspots", api_source)
        self.assertIn("getHotspots", latest_page)
        # the board must rank by the hotspot rule, not slice the feed
        self.assertNotIn("filteredItems.slice(0, 5)", latest_page)

    def test_latest_page_degrades_when_backend_api_is_unavailable(self):
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("emptyLatestReport", api_source)
        self.assertIn("API 服务暂时不可用", api_source)
        self.assertIn("catch (error)", api_source)
        self.assertIn("report.error", latest_page)
        self.assertIn("formatDateTime", latest_page)

    def test_latest_page_uses_shared_sidebar_with_reserved_menus(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        sidebar = (WEB / "components" / "sidebar.tsx").read_text(encoding="utf-8")
        nav = (WEB / "components" / "nav.ts").read_text(encoding="utf-8")

        self.assertIn("Sidebar", latest_page)
        self.assertIn("RadarStatus", latest_page)
        self.assertIn("AI·RADAR", sidebar)
        for label in ["精选", "全部 AI 动态", "AI 日报", "主题", "收藏", "Agent 接入", "关于", "更新日志", "反馈"]:
            self.assertIn(label, nav)
        self.assertIn('href: "/all"', nav)

    def test_admin_dashboard_exposes_refresh_report_button(self):
        button_source = (WEB / "app" / "admin" / "refresh-report-button.tsx").read_text(encoding="utf-8")
        dashboard_source = (WEB / "app" / "admin" / "page.tsx").read_text(encoding="utf-8")
        route_source = (WEB / "app" / "api" / "refresh-latest" / "route.ts").read_text(encoding="utf-8")

        self.assertIn("手动同步", button_source)
        # 2026-07-12 决策:总量由每源 crawl_limit 约束,同步请求不再携带全局上限
        self.assertNotIn("limit=", button_source)
        self.assertNotIn("top_n", button_source)
        self.assertIn("fetch(url", button_source)
        self.assertIn("pollRefreshJob", button_source)
        self.assertIn("Unexpected end of JSON input", button_source)
        self.assertIn("router.refresh", button_source)
        self.assertIn("useEffect", button_source)
        self.assertIn("elapsedSeconds", button_source)
        self.assertIn("同步中", button_source)
        self.assertIn("完成 ·", button_source)
        self.assertIn("失败 ·", button_source)
        self.assertNotIn("setMessage", button_source)
        self.assertIn("finished_at", dashboard_source)
        self.assertIn("formatDuration", dashboard_source)
        self.assertIn("结束", dashboard_source)
        self.assertIn("耗时", dashboard_source)
        self.assertIn("PipelineRunDetail", dashboard_source)
        self.assertIn("run.error", dashboard_source)
        self.assertIn("/api/admin/refresh-latest", route_source)
        self.assertIn("/api/admin/refresh-latest-async", route_source)
        self.assertIn("export async function GET", route_source)
        self.assertIn("searchParams", route_source)

    def test_admin_ledger_shows_ingest_metrics_not_cache_inflated_counts(self):
        # 台账漏斗口径(2026-07-12):抓取 = 重复 + 非AI(判定后直接丢弃,
        # 不入库) + 入库;精选 ⊂ 入库;历史行(NULL)显示 --;末列只保留
        # 信源明细,评分未达阈值属于入库的正常组成,不单独展示
        dashboard_source = (WEB / "app" / "admin" / "page.tsx").read_text(encoding="utf-8")

        for column in ["重复", "非AI", "入库", "精选", "信源明细"]:
            self.assertIn(column, dashboard_source)
        self.assertIn("new_raw_count", dashboard_source)
        self.assertIn("new_selected_count", dashboard_source)
        self.assertIn("non_ai_dropped_count", dashboard_source)
        self.assertIn("duplicate_count", dashboard_source)
        self.assertNotIn("AI 处理</th>", dashboard_source)
        self.assertNotIn("事件簇</th>", dashboard_source)
        self.assertNotIn("跳过说明", dashboard_source)
        self.assertNotIn("评分未达精选阈值", dashboard_source)
        self.assertNotIn("skippedReasonText", dashboard_source)
        self.assertNotIn("notAiCount", dashboard_source)

    def test_hover_card_stays_open_for_copying(self):
        # 悬浮卡(2026-07-12):鼠标移出触发区后延迟关闭,可移入卡片内
        # 选中复制——卡片不能是 pointer-events-none,且悬停卡片取消关闭
        ui_source = (WEB / "app" / "admin" / "ui.tsx").read_text(encoding="utf-8")

        self.assertIn("setTimeout", ui_source)
        self.assertIn("cancelHide", ui_source)
        self.assertNotIn("pointer-events-none", ui_source)
        self.assertIn("onMouseEnter", ui_source)
        for consumer in ["sources/sources-manager.tsx", "events/events-manager.tsx"]:
            consumer_source = (WEB / "app" / "admin" / Path(consumer)).read_text(encoding="utf-8")
            self.assertIn("cancelHide", consumer_source)

    def test_sources_manager_reflects_today_only_crawling(self):
        # 2026-07-12 深夜决策:每源条数配置停用,只处理当天发布——
        # UI 不再有 crawl_limit 输入与"每轮 N 条"文案
        manager_source = (
            WEB / "app" / "admin" / "sources" / "sources-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("仅当天发布", manager_source)
        self.assertNotIn("crawl_limit", manager_source)
        self.assertNotIn("每轮", manager_source)

    def test_sources_list_sorts_by_name_and_flags_official(self):
        # 信源管理(2026-07-12):列表按名称排序;官方信源带显眼"官方"标记
        manager_source = (
            WEB / "app" / "admin" / "sources" / "sources-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("sortedSources", manager_source)
        self.assertIn("localeCompare", manager_source)
        self.assertIn('source.category === "official"', manager_source)
        self.assertIn("官方", manager_source)

    def test_source_crawl_results_distinguish_duplicate_and_non_ai(self):
        # 信源明细(2026-07-12):判定标签必须区分 已存在/非AI/未达精选/异常,
        # 原因码要翻译成人话而不是原样输出 below_threshold:78
        manager_source = (
            WEB / "app" / "admin" / "sources" / "sources-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("outcomeLabel", manager_source)
        self.assertIn("formatVerdictReason", manager_source)
        for label in ["已存在", "非AI", "未达精选", "异常"]:
            self.assertIn(label, manager_source)
        self.assertIn("评分未达精选阈值", manager_source)
        self.assertIn("预筛判定与 AI 无关", manager_source)

    def test_admin_dashboard_exposes_schedule_panel(self):
        panel_source = (WEB / "app" / "admin" / "schedule-panel.tsx").read_text(encoding="utf-8")
        dashboard_page = (WEB / "app" / "admin" / "page.tsx").read_text(encoding="utf-8")
        proxy_route = (
            WEB / "app" / "api" / "admin-proxy" / "[...path]" / "route.ts"
        ).read_text(encoding="utf-8")

        self.assertIn("定时任务", panel_source)
        self.assertIn("/api/admin-proxy/schedule", panel_source)
        self.assertIn("interval_minutes", panel_source)
        self.assertIn("SchedulePanel", dashboard_page)
        self.assertIn("/api/admin/schedule", dashboard_page)
        self.assertIn("export async function PUT", proxy_route)

    def test_admin_content_manager_filters_by_configured_main_source(self):
        page = (WEB / "app" / "admin" / "events" / "page.tsx").read_text(encoding="utf-8")
        manager = (WEB / "app" / "admin" / "events" / "events-manager.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn('source_id?: string', page)
        self.assertIn('/api/admin/sources', page)
        self.assertIn('query.set("source_id"', page)
        self.assertIn('name="source_id"', manager)
        self.assertIn('全部主信源', manager)
        self.assertIn('params.set("source_id"', manager)

    def test_article_images_are_proxied_against_hotlink_protection(self):
        # 中文媒体 CDN 防盗链分两派：infoq（无 Referer 放行）和 qbitai
        # （白名单制，无 Referer 也 403）。浏览器无法伪造 Referer，所以
        # 文章图片统一走服务端代理，代理请求带图片自身 origin 作 Referer
        # （三家 CDN 实测均放行）。
        toggle = (WEB / "app" / "event" / "[id]" / "article-reading-toggle.tsx").read_text(
            encoding="utf-8"
        )
        detail = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        proxy_route = (WEB / "app" / "api" / "image-proxy" / "route.ts").read_text(
            encoding="utf-8"
        )
        helper = (WEB / "lib" / "images.ts").read_text(encoding="utf-8")

        self.assertIn("proxiedImageUrl", helper)
        self.assertIn("/api/image-proxy", helper)
        self.assertIn("Referer", proxy_route)
        self.assertIn("image/", proxy_route)
        for source, name in [(toggle, "article-reading-toggle"), (detail, "event detail page")]:
            self.assertIn("proxiedImageUrl", source, name)

    def test_latest_page_supports_category_filter_links(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("searchParams", latest_page)
        self.assertIn("selectedCategory", latest_page)
        self.assertIn("categoryOptions", latest_page)
        self.assertIn("filteredItems", latest_page)
        self.assertIn("latestHref", latest_page)
        self.assertIn('params.set("category", category)', latest_page)
        taxonomy = (WEB / "lib" / "taxonomy.ts").read_text(encoding="utf-8")
        self.assertIn('["", "全部"]', taxonomy)

    def test_daily_pages_fetch_public_daily_report_and_render_copy_controls(self):
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        daily_index = (WEB / "app" / "daily" / "page.tsx").read_text(encoding="utf-8")
        daily_date = (WEB / "app" / "daily" / "[date]" / "page.tsx").read_text(encoding="utf-8")
        report_view = (WEB / "app" / "daily" / "report-view.tsx").read_text(encoding="utf-8")
        copy_button = (WEB / "app" / "daily" / "copy-markdown-button.tsx").read_text(encoding="utf-8")
        markdown_source = (WEB / "lib" / "markdown.ts").read_text(encoding="utf-8")

        self.assertIn("/api/public/daily/", api_source)
        self.assertIn("getDailyReport", api_source)
        self.assertIn("getLatestReport", daily_index)
        self.assertIn("getDailyArchive", daily_index)
        self.assertIn("AI·RADAR 日报", daily_index)
        self.assertIn("今日看点", daily_index)
        self.assertIn("ReportShell", daily_index)
        self.assertIn("buildDailyDigest", daily_index)
        self.assertNotIn("CopyMarkdownButton", daily_index)  # moved off the daily view
        self.assertNotIn("redirect", daily_index)
        self.assertIn("params", daily_date)
        self.assertIn("DailyReportView", daily_date)
        self.assertIn("CopyMarkdownButton", report_view)
        self.assertIn("复制 Markdown", copy_button)
        self.assertIn("navigator.clipboard.writeText", copy_button)
        self.assertIn("buildDailyMarkdown", markdown_source)
        self.assertIn("按日期归档", report_view)
        self.assertIn("为什么重要", report_view)
        self.assertIn("下一步", report_view)

    def test_report_shell_exposes_aihot_sidebar_and_report_tabs(self):
        shell_source = (WEB / "app" / "reports" / "report-shell.tsx").read_text(encoding="utf-8")
        data_source = (WEB / "app" / "reports" / "report-data.ts").read_text(encoding="utf-8")

        self.assertIn("Sidebar", shell_source)
        self.assertIn("reportModeTabs", shell_source)
        self.assertIn("日报", shell_source)
        self.assertIn("周报", shell_source)
        self.assertIn("月报", shell_source)
        self.assertIn("href: \"/daily\"", shell_source)
        self.assertIn("href: \"/weekly\"", shell_source)
        self.assertIn("href: \"/monthly\"", shell_source)
        self.assertIn("activeNavId", shell_source)
        self.assertIn("buildDailyDigest", data_source)
        self.assertIn("summarizeCategoryHighlights", data_source)
        self.assertIn("buildPeriodDigest", data_source)

    def test_weekly_and_monthly_pages_render_aihot_period_reports(self):
        period_page = (WEB / "app" / "reports" / "period-report-page.tsx").read_text(encoding="utf-8")
        weekly_page = (WEB / "app" / "weekly" / "page.tsx").read_text(encoding="utf-8")
        monthly_page = (WEB / "app" / "monthly" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("ReportShell", period_page)
        self.assertIn("buildPeriodDigest", period_page)
        self.assertIn("getPeriodReport", period_page)

        for source, title, mode in [
            (weekly_page, "AI·RADAR 周报", "weekly"),
            (monthly_page, "AI·RADAR 月报", "monthly"),
        ]:
            self.assertIn(title, source)
            self.assertIn(f'mode="{mode}"', source)
            self.assertIn("本期主线", source)
            self.assertIn("本期看点", source)
            self.assertIn("本期主题", source)

        data_source = (WEB / "app" / "reports" / "report-data.ts").read_text(encoding="utf-8")
        self.assertIn("独立事件", data_source)
        self.assertIn("条精选", data_source)
        self.assertIn("阅读本页", data_source)

    def test_event_detail_page_links_from_latest_and_daily_views(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        report_view = (WEB / "app" / "daily" / "report-view.tsx").read_text(encoding="utf-8")
        event_page = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        reading_toggle = (
            WEB / "app" / "event" / "[id]" / "article-reading-toggle.tsx"
        ).read_text(encoding="utf-8")
        event_helpers = (WEB / "lib" / "events.ts").read_text(encoding="utf-8")
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("eventHref", latest_page)
        self.assertIn("eventHref", report_view)
        self.assertIn("findEventById", event_helpers)
        self.assertIn("getLatestReport", event_page)
        self.assertIn("notFound", event_page)
        self.assertIn("推荐理由", event_page)
        self.assertIn("AI 摘要", event_page)
        self.assertIn("原文", event_page)
        self.assertIn("阅读原文", event_page)
        self.assertIn("original_blocks", event_page)
        self.assertIn("original_paragraphs", event_page)
        self.assertIn("original_images", event_page)
        self.assertIn("original_markdown", event_page)
        self.assertIn("original_markdown?: string", api_source)
        self.assertIn("translated_blocks", api_source)
        self.assertIn("ArticleReadingToggle", event_page)
        self.assertIn("translatedBlocksFor", event_page)
        self.assertIn("Sidebar", event_page)
        self.assertIn("lg:grid-cols-[224px_1fr]", event_page)
        self.assertIn("lg:sticky", (WEB / "components" / "sidebar.tsx").read_text(encoding="utf-8"))
        self.assertIn("显示原文", reading_toggle)
        self.assertIn("显示译文", reading_toggle)
        self.assertIn("AI 翻译 · 中文", reading_toggle)
        self.assertIn("ReactMarkdown", reading_toggle)
        self.assertIn("remarkGfm", reading_toggle)
        self.assertIn("originalMarkdown", reading_toggle)
        self.assertIn("hasOriginalMarkdown", reading_toggle)
        self.assertIn("translatedBlocks.length > 0 && !hasOriginalMarkdown", reading_toggle)
        self.assertIn('hasOriginalMarkdown ? "original" : "translated"', reading_toggle)
        self.assertIn("readmeImageClassName", reading_toggle)
        self.assertIn("isReadmeInlineImage", reading_toggle)
        self.assertIn("readmeImageClassName({ src: block.url })", reading_toggle)
        self.assertIn("cleanTableElementProps", reading_toggle)
        self.assertIn("vAlign", reading_toggle)
        self.assertIn("tr({ node: _node, ...props })", reading_toggle)
        self.assertIn("cleanTableElementProps(props)", reading_toggle)
        self.assertIn("img.shields.io", reading_toggle)
        self.assertIn("inline-block h-auto w-auto max-w-full", reading_toggle)
        self.assertIn("block h-auto max-w-full", reading_toggle)
        self.assertIn("use client", reading_toggle)
        self.assertNotIn("返回最新情报", event_page)
        self.assertNotIn("报告正文", event_page)
        self.assertNotIn("时间线", event_page)
        self.assertNotIn("下一步", event_page)

    def test_all_page_renders_all_latest_events(self):
        all_page = (WEB / "app" / "all" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("getAllEvents", all_page)
        self.assertIn("eventHref", all_page)
        self.assertIn("全部 AI 动态", all_page)
        self.assertIn("AI 相关资讯全量信息流", all_page)
        self.assertIn("Sidebar", all_page)
        self.assertIn("精选", all_page)
        self.assertIn("sourceOptions", all_page)
        self.assertIn("一手信源", all_page)
        self.assertIn("资讯", all_page)
        self.assertIn("推文", all_page)
        self.assertIn("categoryOptions", all_page)
        self.assertIn("searchParams", all_page)
        self.assertIn("selectedSource", all_page)
        self.assertIn("selectedCategory", all_page)
        self.assertIn("searchEvents", all_page)
        self.assertIn('name="q"', all_page)
        self.assertIn("groupEventsByDate", all_page)
        self.assertIn("<details", all_page)
        self.assertIn("推荐理由", all_page)
        self.assertIn("评分", all_page)
        self.assertIn("来源", all_page)

    def test_search_page_filters_latest_events(self):
        search_page = (WEB / "app" / "search" / "page.tsx").read_text(encoding="utf-8")
        event_helpers = (WEB / "lib" / "events.ts").read_text(encoding="utf-8")

        self.assertIn("searchParams", search_page)
        self.assertIn("getLatestReport", search_page)
        self.assertIn("searchEvents", search_page)
        self.assertIn("eventHref", search_page)
        self.assertIn('name="q"', search_page)
        self.assertIn("搜索", search_page)
        self.assertIn("搜索结果", search_page)
        self.assertIn("searchEvents", event_helpers)

    def test_global_css_uses_tailwind_v4_import(self):
        globals_css = (WEB / "app" / "globals.css").read_text(encoding="utf-8")

        self.assertIn('@import "tailwindcss";', globals_css)

    def test_global_link_reset_is_layered_so_underline_utility_still_wins(self):
        # unlayered CSS always outranks Tailwind v4's utility layer regardless
        # of selector order - an un-@layer'd `a { text-decoration: none }`
        # silently defeats every `underline` utility class on every <a> site-
        # wide (confirmed with a real browser: computed text-decoration-line
        # stayed "none" despite the underline class being present).
        globals_css = (WEB / "app" / "globals.css").read_text(encoding="utf-8")

        import re

        match = re.search(r"a\s*\{[^}]*text-decoration:\s*none", globals_css)
        self.assertIsNotNone(match, "expected the global <a> text-decoration reset")
        preceding = globals_css[: match.start()]
        # nearest unclosed @layer before this rule must be "base"
        layer_opens = list(re.finditer(r"@layer\s+(\w+)\s*\{", preceding))
        self.assertTrue(layer_opens, "the <a> reset must be wrapped in @layer base")
        self.assertEqual(layer_opens[-1].group(1), "base")


if __name__ == "__main__":
    unittest.main()
