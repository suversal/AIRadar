"""Agent 接入层的结构与一致性检查。

这套测试的由来：/agent 页面曾经把 /api/public/* 当成公开接口写在文档里，
而 nginx 从来没有把那些路径对外放行——照着文档 curl 必然 404，而且没有
任何测试会发现，因为页面和实现之间没有任何约束。

所以这里检查的重点不是"代码能跑"，而是"文档说的和代码做的是同一件事"：
页面、SKILL.md、llms.txt、OpenAPI 里出现的每一个端点、每一个 MCP 工具名，
都必须在实现里找得到对应物。
"""

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
SKILL_DIR = WEB / "public" / "ai-radar-skill"

AGENT_PAGE = WEB / "app" / "agent" / "page.tsx"
ACCESS_TABS = WEB / "app" / "agent" / "access-tabs.tsx"
SKILL_MD = SKILL_DIR / "SKILL.md"
LLMS_TXT = WEB / "app" / "llms.txt" / "route.ts"
OPENAPI = WEB / "lib" / "v1" / "openapi.ts"
MCP_TOOLS = WEB / "lib" / "mcp" / "tools.ts"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def route_patterns(base: Path, prefix: str) -> set[str]:
    """把 app/ 下的 route.ts 收集成 URL 模式，动态段一律记作 *。"""
    patterns = set()
    for route in base.rglob("route.ts"):
        relative = route.parent.relative_to(base)
        segments = [
            "*" if segment.startswith("[") else segment
            for segment in relative.parts
            if segment != "."
        ]
        patterns.add("/".join([prefix, *segments]) if segments else prefix)
    return patterns


def normalize(path: str) -> str:
    """文档里的 {id}/{YYYY-MM-DD}/{a|b|c} 占位统一成 *，好和路由模式比对。"""
    return re.sub(r"\{[^}]+\}", "*", path)


def is_implemented(path: str, implemented: set[str]) -> bool:
    """文档路径能不能对上某个实际路由。

    先按原样比对；对不上时把最后一段当作动态段再试一次——文档里写具体
    示例（/api/v1/stories/e19143f02e051）比写 {id} 更好用，那种写法应该
    算命中 stories/[publicId]，而不是被判成"端点不存在"。
    """
    if path in implemented:
        return True
    head, _, _ = path.rpartition("/")
    return bool(head) and f"{head}/*" in implemented


class AgentAccessStructureTests(unittest.TestCase):
    def test_all_access_surfaces_exist(self):
        expected = [
            # REST v1
            "app/api/v1/items/route.ts",
            "app/api/v1/hot-topics/route.ts",
            "app/api/v1/stories/[publicId]/route.ts",
            "app/api/v1/dailies/route.ts",
            "app/api/v1/dailies/latest/route.ts",
            "app/api/v1/dailies/[date]/route.ts",
            "app/api/v1/topics/route.ts",
            "app/api/v1/topics/[slug]/route.ts",
            # MCP
            "app/api/mcp/route.ts",
            "lib/mcp/tools.ts",
            "lib/mcp/format.ts",
            # RSS
            "app/feed.xml/route.ts",
            "app/feed/all.xml/route.ts",
            "app/feed/daily.xml/route.ts",
            "app/feed/category/[slug]/route.ts",
            "lib/feed/rss.ts",
            "lib/feed/load.ts",
            # 文档出口
            "app/llms.txt/route.ts",
            "app/openapi-v1.json/route.ts",
            "lib/v1/openapi.ts",
            # 接入页
            "app/agent/page.tsx",
            "app/agent/access-tabs.tsx",
            # 共享层
            "lib/v1/http.ts",
            "lib/v1/params.ts",
            "lib/v1/shape.ts",
            "lib/v1/items.ts",
            "lib/v1/daily.ts",
            "lib/v1/upstream.ts",
            # Skill 包
            "public/ai-radar-skill/SKILL.md",
            "public/ai-radar-skill/install.sh",
            "public/ai-radar-skill/VERSION",
        ]
        for relative in expected:
            self.assertTrue((WEB / relative).exists(), relative)


class DocumentedEndpointsExistTests(unittest.TestCase):
    """文档里写出来的端点必须真的有实现。"""

    @classmethod
    def setUpClass(cls):
        cls.implemented = route_patterns(WEB / "app" / "api" / "v1", "/api/v1")

    def assert_documented_paths_exist(self, source: Path):
        text = read(source)
        # 只抓 /api/v1/... 形式的端点，忽略示例里的查询串
        documented = {
            normalize(match.rstrip("/"))
            for match in re.findall(r"/api/v1/[A-Za-z0-9_\-{}|]+(?:/[A-Za-z0-9_\-{}|]+)*", text)
        }
        self.assertTrue(documented, f"{source} 里没有提到任何 v1 端点，提取逻辑可能失效了")
        for path in documented:
            self.assertTrue(
                is_implemented(path, self.implemented),
                f"{source.name} 提到了 {path}，但 app/api/v1 下没有对应的 route.ts",
            )

    def test_agent_page_endpoints_are_implemented(self):
        self.assert_documented_paths_exist(AGENT_PAGE)

    def test_skill_endpoints_are_implemented(self):
        self.assert_documented_paths_exist(SKILL_MD)

    def test_llms_txt_endpoints_are_implemented(self):
        self.assert_documented_paths_exist(LLMS_TXT)

    def test_openapi_paths_match_routes_exactly(self):
        # OpenAPI 是字段与端点的权威来源，必须双向一致：既不能少写，也不能
        # 留下已经删掉的端点。
        declared = {
            normalize(path) for path in re.findall(r'"(/api/v1/[^"]*)": \{\s*\n\s*get:', read(OPENAPI))
        }
        self.assertEqual(declared, self.implemented)

    def test_feed_paths_are_implemented(self):
        implemented = route_patterns(WEB / "app" / "feed", "/feed") | {"/feed.xml"}
        for source in (AGENT_PAGE, LLMS_TXT):
            documented = {
                normalize(match)
                for match in re.findall(
                    # 路径可能有多段：/feed/category/{model|...}.xml
                    r"/feed(?:\.xml|(?:/[A-Za-z0-9_\-{}|]+)+(?:\.xml)?)",
                    read(source),
                )
            }
            self.assertTrue(documented, f"{source} 里没提到任何 feed")
            for path in documented:
                # /feed/category/{...}.xml 走的是 [slug] 动态段，扩展名是地址的
                # 一部分而不是独立路由段
                candidate = re.sub(r"/\*\.xml$", "/*", path)
                self.assertIn(
                    candidate,
                    implemented,
                    f"{source.name} 提到了 {path}，但 app/feed 下没有对应实现",
                )


class McpToolConsistencyTests(unittest.TestCase):
    """MCP 工具名在实现、页面与文档之间必须一致。

    工具名写错的后果特别隐蔽：客户端能连上、能列出工具，只是用户照着页面
    要求调用某个名字时永远调不到。
    """

    @classmethod
    def setUpClass(cls):
        source = read(MCP_TOOLS)
        cls.declared = set(re.findall(r'name: "(radar_[a-z_]+)"', source))
        # HANDLERS 表里的键是真正会被调用的那份名单
        handlers_block = source.split("const HANDLERS")[1]
        cls.handlers = set(re.findall(r"(radar_[a-z_]+):", handlers_block))

    def test_every_declared_tool_has_a_handler(self):
        self.assertTrue(self.declared, "没有从 tools.ts 里提取到工具定义")
        self.assertEqual(
            self.declared,
            self.handlers,
            "tools/list 公布的工具与 HANDLERS 里能调用的工具对不上",
        )

    def test_agent_page_lists_every_tool(self):
        listed = set(re.findall(r'"(radar_[a-z_]+)"', read(AGENT_PAGE)))
        self.assertEqual(listed, self.declared, "/agent 页面的工具清单和实现对不上")

    def test_tool_count_claim_matches_reality(self):
        # 页面和 llms.txt 都写了"六个工具"，数字变了文案必须跟着改
        self.assertEqual(len(self.declared), 6)
        self.assertIn("六个工具", read(AGENT_PAGE))
        self.assertIn("六个工具", read(LLMS_TXT))

    def test_llms_txt_names_every_tool(self):
        text = read(LLMS_TXT)
        for name in self.declared:
            self.assertIn(name, text, f"llms.txt 没有提到工具 {name}")


class ContractInvariantTests(unittest.TestCase):
    """几条一旦破坏就会静默失效的约定。"""

    def test_v1_payloads_carry_no_wall_clock_field(self):
        # payload 里放 Date.now() 会让每次响应的 ETag 都不同，条件请求
        # 与共享缓存一起失效，而且不报错——只是所有轮询都变成全量下载。
        for route in (WEB / "app" / "api" / "v1").rglob("route.ts"):
            source = read(route)
            self.assertNotIn(
                "generatedAt",
                source,
                f"{route.relative_to(WEB)} 的响应体里出现了随时刻变化的字段，会让 ETag 永久失效",
            )

    def test_v1_routes_share_the_response_layer(self):
        # 绕过 handleV1 自己 new Response，就会在错误格式、ETag 或 CORS 上
        # 和别的端点不一致。
        for route in (WEB / "app" / "api" / "v1").rglob("route.ts"):
            source = read(route)
            self.assertIn("handleV1", source, f"{route.relative_to(WEB)} 没有走统一响应层")
            self.assertIn("OPTIONS", source, f"{route.relative_to(WEB)} 没有导出 CORS 预检")

    def test_every_tab_panel_stays_in_the_dom(self):
        """四个面板必须全部渲染，用 hidden 收起非当前项。

        只渲染选中的那个是最自然的"优化"，但这页有一半读者是 Agent——
        llms.txt 把它列为入口，抓 HTML 只拿到四分之一内容是实打实的损失。
        hidden 的内容对爬虫和 Ctrl+F 都还在。
        """
        source = read(ACCESS_TABS)
        self.assertIn("hidden={tab.id !== active}", source)
        # 只有一个 tabpanel 渲染点，且它在对 tabs 的完整 map 里
        self.assertEqual(source.count('role="tabpanel"'), 1)
        panel_at = source.index('role="tabpanel"')
        self.assertLess(source.rindex("tabs.map(", 0, panel_at), panel_at)

    def test_agent_page_wires_all_four_paths(self):
        source = read(AGENT_PAGE)
        for tab_id in ("skill", "mcp", "rss", "rest"):
            self.assertIn(f'id: "{tab_id}"', source)

    def test_no_surface_claims_a_fixed_daily_publish_time(self):
        """本站没有定时发布，任何"每天 XX:00 发布"都是编的。

        调度是按 interval_minutes 轮询的（apps/api 的 run_scheduler_tick），
        实测各期 generated_at 落在北京时间 16:24 / 22:05 / 23:51 / 19:31。
        照抄同类站点的"每天 08:00 发布"曾经写进了页面、llms.txt、OpenAPI、
        MCP 工具描述，以及 daily feed 每一条的 pubDate——最后那个尤其糟：
        它给每个订阅者的时间线注入了假时间戳。
        """
        surfaces = [AGENT_PAGE, LLMS_TXT, SKILL_MD, MCP_TOOLS, OPENAPI]
        for path in surfaces:
            self.assertNotRegex(
                read(path),
                r"每天\s*\d{1,2}:\d{2}",
                f"{path.name} 声称了一个固定的日报发布时刻，但本站没有定时发布",
            )

    def test_daily_feed_timestamps_come_from_the_data(self):
        source = read(WEB / "app" / "feed" / "daily.xml" / "route.ts")
        # pubDate 必须取自这一期真实的生成时刻
        self.assertIn("generated_at", source)
        # 不得按期次日期拼一个固定钟点
        self.assertNotRegex(
            source,
            r"\$\{[^}]+\}T\d{2}:\d{2}",
            "daily feed 在用期次日期拼固定钟点，这是编造的发布时间",
        )

    def test_time_basis_never_fails_open_to_published(self):
        """缺失的 time_basis 必须是 null，不能当成 published。

        抓取层拿不到原文时间时会退回 now()（crawlers/base.py 的
        `published_at or datetime.now()`），而只有 SourcePilot 来源会显式标
        time_basis——实测公开端点 0/51 条带这个字段。把缺失兜底成 "published"，
        等于对每一条都声称"这是原文发布时间"，正是 SourcePilot 契约禁止的事。
        """
        shape = read(WEB / "lib" / "v1" / "shape.ts")
        self.assertNotIn(
            '=== "discovered" ? "discovered" : "published"',
            shape,
            "timeBasis 又被兜底成 published 了",
        )
        # 三态必须在类型上写明
        self.assertIn('"published" | "discovered" | null', shape)

    def test_errors_do_not_echo_internal_detail(self):
        """对外的错误文案不得回显异常消息。

        error.message 里带着内网路径和上游状态码（"上游 /api/public/… 返回 500"），
        回显给任何一个匿名调用者都是信息泄露。
        """
        for relative in ("lib/v1/http.ts", "lib/feed/load.ts", "app/feed/daily.xml/route.ts"):
            source = read(WEB / relative)
            self.assertNotRegex(
                source,
                r"(数据源暂时不可用|服务内部错误)[^\n]*\$\{detail\}",
                f"{relative} 把异常消息回显给了客户端",
            )

    def test_transient_and_permanent_failures_are_distinguished(self):
        """上游 4xx 不能报成 503。

        SKILL.md 和 OpenAPI 都告诉客户端"503 → 退避后重试"。把本层的 bug
        （发了个上游不认的请求）也报成 503，客户端就会永远重试一个永久故障。
        """
        source = read(WEB / "lib" / "v1" / "http.ts")
        self.assertIn("UpstreamError", source)
        self.assertIn("internal_error", source)

    def test_lookup_tables_do_not_walk_the_prototype_chain(self):
        """按用户输入查表必须用 Object.hasOwn。

        普通对象索引会命中 Object.prototype：MCP 的 tools/call 传
        name="constructor" 曾拿到 Object 函数并把非字符串塞进 content[0].text
        （违反 MCP 协议），/feed/category/__proto__.xml 曾绕过 404 守卫产出一个
        标题为 "[object Object]" 的 feed。改用 Map 也可以，但那时要一并改本测试。
        """
        for relative in ("lib/mcp/tools.ts", "app/feed/category/[slug]/route.ts"):
            self.assertIn(
                "Object.hasOwn",
                read(WEB / relative),
                f"{relative} 在用裸索引按用户输入查表",
            )

    def test_todays_daily_is_not_served_from_the_archived_tier(self):
        """当天那一期还在滚动，三个入口必须同档。

        套用"封版后不再变"的一小时档，会让 /api/v1/dailies/{今天} 与
        /api/v1/dailies/latest 在长达一小时里对同一期各说各话。
        """
        self.assertIn("dailyCacheTier", read(WEB / "lib" / "v1" / "daily.ts"))
        for relative in (
            "app/api/v1/dailies/[date]/route.ts",
            "lib/mcp/tools.ts",
            "app/feed/daily.xml/route.ts",
        ):
            source = read(WEB / relative)
            self.assertIn("dailyCacheTier", source, f"{relative} 没有按期次选缓存档位")
            self.assertNotIn(
                "revalidate: CACHE.dailyArchived",
                source,
                f"{relative} 对所有期次都用了归档档位",
            )

    def test_story_endpoint_does_not_expose_third_party_body(self):
        # 站内阅读页可以展示原文，但通过 API 批量取走是再分发。
        shape = read(WEB / "lib" / "v1" / "shape.ts")
        for field in ("original_paragraphs", "original_blocks", "translated_paragraphs"):
            self.assertNotIn(field, shape.split("export function shapeStory")[1])


class SkillPackageTests(unittest.TestCase):
    def test_skill_frontmatter_is_valid(self):
        text = read(SKILL_MD)
        self.assertTrue(text.startswith("---\n"), "SKILL.md 必须以 frontmatter 开头")
        # install.sh 就是按这两条校验下载结果的，改了这里要同步改那边
        self.assertIn("\nname: ai-radar\n", text)
        self.assertRegex(text, r"\ndescription: .+")

    def test_version_is_semver(self):
        self.assertRegex(read(SKILL_DIR / "VERSION").strip(), r"^\d+\.\d+\.\d+$")

    def test_installer_syntax_is_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SKILL_DIR / "install.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_installer_keeps_its_safety_rails(self):
        source = read(SKILL_DIR / "install.sh")
        self.assertIn("set -euo pipefail", source)
        # 必须显式 --target：装错目录的 Skill 不报错，只是永远不触发
        self.assertIn("必须指定 --target", source)
        # 目标目录不是本 Skill 时要停下，而不是覆盖
        self.assertIn("安装器不会覆盖别人的东西", source)
        # 替换旧版本只能用 mv 备份，绝不能对用户目录做 rm -rf
        self.assertNotIn("rm -rf \"$INSTALL_DIR\"", source)
        self.assertNotIn("rm -rf \"${INSTALL_DIR}\"", source)

    def test_installer_handles_a_valueless_target_flag(self):
        """`install.sh --target`（漏了值）必须给出提示。

        原来是 `--target) TARGET="${2:-}"; shift 2`，$# 只有 1 时 shift 2 返回
        非零，set -e 让脚本一声不吭地退出——用户连"必须指定 --target"都看不到。
        """
        result = subprocess.run(
            ["bash", str(SKILL_DIR / "install.sh"), "--target"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            result.stderr.strip() or result.stdout.strip(),
            "--target 缺值时脚本没有任何输出",
        )

    def test_installer_verifies_download_before_touching_disk(self):
        source = read(SKILL_DIR / "install.sh")
        verify_at = source.index("下载到的 SKILL.md 是空的")
        install_at = source.index('mv "$STAGED_FINAL" "$INSTALL_DIR"')
        self.assertLess(verify_at, install_at, "必须先校验下载结果，再动目标目录")


if __name__ == "__main__":
    unittest.main()
