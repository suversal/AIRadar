"""image-proxy 的准入守卫（apps/web/lib/image-proxy-guard.ts）的回归约束。

这个仓库的 web 侧没有 JS 测试框架，所以和 test_image_proxy_route.py 一样，
用源码断言锁住几条容易在重构中被改掉的关键性质。

行为层面的验证方式（本地 Mac 跑不了，见下）记录在
docs/2026-08-13-hardening-plan.md 第 1.2 节：把 guard 编译成 JS，
在 greenvps 上用 node:22-alpine 容器跑 25 条用例。
之所以必须去服务器上跑：这台 Mac 的代理软件开了 DNS 覆写，
会把所有域名解析成 198.18.x.x（RFC 2544 基准测试网段），
本地和 Docker Desktop 里都拿不到真实解析结果。
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "apps" / "web" / "lib" / "image-proxy-guard.ts"
ROUTE = ROOT / "apps" / "web" / "app" / "api" / "image-proxy" / "route.ts"


class ImageProxyGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = GUARD.read_text(encoding="utf-8")
        self.route = ROUTE.read_text(encoding="utf-8")

    def test_blocks_cloud_metadata_and_private_ranges(self):
        # 169.254/16 里的元数据服务是 SSRF 最常见的目标
        self.assertIn("a === 169 && b === 254", self.guard)
        self.assertIn("a === 10", self.guard)
        self.assertIn("a === 127", self.guard)
        self.assertIn("a === 172 && b >= 16 && b <= 31", self.guard)
        self.assertIn("a === 192 && b === 168", self.guard)

    def test_ipv6_is_parsed_not_prefix_matched(self):
        # WHATWG URL 会把 ::ffff:127.0.0.1 规范化成 ::ffff:7f00:1，
        # 用字符串前缀匹配会直接漏掉 IPv4 映射地址。必须真的展开成 8 组。
        self.assertIn("function expandIpv6", self.guard)
        self.assertIn("groups[5] === 0xffff", self.guard)
        self.assertIn("0xfc00", self.guard)  # fc00::/7
        self.assertIn("0xfe80", self.guard)  # fe80::/10

    def test_all_resolved_addresses_are_checked(self):
        # 多 A 记录里混一条 127.0.0.1 是标准绕过手法，不能只看第一条
        self.assertIn("lookup(bare, { all: true })", self.guard)
        self.assertIn("for (const { address, family } of addresses)", self.guard)

    def test_redirects_are_followed_manually_and_revalidated(self):
        # 先校验域名、再让上游 302 到内网，是绕过 SSRF 防护的标准手法：
        # 每一跳都必须重新过 assertPublicHost
        self.assertIn('redirect: "manual"', self.route)
        self.assertIn("for (let hop = 0; hop <= MAX_REDIRECTS", self.route)
        self.assertIn("const guard = await assertPublicHost(target)", self.route)

    def test_response_size_and_timeout_are_capped(self):
        self.assertIn("MAX_IMAGE_BYTES", self.route)
        self.assertIn("function cappedBody", self.route)
        self.assertIn("UPSTREAM_TIMEOUT_MS", self.route)
        # 只看 Content-Length 不够：分块传输可以不带这个头
        self.assertIn("received > MAX_IMAGE_BYTES", self.route)

    def test_fake_ip_escape_hatch_is_opt_in_and_narrow(self):
        # 开发机的代理软件把域名解析成 198.18.x.x，撞上"基准测试网段"这一条，
        # 本地推文图片会全白。开发口子必须满足两点：显式打开、且只松这一段。
        self.assertIn("IMAGE_PROXY_ALLOW_FAKE_IP", self.guard)
        self.assertIn('=== "1"', self.guard)
        self.assertIn(
            "(a === 198 && (b === 18 || b === 19) && !allowsFakeIpRange())",
            self.guard,
        )
        # 其余内网段不受这个开关影响——尤其是云元数据所在的 169.254/16
        for line in self.guard.splitlines():
            if "allowsFakeIpRange()" in line and "a === 198" not in line:
                self.assertNotIn("a === ", line, f"开关泄漏到了其它网段: {line}")

    def test_unknown_hosts_are_logged_but_not_blocked_by_default(self):
        # 硬白名单会造成静默的"图片全白"事故，所以默认只记日志，
        # 靠 IMAGE_PROXY_ENFORCE_HOSTS=1 显式切换成强制模式
        self.assertIn("IMAGE_PROXY_ENFORCE_HOSTS", self.guard)
        self.assertIn("[image-proxy] unknown host:", self.route)
        self.assertIn("shouldEnforceKnownHosts() && !isKnownImageHost", self.route)

    def test_own_image_host_is_in_the_known_list(self):
        # 后台手动上传的图落在 img.suversal.com（IMAGE_HOST_BASE_URL 的默认值）。
        # 它原先不在名单里，一旦打开 IMAGE_PROXY_ENFORCE_HOSTS=1，
        # 自己上传的图会被自己 403 掉。
        self.assertIn('"suversal.com"', self.guard)
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("IMAGE_HOST_BASE_URL=https://img.suversal.com/upload", env_example)


if __name__ == "__main__":
    unittest.main()
