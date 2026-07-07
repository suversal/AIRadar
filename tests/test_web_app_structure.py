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
            "app/latest/refresh-report-button.tsx",
            "app/api/refresh-latest/route.ts",
            "app/all/page.tsx",
            "app/search/page.tsx",
            "app/daily/page.tsx",
            "app/daily/[date]/page.tsx",
            "app/daily/report-view.tsx",
            "app/daily/copy-markdown-button.tsx",
            "app/event/[id]/page.tsx",
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
        self.assertIn("RefreshReportButton", latest_page)
        self.assertIn("推荐理由", latest_page)
        self.assertIn("下一步", latest_page)

    def test_latest_page_exposes_refresh_report_button(self):
        button_source = (WEB / "app" / "latest" / "refresh-report-button.tsx").read_text(encoding="utf-8")
        route_source = (WEB / "app" / "api" / "refresh-latest" / "route.ts").read_text(encoding="utf-8")

        self.assertIn("刷新最新日报", button_source)
        self.assertIn("/api/refresh-latest?limit=100&top_n=12", button_source)
        self.assertIn("完整成果", button_source)
        self.assertIn("top_n=30", button_source)
        self.assertIn("fetch(url", button_source)
        self.assertIn("pollRefreshJob", button_source)
        self.assertIn("Unexpected end of JSON input", button_source)
        self.assertIn("router.refresh", button_source)
        self.assertIn("/api/admin/refresh-latest", route_source)
        self.assertIn("/api/admin/refresh-latest-async", route_source)
        self.assertIn("export async function GET", route_source)
        self.assertIn("searchParams", route_source)

    def test_latest_page_supports_category_filter_links(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("searchParams", latest_page)
        self.assertIn("selectedCategory", latest_page)
        self.assertIn("categoryOptions", latest_page)
        self.assertIn("filteredItems", latest_page)
        self.assertIn("?category=", latest_page)
        self.assertIn("全部分类", latest_page)

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
        self.assertIn("redirect", daily_index)
        self.assertIn("params", daily_date)
        self.assertIn("DailyReportView", daily_date)
        self.assertIn("CopyMarkdownButton", report_view)
        self.assertIn("复制 Markdown", copy_button)
        self.assertIn("navigator.clipboard.writeText", copy_button)
        self.assertIn("buildDailyMarkdown", markdown_source)
        self.assertIn("按日期归档", report_view)
        self.assertIn("为什么重要", report_view)
        self.assertIn("下一步", report_view)

    def test_event_detail_page_links_from_latest_and_daily_views(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        report_view = (WEB / "app" / "daily" / "report-view.tsx").read_text(encoding="utf-8")
        event_page = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        event_helpers = (WEB / "lib" / "events.ts").read_text(encoding="utf-8")

        self.assertIn("eventHref", latest_page)
        self.assertIn("eventHref", report_view)
        self.assertIn("findEventById", event_helpers)
        self.assertIn("getLatestReport", event_page)
        self.assertIn("notFound", event_page)
        self.assertIn("主来源", event_page)
        self.assertIn("相关来源", event_page)
        self.assertIn("时间线", event_page)
        self.assertIn("报告正文", event_page)
        self.assertIn("原文链接", event_page)
        self.assertIn("推荐理由", event_page)
        self.assertIn("下一步", event_page)

    def test_all_page_renders_all_latest_events(self):
        all_page = (WEB / "app" / "all" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("getLatestReport", all_page)
        self.assertIn("eventHref", all_page)
        self.assertIn("全部事件", all_page)
        self.assertIn("分类", all_page)
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


if __name__ == "__main__":
    unittest.main()
