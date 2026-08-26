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
            "app/telegram/page.tsx",
            "app/api/telegram-events/route.ts",
            "app/search/page.tsx",
            "app/daily/page.tsx",
            "app/reports/report-shell.tsx",
            "app/reports/report-data.ts",
            "app/reports/period-shared.tsx",
            "app/reports/weekly-report-page.tsx",
            "app/reports/monthly-report-page.tsx",
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
        # the date-grouped, infinite-scroll list (groupEventsByDate, <details>,
        # the per-card "推荐理由" line) lives in latest-events-feed.tsx /
        # event-card.tsx now - /latest's page.tsx only fetches the first page
        # and renders the filter chrome around the feed component
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(encoding="utf-8")
        event_card = (WEB / "components" / "event-card.tsx").read_text(encoding="utf-8")
        date_group = (WEB / "components" / "date-group-section.tsx").read_text(encoding="utf-8")

        self.assertIn("/api/public/latest", api_source)
        self.assertIn("AI_RADAR_API_BASE_URL", api_source)
        self.assertIn("getLatestReport", latest_page)
        self.assertIn("LatestEventsFeed", latest_page)
        self.assertIn("推荐理由", event_card)
        self.assertIn("当前热点", latest_page)
        self.assertIn("groupEventsByDate", latest_feed)
        self.assertIn("DateGroupSection", latest_feed)
        self.assertIn('aria-expanded={open}', date_group)
        self.assertIn("setOpen((value) => !value)", date_group)
        self.assertIn('name="q"', latest_page)
        self.assertIn("搜索标题/摘要", latest_page)

    def test_latest_hotspots_come_from_dedicated_api_not_feed_slice(self):
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("/api/public/hotspots", api_source)
        self.assertIn("getHotspots", api_source)
        self.assertIn("getHotspots", latest_page)
        self.assertIn("const HOTSPOT_LIMIT = 10", latest_page)
        self.assertIn("limit: HOTSPOT_LIMIT", latest_page)
        # the board must rank by the hotspot rule, not slice the feed
        self.assertNotIn("filteredItems.slice(0, 5)", latest_page)

    def test_latest_and_all_event_cards_share_the_same_source_line(self):
        event_card = (WEB / "components" / "event-card.tsx").read_text(encoding="utf-8")
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(encoding="utf-8")
        all_feed = (WEB / "components" / "all-events-feed.tsx").read_text(encoding="utf-8")

        self.assertIn('{item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源', event_card)
        for feed in [latest_feed, all_feed]:
            self.assertNotIn("function sourceLine", feed)
            self.assertNotIn("sourceLine=", feed)

    def test_changelog_describes_reader_visible_outcomes(self):
        changelog = (WEB / "app" / "changelog" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("移动端主题切换的展开与收起动画更加平滑", changelog)
        self.assertIn("来源名称 · N 个来源", changelog)
        for date in ["2026-08-21", "2026-08-25", "2026-08-26"]:
            self.assertIn(f'date: "{date}"', changelog)
        self.assertIn("中文译文会逐段核对原文结构", changelog)
        self.assertIn("信号绿、经典橙、雷达蓝和墨靛紫四套配色", changelog)
        self.assertIn("周报、月报在窄屏下不再被长标题和事件卡片撑出页面", changelog)
        for implementation_detail in ["六维加权", "三层判断", "T1/T1.5/T2/T3", "独立的入选分数线"]:
            self.assertNotIn(implementation_detail, changelog)

    def test_mobile_discovery_chrome_is_compact_and_preserves_filter_state(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        all_page = (WEB / "app" / "all" / "page.tsx").read_text(encoding="utf-8")
        mobile_discovery = (WEB / "components" / "mobile-discovery.tsx").read_text(encoding="utf-8")
        source_filter = (WEB / "components" / "mobile-source-filter.tsx").read_text(encoding="utf-8")

        for page in [latest_page, all_page]:
            self.assertIn("MobileSearchForm", page)
            self.assertIn("MobileCategoryNav", page)
            self.assertIn('name: "focus"', page)
            self.assertIn('name: "tag"', page)

        self.assertIn('name: "source"', all_page)
        self.assertIn('name: "topic"', all_page)
        self.assertIn("MobileSourceFilter", all_page)
        self.assertIn("overflow-x-auto", mobile_discovery)
        self.assertIn("const [hasOverflow, setHasOverflow] = useState(false)", mobile_discovery)
        self.assertIn("lastOption.offsetLeft + lastOption.offsetWidth - firstOption.offsetLeft", mobile_discovery)
        self.assertIn("contentWidth > nav.clientWidth + 1", mobile_discovery)
        self.assertIn("new ResizeObserver(updateOverflow)", mobile_discovery)
        self.assertIn('hasOverflow ? "pr-8" : ""', mobile_discovery)
        self.assertIn("{hasOverflow ? (", mobile_discovery)
        self.assertIn('aria-label="提交搜索"', mobile_discovery)
        self.assertIn('role="dialog"', source_filter)
        self.assertIn("全部来源", all_page)

    def test_mobile_theme_settings_live_inside_navigation_drawer(self):
        theme_toggle = (WEB / "components" / "theme-toggle.tsx").read_text(encoding="utf-8")
        theme_config = (WEB / "components" / "theme-config.ts").read_text(encoding="utf-8")
        mobile_nav = (WEB / "components" / "mobile-nav.tsx").read_text(encoding="utf-8")
        global_css = (WEB / "app" / "globals.css").read_text(encoding="utf-8")

        self.assertIn("MobileThemeSettings", theme_toggle)
        self.assertIn("MobileThemeSettings", mobile_nav)
        self.assertIn('aria-label="外观设置"', theme_toggle)
        self.assertIn('aria-label="明暗主题"', theme_toggle)
        self.assertIn('aria-label="主题色"', theme_toggle)
        self.assertIn("COLOR_PALETTES", theme_toggle)
        self.assertIn("PALETTE_STORAGE_KEY", theme_toggle)
        self.assertIn('DEFAULT_COLOR_PALETTE: ColorPalette = "instrument"', theme_config)
        self.assertIn('{ value: "instrument", label: "信号绿", swatch: "#147a4a" }', theme_config)
        self.assertLess(
            theme_config.index('{ value: "instrument"'),
            theme_config.index('{ value: "original"'),
        )
        self.assertIn("DEFAULT_COLOR_PALETTE", theme_toggle)
        self.assertIn("THEME_SETTINGS_CHANGE_EVENT", theme_toggle)
        self.assertIn("broadcastThemeSettings", theme_toggle)
        self.assertIn('useState<"mode" | "palette" | null>(null)', theme_toggle)
        self.assertIn("drawer-theme-option", theme_toggle)
        self.assertIn("desktop-theme-option", theme_toggle)
        self.assertIn('const [expanded, setExpanded] = useState<"mode" | "palette" | null>(null)', theme_toggle)
        self.assertIn('expanded === "mode"', theme_toggle)
        self.assertIn('expanded === "palette"', theme_toggle)
        self.assertIn('setExpanded(null)', theme_toggle)
        self.assertIn("当前明暗主题：", theme_toggle)
        self.assertIn("当前主题色：", theme_toggle)
        self.assertIn("mt-2 flex w-fit max-w-full items-center", theme_toggle)
        self.assertNotIn("items-center justify-between gap-3", theme_toggle)
        self.assertIn("hidden items-center gap-1", theme_toggle)
        self.assertIn("md:flex", theme_toggle)
        self.assertNotIn("mobileExpanded", theme_toggle)
        self.assertNotIn("md:hidden", theme_toggle)
        self.assertNotIn("mobile-theme-option", theme_toggle)
        self.assertNotIn("fixed top-0.5 right-16", theme_toggle)
        self.assertNotIn(".mobile-theme-options", global_css)
        self.assertIn(".drawer-theme-options", global_css)
        self.assertIn(".desktop-theme-options", global_css)
        self.assertIn(".desktop-theme-option", global_css)
        self.assertIn("width 0.38s", global_css)
        self.assertIn("prefers-reduced-motion: reduce", global_css)

        theme_init = (WEB / "components" / "theme-init-script.tsx").read_text(encoding="utf-8")
        for palette in ('data-palette="radar"', 'data-palette="instrument"', 'data-palette="indigo"'):
            self.assertIn(palette, global_css)
        self.assertIn("PALETTE_STORAGE_KEY", theme_init)
        self.assertIn("DEFAULT_COLOR_PALETTE", theme_init)
        self.assertIn("var storedPalette", theme_init)
        self.assertIn("PALETTE_CANVAS_COLORS", theme_init)
        self.assertIn('setAttribute("data-palette", palette)', theme_init)
        self.assertNotIn('removeAttribute("data-palette")', theme_init)
        self.assertNotIn('removeAttribute("data-palette")', theme_toggle)
        self.assertIn("syncThemeChrome(resolved)", theme_toggle)
        for canvas in ("#eef0f6", "#efeee8", "#efedf6"):
            self.assertIn(canvas, global_css)
        self.assertIn("--color-signal: #55c98d", global_css)
        favicon = (WEB / "app" / "icon.svg").read_text(encoding="utf-8")
        self.assertEqual(favicon.count('#55c98d'), 2)
        self.assertNotIn('#d97757', favicon)

    def test_mobile_browser_chrome_matches_editorial_surface(self):
        layout = (WEB / "app" / "layout.tsx").read_text(encoding="utf-8")
        globals_css = (WEB / "app" / "globals.css").read_text(encoding="utf-8")
        theme_chrome = (WEB / "components" / "theme-chrome.ts").read_text(encoding="utf-8")
        theme_init = (WEB / "components" / "theme-init-script.tsx").read_text(encoding="utf-8")
        theme_toggle = (WEB / "components" / "theme-toggle.tsx").read_text(encoding="utf-8")
        mobile_nav = (WEB / "components" / "mobile-nav.tsx").read_text(encoding="utf-8")

        self.assertIn('name="theme-color"', layout)
        self.assertIn('media="(prefers-color-scheme: light)"', layout)
        self.assertIn('media="(prefers-color-scheme: dark)"', layout)
        self.assertIn("EDITORIAL_LIGHT_CHROME_COLOR", layout)
        self.assertIn("EDITORIAL_DARK_CHROME_COLOR", layout)
        self.assertIn("syncThemeChrome(resolved)", theme_toggle)
        self.assertIn("#eee9dc", theme_chrome)
        self.assertIn("#181815", theme_chrome)
        self.assertIn("EDITORIAL_THEME_PATHS", theme_init)
        for path in ('"/about"', '"/agent"', '"/changelog"', '"/feedback"'):
            self.assertIn(path, theme_chrome)
        self.assertIn('meta.removeAttribute("media")', theme_init)
        self.assertIn('nextMeta.removeAttribute("media")', theme_chrome)
        self.assertIn("previousMeta.replaceWith(nextMeta)", theme_chrome)
        self.assertIn("document.body.style.backgroundColor = color", theme_chrome)
        self.assertIn('style.setProperty("--color-canvas", color)', theme_init)
        self.assertNotIn("document.body.style.backgroundColor", theme_init)
        self.assertIn('root.style.setProperty("--color-canvas", color)', theme_chrome)
        self.assertIn("root.style.backgroundColor = color", theme_chrome)
        self.assertIn("root.style.colorScheme = theme", theme_chrome)
        self.assertIn("mobile-app-chrome", mobile_nav)
        self.assertIn(".theme-transition .mobile-app-chrome", globals_css)

    def test_mobile_nav_buttons_follow_brand_and_sticky_summary(self):
        mobile_nav = (WEB / "components" / "mobile-nav.tsx").read_text(encoding="utf-8")
        date_group = (WEB / "components" / "date-group-section.tsx").read_text(encoding="utf-8")
        mobile_nav_events = (WEB / "components" / "mobile-nav-events.ts").read_text(encoding="utf-8")

        self.assertNotIn('className="sticky top-0', mobile_nav)
        self.assertNotIn("headerVisible", mobile_nav)
        self.assertNotIn("summarySticky", mobile_nav)
        self.assertNotIn("fixed z-[60]", mobile_nav)
        self.assertIn("MOBILE_NAV_OPEN_EVENT", mobile_nav)
        self.assertIn("window.addEventListener(MOBILE_NAV_OPEN_EVENT", mobile_nav)
        self.assertIn('aria-label="打开导航菜单"', mobile_nav)
        self.assertIn("onClick={openDrawer}", mobile_nav)
        self.assertIn("const [mounted, setMounted]", mobile_nav)
        self.assertIn("DRAWER_TRANSITION_MS = 300", mobile_nav)
        self.assertIn("setMounted(false)", mobile_nav)
        self.assertIn("syncThemeChrome(resolved)", mobile_nav)
        self.assertIn("w-[min(76vw,248px)]", mobile_nav)
        self.assertIn("transition-transform duration-300", mobile_nav)
        self.assertIn("translate-x-full ease-in", mobile_nav)
        self.assertIn("transition-opacity duration-200", mobile_nav)
        self.assertIn("motion-reduce:transition-none", mobile_nav)
        self.assertIn("inert={!open}", mobile_nav)

        # 抽屉是模态对话框，要有完整的键盘出口：一个显式的关闭按钮、Escape 关闭、
        # Tab 在抽屉内循环、关闭后焦点回到触发它的菜单按钮。
        #
        # 这几条原先是反向断言（禁止出现"关闭导航菜单"），当时的设计是只靠点遮罩
        # 关闭。那对鼠标够用，对键盘和读屏用户不够——没有可聚焦的关闭控件，
        # 焦点还会漏到抽屉后面的页面上。2026-08-21 补齐无障碍后改成正向锁定。
        self.assertIn('aria-label="关闭导航菜单"', mobile_nav)
        self.assertIn('role="dialog"', mobile_nav)
        self.assertIn('aria-modal="true"', mobile_nav)
        self.assertIn('event.key === "Escape"', mobile_nav)
        self.assertIn("menuButtonRef.current?.focus()", mobile_nav)
        self.assertIn("flex h-14 items-center", mobile_nav)
        self.assertIn("border-b-2 border-ink bg-canvas", mobile_nav)
        self.assertIn("sticky top-0", date_group)
        self.assertIn("flex min-h-11 min-w-0 items-center", date_group)
        self.assertIn("md:min-h-12", date_group)
        self.assertIn("entry.boundingClientRect.top <= 0", date_group)
        self.assertIn("MOBILE_NAV_OPEN_EVENT", date_group)
        self.assertIn("stuck ? 0 : -1", date_group)
        self.assertIn('stuck ? "opacity-100"', date_group)
        self.assertIn("pointer-events-none opacity-0", date_group)
        self.assertIn('aria-label="打开导航菜单"', date_group)
        self.assertIn("ai-radar:mobile-nav-open", mobile_nav_events)
        self.assertNotIn("top-16", date_group)
        self.assertNotIn("pr-16", date_group)

    def test_mobile_feed_uses_compact_consistent_vertical_rhythm(self):
        all_page = (WEB / "app" / "all" / "page.tsx").read_text(encoding="utf-8")
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        all_feed = (WEB / "components" / "all-events-feed.tsx").read_text(encoding="utf-8")
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(encoding="utf-8")
        date_group = (WEB / "components" / "date-group-section.tsx").read_text(encoding="utf-8")
        event_card = (WEB / "components" / "event-card.tsx").read_text(encoding="utf-8")
        mobile_discovery = (WEB / "components" / "mobile-discovery.tsx").read_text(encoding="utf-8")

        self.assertIn("max-w-[1320px] justify-self-center px-4 pb-8 pt-3", all_page)
        self.assertIn("px-4 pb-8 pt-3 md:px-8 md:py-8", latest_page)
        self.assertIn('className="mt-3 md:mt-6"', all_feed)
        self.assertIn('className="mt-2 md:mt-5"', latest_feed)
        self.assertNotIn("SELECTED / 7 DAYS", latest_feed)
        self.assertNotIn("近 7 天精选", latest_feed)
        self.assertIn("relative mt-1.5 grid gap-2 md:mt-2", date_group)
        self.assertNotIn("md:gap-4", date_group)
        self.assertIn("grid grid-cols-1 gap-1 md:grid-cols-[72px_1fr] md:gap-2", event_card)
        self.assertIn("md:block md:pt-3 md:text-sm", event_card)
        self.assertNotIn("md:block md:pt-1 md:text-sm", event_card)
        self.assertIn("md:-left-[25px] md:top-[21px] md:w-5", event_card)
        self.assertNotIn("md:-left-[25px] md:top-3 md:w-5", event_card)
        self.assertIn("openArticle", event_card)
        self.assertIn("group/event border-t border-line-strong pb-1 pt-3", event_card)
        self.assertNotIn("评分 {score}", event_card)
        self.assertIn("Score {score}", event_card)
        self.assertIn("text-sm leading-6 text-ink-mid", event_card)
        self.assertIn("<BookmarkButton eventId={item.event_id} compact />", event_card)
        self.assertIn("editorial-card-title", event_card)
        self.assertIn("<Sparkles", event_card)
        self.assertIn("relative -top-0.5 mr-2 inline-flex h-5 items-center gap-1", event_card)
        self.assertIn("精选", event_card)
        self.assertNotIn("Selected", event_card)
        self.assertIn("aspect-[2/1]", event_card)
        self.assertIn("max-w-[460px]", event_card)
        self.assertIn("md:w-2/5", event_card)
        self.assertIn("mr-auto", event_card)
        self.assertIn("object-cover object-center", event_card)
        self.assertNotIn("max-h-[640px]", event_card)
        self.assertIn('className="mt-2.5 flex gap-2 md:hidden"', mobile_discovery)
        self.assertIn('className="relative mt-1.5 md:hidden"', mobile_discovery)
        self.assertIn("flex gap-1 overflow-x-auto", mobile_discovery)
        self.assertIn('compact ? "h-5 w-5"', (WEB / "components" / "bookmark-button.tsx").read_text(encoding="utf-8"))

    def test_public_pages_share_editorial_shell_except_search(self):
        direct_pages = [
            WEB / "app" / "latest" / "page.tsx",
            WEB / "app" / "all" / "page.tsx",
            WEB / "app" / "x" / "page.tsx",
            WEB / "app" / "x" / "[id]" / "page.tsx",
            WEB / "app" / "telegram" / "page.tsx",
            WEB / "app" / "bookmarks" / "page.tsx",
            WEB / "app" / "topics" / "page.tsx",
            WEB / "app" / "topics" / "[slug]" / "page.tsx",
            WEB / "app" / "event" / "[id]" / "page.tsx",
        ]
        for page in direct_pages:
            source = page.read_text(encoding="utf-8")
            self.assertIn("editorial-page min-h-screen", source, str(page))
            self.assertIn("lg:grid-cols-[248px", source, str(page))

        static_shell = (WEB / "components" / "static-page.tsx").read_text(encoding="utf-8")
        report_shell = (WEB / "app" / "reports" / "report-shell.tsx").read_text(encoding="utf-8")
        search_page = (WEB / "app" / "search" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("editorial-page min-h-screen", static_shell)
        self.assertIn("lg:grid-cols-[248px_1fr]", static_shell)
        self.assertIn("editorial-page min-h-screen", report_shell)
        self.assertIn("lg:grid-cols-[248px_216px_minmax(0,1fr)]", report_shell)
        self.assertNotIn("editorial-page", search_page)

    def test_static_content_pages_use_whitespace_instead_of_stacked_rules(self):
        static_shell = (WEB / "components" / "static-page.tsx").read_text(encoding="utf-8")
        about_page = (WEB / "app" / "about" / "page.tsx").read_text(encoding="utf-8")
        feedback_page = (WEB / "app" / "feedback" / "page.tsx").read_text(encoding="utf-8")
        agent_page = (WEB / "app" / "agent" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("border-b border-line-strong", static_shell)
        self.assertNotIn("border-b-2 border-ink", static_shell)
        self.assertIn("space-y-10", static_shell)

        for source in (about_page, feedback_page, agent_page):
            self.assertNotIn("border-y border-line", source)
            self.assertNotIn("border-y border-signal/30", source)

        self.assertNotIn("rounded-md border border-line bg-panel p-6", feedback_page)
        self.assertIn("bg-panel/45", about_page)
        self.assertIn("bg-panel/45", feedback_page)
        self.assertIn("bg-panel/45", agent_page)

    def test_public_editorial_pages_do_not_stack_decorative_horizontal_rules(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(encoding="utf-8")
        date_group = (WEB / "components" / "date-group-section.tsx").read_text(encoding="utf-8")
        all_page = (WEB / "app" / "all" / "page.tsx").read_text(encoding="utf-8")
        telegram_page = (WEB / "app" / "telegram" / "page.tsx").read_text(encoding="utf-8")
        x_page = (WEB / "app" / "x" / "page.tsx").read_text(encoding="utf-8")
        daily_page = (WEB / "app" / "daily" / "page.tsx").read_text(encoding="utf-8")
        period_shared = (WEB / "app" / "reports" / "period-shared.tsx").read_text(encoding="utf-8")
        weekly_report = (WEB / "app" / "reports" / "weekly-report-page.tsx").read_text(encoding="utf-8")
        monthly_report = (WEB / "app" / "reports" / "monthly-report-page.tsx").read_text(encoding="utf-8")
        report_shell = (WEB / "app" / "reports" / "report-shell.tsx").read_text(encoding="utf-8")
        bookmarks_page = (WEB / "app" / "bookmarks" / "page.tsx").read_text(encoding="utf-8")
        topics_page = (WEB / "app" / "topics" / "page.tsx").read_text(encoding="utf-8")
        topic_page = (WEB / "app" / "topics" / "[slug]" / "page.tsx").read_text(encoding="utf-8")
        event_page = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        reading_toggle = (WEB / "app" / "event" / "[id]" / "article-reading-toggle.tsx").read_text(encoding="utf-8")

        self.assertNotIn("border-b-2 border-ink pb-5", latest_page)
        self.assertNotIn("border-b-2 border-ink pb-3", latest_feed)
        self.assertIn('stuck ? "border-line', date_group)
        self.assertIn(': "border-transparent"', date_group)

        for source in (all_page, telegram_page, x_page):
            self.assertNotIn("editorial-surface border-y border-line", source)

        for source in (daily_page, period_shared):
            self.assertNotIn("border-y border-line border-l-4", source)
            self.assertNotIn("border-y border-signal/40", source)

        for source in (daily_page, weekly_report, monthly_report):
            self.assertNotIn("grid grid-cols-2 gap-x-6 border-y border-line", source)

        self.assertIn("grid grid-cols-3 border-b border-line", report_shell)
        self.assertNotIn("grid grid-cols-3 border-y border-line", report_shell)

        for source in (bookmarks_page, topics_page, topic_page, event_page):
            self.assertNotIn("border-b-2 border-ink", source)

        self.assertNotIn("max-w-[720px]", reading_toggle)

    def test_mobile_hotspots_use_compact_spacing(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")

        self.assertNotIn("<BentoGridItem", latest_page)
        self.assertIn("divide-y divide-line/70", latest_page)
        self.assertIn("grid grid-cols-[28px_1fr_auto]", latest_page)
        self.assertIn("py-2.5 text-sm md:py-3", latest_page)
        self.assertIn("{item.source_count ?? 1} 个信源", latest_page)
        self.assertIn('index > 2 ? "hidden 2xl:block"', latest_page)

    def test_latest_page_uses_aceternity_background_without_bento_cards(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        grid_background = (WEB / "components" / "ui" / "grid-background.tsx").read_text(encoding="utf-8")

        self.assertIn("GridBackground", latest_page)
        self.assertNotIn("BentoGrid", latest_page)
        self.assertIn("background-image:linear-gradient", grid_background)
        self.assertNotIn("framer-motion", latest_page + grid_background)
        self.assertNotIn("🔥", latest_page)

    def test_latest_editorial_entries_preserve_summary_and_use_fixed_media_crop(self):
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(encoding="utf-8")
        event_card = (WEB / "components" / "event-card.tsx").read_text(encoding="utf-8")

        self.assertIn("openArticle", latest_feed)
        self.assertNotIn("clampSummary\n", latest_feed)
        self.assertIn("line-clamp-3 md:line-clamp-none", event_card)
        self.assertIn("aspect-[2/1]", event_card)
        self.assertIn("max-w-[460px]", event_card)
        self.assertIn("md:w-2/5", event_card)
        self.assertIn("mr-auto", event_card)
        self.assertIn("object-cover object-center", event_card)
        self.assertNotIn("max-h-[640px]", event_card)
        self.assertLess(event_card.index("{image && openArticle ?"), event_card.index("{showReason && item.reason ?"))
        self.assertIn('openArticle ? ""', event_card)
        self.assertIn('openArticle\n              ? "min-w-0"', event_card)
        self.assertIn('? "w-full line-clamp-3 md:line-clamp-none"', event_card)
        self.assertNotIn("xl:grid-cols-[minmax(0,1fr)_280px]", event_card)
        self.assertNotIn("xl:col-start-2 xl:row-span-2 xl:row-start-3", event_card)

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
        for label in ["精选", "推文", "电报", "全部", "日报", "主题", "收藏", "Agent 接入", "关于", "更新日志", "反馈"]:
            self.assertIn(label, nav)
        self.assertIn('href: "/all"', nav)

    def test_telegram_page_uses_rsshub_channel_api_and_sits_below_x_nav(self):
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        telegram_page = (WEB / "app" / "telegram" / "page.tsx").read_text(
            encoding="utf-8"
        )
        nav = (WEB / "components" / "nav.ts").read_text(encoding="utf-8")

        self.assertIn("/api/public/telegram", api_source)
        self.assertIn("getTelegramEvents", telegram_page)
        self.assertIn('activeNavId="telegram"', telegram_page)
        self.assertIn("payload.channels.map", telegram_page)
        self.assertLess(nav.index('label: "推文"'), nav.index('label: "电报"'))
        self.assertLess(nav.index('label: "电报"'), nav.index('label: "全部"'))

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

    def test_run_detail_shows_source_names_not_ids(self):
        # 信源改名后,运行明细必须跟着显示新名称——id 只是稳定标识,
        # 展示层用 overview.sources 的 id→name 映射解析
        detail_source = (WEB / "app" / "admin" / "pipeline-run-detail.tsx").read_text(encoding="utf-8")
        dashboard_source = (WEB / "app" / "admin" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("sourceNames", detail_source)
        self.assertIn("sourceNames", dashboard_source)

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

    def test_event_coverage_links_stay_on_site(self):
        # 2026-07-13:同一事件的跨源报道点进去要看我们站内自己的内容页
        # (每篇文章都有独立地址),不能再跳去来源站的外部原文
        event_page = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("member.event_id", event_page)
        self.assertNotIn("href={member.source_url}", event_page)
        self.assertIn("event.source_count ?? 1", event_page)
        self.assertIn("event.coverage.length", event_page)

    def test_hotspot_list_displays_source_count_without_report_count(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn("{item.source_count ?? 1} 个信源", latest_page)
        self.assertNotIn("item.coverage.length", latest_page)

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

    def test_sources_manager_reflects_configurable_recent_days_crawling(self):
        # 2026-07-12 深夜决策:每源条数配置停用,改为按发布日期过滤——
        # UI 不再有 crawl_limit 输入与"每轮 N 条"文案。2026-07-15:固定
        # "仅当天"改为可在信源管理里编辑的"最近 N 天"(config.recent_days)
        manager_source = (
            WEB / "app" / "admin" / "sources" / "sources-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("仅当天发布", manager_source)
        self.assertIn("recent_days", manager_source)
        self.assertNotIn("crawl_limit", manager_source)
        self.assertNotIn("每轮", manager_source)

    def test_sources_list_sorts_by_active_then_name_and_flags_official(self):
        # 信源管理(2026-07-15):列表先按启用状态排序(启用在前),同状态内
        # 再按名称排序;官方信源带显眼"官方"标记
        manager_source = (
            WEB / "app" / "admin" / "sources" / "sources-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("sortedSources", manager_source)
        self.assertIn("a.is_active !== b.is_active", manager_source)
        self.assertIn("localeCompare", manager_source)
        self.assertIn('source.category === "official"', manager_source)
        self.assertIn("官方", manager_source)

    def test_events_manager_source_filter_sorts_by_active_then_name(self):
        # 内容管理页的"主信源"筛选下拉框要和信源管理列表一样,先按启用
        # 状态排序,同状态内再按名称(拼音)排序，而不是沿用后端接口的
        # 原始顺序
        manager_source = (
            WEB / "app" / "admin" / "events" / "events-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("sortedSources", manager_source)
        self.assertIn("a.is_active !== b.is_active", manager_source)
        self.assertIn('localeCompare(b.name, "zh-CN")', manager_source)
        self.assertIn("sortedSources.map((source) =>", manager_source)

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
        self.assertIn("export async function DELETE", proxy_route)

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

    def test_admin_content_manager_supports_server_side_time_sorting(self):
        page = (WEB / "app" / "admin" / "events" / "page.tsx").read_text(encoding="utf-8")
        manager = (WEB / "app" / "admin" / "events" / "events-manager.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn('sort_by?: string', page)
        self.assertIn('sort_dir?: string', page)
        self.assertIn('sort_by: sortBy', page)
        self.assertIn('sort_dir: sortDirection', page)
        self.assertIn('sortHref("published_at")', manager)
        self.assertIn('sortHref("crawled_at")', manager)
        self.assertIn('aria-sort=', manager)
        self.assertIn('name="sort_by"', manager)
        self.assertIn('name="sort_dir"', manager)
        self.assertIn('点击时间表头可切换', manager)

    def test_admin_content_manager_supports_deleting_an_article(self):
        manager_source = (
            WEB / "app" / "admin" / "events" / "events-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("deleteEvent", manager_source)
        self.assertIn('method: "DELETE"', manager_source)
        self.assertIn("确定要彻底删除这篇文章吗", manager_source)
        self.assertIn("此操作不可恢复", manager_source)
        self.assertIn("deletingEvent", manager_source)

    def test_admin_can_preview_hidden_article_without_public_visibility(self):
        manager = (
            WEB / "app" / "admin" / "events" / "events-manager.tsx"
        ).read_text(encoding="utf-8")
        detail = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn("?admin_preview=1", manager)
        self.assertIn("/api/admin/events/", detail)
        self.assertIn("管理员预览", detail)
        self.assertIn("该文章当前处于隐藏状态", detail)

    def test_admin_drafts_have_read_only_detail_preview(self):
        manager = (
            WEB / "app" / "admin" / "drafts" / "drafts-manager.tsx"
        ).read_text(encoding="utf-8")
        preview = (
            WEB / "app" / "admin" / "drafts" / "[id]" / "page.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("/admin/drafts/${encodeURIComponent(draft.id)}", manager)
        self.assertIn("预览", manager)
        self.assertIn("草稿预览", preview)
        self.assertIn("editorDocumentHtml", preview)
        self.assertIn("预览不会发布内容", preview)
        self.assertIn("继续编辑", preview)

    def test_admin_content_edit_reuses_the_full_draft_editor(self):
        manager = (
            WEB / "app" / "admin" / "events" / "events-manager.tsx"
        ).read_text(encoding="utf-8")
        edit_page = (
            WEB / "app" / "admin" / "events" / "[id]" / "edit" / "page.tsx"
        ).read_text(encoding="utf-8")
        editor = (
            WEB / "app" / "admin" / "events" / "new" / "manual-article-editor.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("/admin/events/${encodeURIComponent(event.event_id)}/edit", manager)
        self.assertIn("ManualArticleEditor", edit_page)
        self.assertIn("initialEventId={id}", edit_page)
        for field in [
            "one_line_summary",
            "summary_zh",
            "author",
            "published_at",
            "original_url",
            "editor_document",
            "selection_mode",
        ]:
            self.assertIn(field, editor)
        self.assertIn('updated.includes("editor_document")', editor)
        self.assertIn("API 服务仍是旧版本", editor)
        self.assertIn("useAiWhenTagsBlank", editor)
        self.assertIn("parsedTags.length === 0 ? null", editor)

    def test_article_images_are_proxied_against_hotlink_protection(self):
        # 中文媒体 CDN 防盗链分两派：infoq（无 Referer 放行）和 qbitai
        # （白名单制，无 Referer 也 403）。浏览器无法伪造 Referer，所以
        # 文章图片统一走服务端代理，代理请求带图片自身 origin 作 Referer
        # （三家 CDN 实测均放行）。
        toggle = (WEB / "app" / "event" / "[id]" / "article-reading-toggle.tsx").read_text(
            encoding="utf-8"
        )
        detail = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        # paragraph/heading/image block rendering (used by both the plain
        # no-translation path in page.tsx and ArticleReadingToggle) lives in
        # one shared component so the hotlink-protection proxying only needs
        # fixing once - see components/original-block.tsx
        original_block = (WEB / "components" / "original-block.tsx").read_text(encoding="utf-8")
        proxy_route = (WEB / "app" / "api" / "image-proxy" / "route.ts").read_text(
            encoding="utf-8"
        )
        helper = (WEB / "lib" / "images.ts").read_text(encoding="utf-8")

        self.assertIn("proxiedImageUrl", helper)
        self.assertIn("/api/image-proxy", helper)
        self.assertIn("Referer", proxy_route)
        self.assertIn("image/", proxy_route)
        self.assertIn("proxiedImageUrl", original_block)
        self.assertIn('block.type === "video"', original_block)
        self.assertIn("<iframe", original_block)
        self.assertIn("<video", original_block)
        self.assertIn('block.type === "social_embed"', original_block)
        self.assertIn("在 X 上查看", original_block)
        # article-reading-toggle still proxies README markdown images directly
        self.assertIn("proxiedImageUrl", toggle)
        # page.tsx delegates to the shared renderer instead of proxying itself
        self.assertIn("renderOriginalBlock", detail)

    def test_latest_page_supports_category_filter_links(self):
        # the actual client-side filtering (filteredItems) now runs inside
        # latest-events-feed.tsx, which page.tsx passes selectedCategory/
        # query into as props - the filter chip links themselves stay in
        # page.tsx
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(encoding="utf-8")

        self.assertIn("searchParams", latest_page)
        self.assertIn("selectedCategory", latest_page)
        self.assertIn("categoryOptions", latest_page)
        self.assertIn("filteredItems", latest_feed)
        self.assertIn("latestHref", latest_page)
        self.assertIn('params.set("focus", focus)', latest_page)
        taxonomy = (WEB / "lib" / "taxonomy.ts").read_text(encoding="utf-8")
        self.assertIn('["", "全部"]', taxonomy)

    def test_daily_page_falls_back_to_latest_archived_date_not_todays_empty_report(self):
        # 2026-07-13 修复:同步还没跑到"今天"之前(比如刚过零点),/latest
        # 的滚动窗口会把 report_date 报成"今天"，但当天还没有真正生成的
        # 日报——/daily 必须用归档里真实存在的最新日期兜底，而不是硬套
        # 一个空壳日期导致页面显示 0 篇。
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
        daily_index = (WEB / "app" / "daily" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("/api/public/daily/", api_source)
        self.assertIn("getDailyReport", api_source)
        self.assertIn("getLatestReport", daily_index)
        self.assertIn("getDailyArchive", daily_index)
        self.assertIn("archiveDates[0]", daily_index)
        self.assertIn("AI·RADAR 日报", daily_index)
        self.assertIn("今日看点", daily_index)
        self.assertIn("ReportShell", daily_index)
        self.assertIn("buildDailyDigest", daily_index)
        self.assertIn("eventHref", daily_index)
        # 归档日期和前后翻页都停留在同一个页面壳(带侧边栏)，用查询参数
        # 切换日期，不再跳去没有侧边栏的独立 /daily/[date] 页面
        self.assertIn("/daily?date=", daily_index)
        self.assertNotIn("href={`/daily/${", daily_index)
        for removed in ["app/daily/[date]/page.tsx", "app/daily/report-view.tsx", "app/daily/copy-markdown-button.tsx"]:
            self.assertFalse((WEB / removed).exists(), removed)

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
        self.assertIn("px-4 pt-2 lg:hidden", shell_source)
        self.assertIn("px-4 pb-6 pt-4 md:px-8 md:py-8", shell_source)
        self.assertIn("buildDailyDigest", data_source)
        self.assertIn("buildWeeklyDigest", data_source)
        self.assertIn("buildMonthlyDigest", data_source)

    def test_daily_page_renders_mainline_and_collapsible_categories(self):
        """日报页三块新结构：AI 主线、分类简述、可折叠的分类列表。

        折叠用原生 details/summary——这一页是服务端组件，为一个开合把整棵
        树变成客户端组件不划算。
        """
        daily_page = (WEB / "app" / "daily" / "page.tsx").read_text(encoding="utf-8")
        data_source = (WEB / "app" / "reports" / "report-data.ts").read_text(encoding="utf-8")

        self.assertIn("今日主线", daily_page)
        self.assertIn("<details", daily_page)
        self.assertIn("digest!.categories", daily_page)
        self.assertIn("category.note", daily_page)
        self.assertIn("mainline", data_source)
        self.assertIn("category_notes", data_source)
        self.assertIn("mt-5 grid grid-cols-4 divide-x divide-line", daily_page)
        self.assertIn("whitespace-nowrap text-base", daily_page)

    def test_daily_cards_no_longer_render_the_why_it_matters_block(self):
        """「为什么重要」按 2026-08-18 的改版从日报卡片移除。

        它是日报页唯一读快照（reason_snapshot）的字段，移除后这一页的内容
        全部现查。周月报卡片仍然用 reason，不受影响。
        """
        daily_page = (WEB / "app" / "daily" / "page.tsx").read_text(encoding="utf-8")

        self.assertNotIn("为什么重要", daily_page)
        self.assertNotIn("item.reason", daily_page)

    def test_report_data_does_not_resort_items_by_raw_score(self):
        """接口给的顺序就是名次，前端不能再按 final_score 排一次。

        final_score 只在同一个打分模型内部可比，后端已经按模型分组归一化过
        （api/public.py 的 sort_period_items）。前端只要再按原始分排一次，
        2026-08-13 换模型之后的条目就会重新被压回榜尾——正是这个修复要
        消除的现象。
        """
        data_source = (WEB / "app" / "reports" / "report-data.ts").read_text(encoding="utf-8")

        self.assertNotIn("final_score ?? 0) - (", data_source)
        self.assertNotIn("sortByScore", data_source)

    def test_weekly_and_monthly_pages_render_aihot_period_reports(self):
        """周报和月报分家：周报与日报同构（主线+看点+分类列表全露出），
        月报换趋势结构（总述+趋势线挂证据+完整榜单+数据面）。"""
        weekly_report = (WEB / "app" / "reports" / "weekly-report-page.tsx").read_text(encoding="utf-8")
        monthly_report = (WEB / "app" / "reports" / "monthly-report-page.tsx").read_text(encoding="utf-8")
        weekly_page = (WEB / "app" / "weekly" / "page.tsx").read_text(encoding="utf-8")
        monthly_page = (WEB / "app" / "monthly" / "page.tsx").read_text(encoding="utf-8")

        self.assertIn("WeeklyReportPage", weekly_page)
        self.assertIn("MonthlyReportPage", monthly_page)

        # 周报：日报的放大版
        self.assertIn("ReportShell", weekly_report)
        self.assertIn("buildWeeklyDigest", weekly_report)
        self.assertIn("本周主线", weekly_report)
        self.assertIn("本周看点", weekly_report)
        self.assertIn("<details", weekly_report)
        # 名单全露出：不允许再出现每板块截前几条的写法
        self.assertNotIn("slice(0, 3)", weekly_report)

        # 月报：趋势结构，不按分类分板块
        self.assertIn("ReportShell", monthly_report)
        self.assertIn("buildMonthlyDigest", monthly_report)
        self.assertIn("本月总述", monthly_report)
        self.assertIn("本月榜单", monthly_report)
        self.assertIn("trends", monthly_report)
        self.assertIn("grid-cols-[minmax(0,1fr)]", monthly_report)
        self.assertIn("[overflow-wrap:anywhere]", (WEB / "app" / "reports" / "period-shared.tsx").read_text(encoding="utf-8"))
        self.assertNotIn("slice(0, 3)", monthly_report)

        # 进行中的期次要明示会变，两页都挂封版横幅
        self.assertIn("SealBanner", weekly_report)
        self.assertIn("SealBanner", monthly_report)

        data_source = (WEB / "app" / "reports" / "report-data.ts").read_text(encoding="utf-8")
        # 诚实口径：入选与期间收录分开说，不再拿名单长度冒充收录数
        self.assertIn("期间收录", data_source)
        self.assertIn("coverage_count", data_source)

    def test_event_detail_page_links_from_latest_and_daily_views(self):
        latest_page = (WEB / "app" / "latest" / "page.tsx").read_text(encoding="utf-8")
        event_page = (WEB / "app" / "event" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        reading_toggle = (
            WEB / "app" / "event" / "[id]" / "article-reading-toggle.tsx"
        ).read_text(encoding="utf-8")
        original_block = (WEB / "components" / "original-block.tsx").read_text(encoding="utf-8")
        prose_tokens = (WEB / "components" / "prose-tokens.ts").read_text(encoding="utf-8")
        event_helpers = (WEB / "lib" / "events.ts").read_text(encoding="utf-8")
        api_source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")

        self.assertIn("eventHref", latest_page)
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
        self.assertIn("translatedBlocksFor(event, originalBlocks)", event_page)
        self.assertIn("translationLooksAligned", event_page)
        self.assertIn(
            "translatedText.length !== originalText.length",
            event_page,
        )
        self.assertIn("Sidebar", event_page)
        self.assertIn("GridBackground", event_page)
        self.assertIn("lg:grid-cols-[248px_minmax(0,1fr)]", event_page)
        self.assertIn("px-4 pb-16 pt-5 md:px-8 md:py-14", event_page)
        self.assertIn("mx-auto max-w-[1120px]", event_page)
        self.assertIn("relative flex items-start justify-between gap-4 md:items-center", event_page)
        self.assertIn("flex h-5 min-w-0 items-center", event_page)
        self.assertIn("Score {formatScore(event.final_score)}", event_page)
        self.assertIn("readout hidden text-xs uppercase tracking-[0.08em] md:inline", event_page)
        self.assertIn("text-[10px] uppercase tracking-[0.08em] text-ink-mid md:hidden", event_page)
        self.assertIn("<BookmarkButton eventId={event.event_id} labelOnDesktop />", event_page)
        self.assertIn("relative mt-4 flex w-fit items-center gap-2 text-sm", event_page)
        self.assertIn('section className="mx-auto mt-7 max-w-[760px] space-y-7', event_page)
        self.assertNotIn("Index /", event_page)
        self.assertIn('text-[15px] leading-7 text-ink-mid md:text-base', event_page)
        self.assertIn('border-l-2 border-signal pl-4', event_page)
        self.assertIn('header className="relative mx-auto max-w-[760px]', event_page)
        self.assertIn('text-[clamp(1.9rem,2.6vw,2.8rem)]', event_page)
        self.assertNotIn('overflow-hidden border-b border-line-strong', event_page)
        self.assertNotIn('mt-7 border-t border-line pt-5', event_page)
        self.assertNotIn('md:grid-cols-[112px_minmax(0,1fr)]', event_page)
        self.assertNotIn("md:grid-cols-[minmax(0,1fr)_260px]", event_page)
        self.assertIn('article className="mx-auto mt-6 max-w-[760px]', event_page)
        self.assertIn('div className="mt-5 space-y-4"', event_page)
        self.assertIn('aria-label="精选"', event_page)
        self.assertIn("<Sparkles aria-hidden", event_page)
        self.assertIn("精选\n                    </span>", event_page)
        self.assertNotIn("flex flex-wrap items-center justify-end gap-2", event_page)
        self.assertNotIn('<div className="mt-8">', event_page)
        bookmark_button = (WEB / "components" / "bookmark-button.tsx").read_text(encoding="utf-8")
        self.assertIn("labelOnDesktop", bookmark_button)
        self.assertIn('"hidden md:inline"', bookmark_button)
        self.assertIn("lg:sticky", (WEB / "components" / "sidebar.tsx").read_text(encoding="utf-8"))
        self.assertIn("显示原文", reading_toggle)
        self.assertIn("显示译文", reading_toggle)
        self.assertIn("AI 中文译文", reading_toggle)
        self.assertNotIn("Index /", reading_toggle)
        self.assertIn('article className="mx-auto mt-6 max-w-[760px]', reading_toggle)
        self.assertIn("border-t border-line-strong pt-5", reading_toggle)
        self.assertIn('div className="mt-5 space-y-4 font-sans"', reading_toggle)
        self.assertIn('text-[15px] font-normal leading-7', prose_tokens)
        self.assertIn('lg:text-[16px] lg:leading-[29px]', prose_tokens)
        self.assertIn("ReactMarkdown", reading_toggle)
        self.assertIn("remarkGfm", reading_toggle)
        # known unscrapable read-original domains (WeChat) - backend
        # withholds original_*, frontend must skip rendering a 原文 block
        # entirely rather than synthesize one from the AI summary
        self.assertIn("aihot_item_page_link_only", event_page)
        self.assertIn("content_origin?: string", api_source)
        # SourcePilot 契约:time_basis="discovered" 的条目只有收录时间,
        # 展示必须写「收录于」,不得伪称原文发布时间
        self.assertIn("time_basis?: string", api_source)
        self.assertIn("收录于", event_page)
        self.assertIn("originalMarkdown", reading_toggle)
        self.assertIn("hasOriginalMarkdown", reading_toggle)
        self.assertIn("translatedBlocks.length > 0 && !hasOriginalMarkdown", reading_toggle)
        self.assertIn('hasOriginalMarkdown ? "original" : "translated"', reading_toggle)
        self.assertIn("readmeImageClassName", reading_toggle)
        # block-level image rendering (isReadmeInlineImage/readmeImageClassName
        # applied to a block's own url) now lives in the shared renderer
        self.assertIn("isReadmeInlineImage", original_block)
        self.assertIn(
            "readmeImageClassName({ src: block.url, width: block.width, height: block.height })",
            original_block,
        )
        self.assertIn("renderOriginalBlock", reading_toggle)
        self.assertIn("cleanTableElementProps", reading_toggle)
        self.assertIn("vAlign", reading_toggle)
        self.assertIn("tr({ node: _node, ...props })", reading_toggle)
        self.assertIn("cleanTableElementProps(props)", reading_toggle)
        self.assertIn("img.shields.io", original_block)
        self.assertIn('if (block.type === "byline") {', original_block)
        self.assertNotIn('key={`byline-${index}`}', original_block)
        self.assertIn("inline-block h-auto w-auto max-w-full", original_block)
        self.assertIn("block h-auto w-auto max-w-full", original_block)
        self.assertIn("use client", reading_toggle)
        self.assertNotIn("返回最新情报", event_page)
        self.assertNotIn("报告正文", event_page)
        self.assertNotIn("时间线", event_page)
        self.assertNotIn("下一步", event_page)

    def test_all_page_renders_all_latest_events(self):
        # eventHref/"精选" badge rendering live in the shared event-card.tsx
        # now (used by both the latest and all feeds); the client-side
        # search happens inside all-events-feed.tsx, which page.tsx feeds
        # selectedSource/selectedCategory/query into as props
        all_page = (WEB / "app" / "all" / "page.tsx").read_text(encoding="utf-8")
        all_feed = (WEB / "components" / "all-events-feed.tsx").read_text(encoding="utf-8")
        event_card = (WEB / "components" / "event-card.tsx").read_text(encoding="utf-8")
        date_group = (WEB / "components" / "date-group-section.tsx").read_text(encoding="utf-8")

        self.assertIn("getAllEvents", all_page)
        self.assertIn("AllEventsFeed", all_page)
        self.assertIn("eventHref", event_card)
        self.assertIn("全部 AI 动态", all_page)
        self.assertIn("没进精选的动态也都在这里", all_page)
        self.assertIn("Sidebar", all_page)
        self.assertIn("精选", event_card)
        self.assertIn("sourceOptions", all_page)
        self.assertIn("全部来源", all_page)
        self.assertIn("官方原文", all_page)
        self.assertIn("媒体报道", all_page)
        self.assertIn("社区讨论", all_page)
        self.assertIn("categoryOptions", all_page)
        self.assertIn("searchParams", all_page)
        self.assertIn("selectedSource", all_page)
        self.assertIn("selectedCategory", all_page)
        self.assertIn("searchEvents", all_feed)
        self.assertIn('name="q"', all_page)
        self.assertIn("groupEventsByDate", all_feed)
        self.assertIn("DateGroupSection", all_feed)
        self.assertIn("<details", date_group)
        self.assertIn("推荐理由", event_card)
        self.assertIn("score={formatScore(item.final_score)}", all_feed)
        self.assertNotIn("评分 {score}", event_card)
        self.assertIn("来源", event_card)

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

    def test_tag_chips_use_exact_tag_query_instead_of_keyword_search(self):
        all_feed = (WEB / "components" / "all-events-feed.tsx").read_text(encoding="utf-8")
        latest_feed = (WEB / "components" / "latest-events-feed.tsx").read_text(
            encoding="utf-8"
        )
        event_detail = (
            WEB / "app" / "event" / "[id]" / "page.tsx"
        ).read_text(encoding="utf-8")
        all_proxy = (WEB / "app" / "api" / "all-events" / "route.ts").read_text(
            encoding="utf-8"
        )
        latest_proxy = (
            WEB / "app" / "api" / "latest-events" / "route.ts"
        ).read_text(encoding="utf-8")

        for feed in (all_feed, latest_feed):
            self.assertIn("new URLSearchParams({ tag })", feed)
            self.assertNotIn("new URLSearchParams({ q: tag })", feed)
            self.assertIn('params.set("tag", tag)', feed)
        self.assertIn("new URLSearchParams({ tag })", event_detail)
        self.assertIn("href={tagHref(tag)}", event_detail)
        self.assertNotIn("new URLSearchParams({ q: tag })", event_detail)
        for proxy in (all_proxy, latest_proxy):
            self.assertIn('url.searchParams.get("tag")', proxy)

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

    def test_tweet_lightbox_is_portalled_out_of_the_card(self):
        """推文大图弹层必须 portal 到 <body>。起因是 .card-hover 曾给卡片上
        transform，而带 transform 的祖先会接管后代 position:fixed 的包含块，
        弹层于是变成「以卡片居中」，位置随卡片飘。2026-08-18 悬浮态改成只亮
        边框、transform 已移除，但 portal 必须留着：hover 效果是随时会被调
        回来的东西，弹层不该跟着一起坏。"""
        tweet_card = (WEB / "components" / "tweet-card.tsx").read_text(encoding="utf-8")

        self.assertIn("createPortal", tweet_card)
        self.assertIn("document.body", tweet_card)
        # 弹层本身仍靠 fixed inset-0 占满视口
        self.assertIn("fixed inset-0 z-50 flex items-center justify-center", tweet_card)

    def test_tweet_list_collapses_adjacent_card_borders(self):
        x_page = (WEB / "app" / "x" / "page.tsx").read_text(encoding="utf-8")
        tweet_card = (WEB / "components" / "tweet-card.tsx").read_text(encoding="utf-8")

        self.assertIn('<div className="mt-2 md:mt-4">', x_page)
        self.assertNotIn("space-y-2 md:mt-4 md:space-y-3", x_page)
        self.assertIn(
            '"-mt-px border-x-0 border-y border-line first:mt-0 hover:z-10"',
            tweet_card,
        )
        self.assertIn('? "rounded-md border border-line"', tweet_card)

    def test_tweet_external_links_are_deduplicated_before_render(self):
        """SP may emit the same expanded URL more than once. The card must
        deduplicate before mapping because href is also the React key."""
        tweet_card = (WEB / "components" / "tweet-card.tsx").read_text(encoding="utf-8")

        self.assertIn("const uniqueUrls = Array.from(", tweet_card)
        self.assertIn("new Set((urls ?? []).map((url) => url.trim()).filter(Boolean))", tweet_card)
        self.assertIn("{uniqueUrls.map((url) => (", tweet_card)
        self.assertNotIn("{urls.map((url) => (", tweet_card)


if __name__ == "__main__":
    unittest.main()
