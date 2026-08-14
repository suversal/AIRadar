// 访问统计埋点（自托管 umami，见 infra/docker-compose.prod.yml 的 umami 服务）。
//
// 为什么是一段内联脚本动态注入 <script>，而不是直接写 <script src="/s.js">：
// 根 layout 覆盖所有路由（含 /admin），而 Server Component 里拿不到 pathname，
// 所以路径判断只能发生在浏览器侧。一段内联脚本同时办完三件事：
// 排除后台路径、注入 tracker、把稳定的匿名 ID 交给 umami。
//
// 路径 /s.js 与上报口 /api/collect 都是改过的非默认值（默认的 /script.js 与
// /api/send 已被 EasyPrivacy 一类名单按路径收录）。这三处必须一致，改一个就断：
//   - 这里的 SCRIPT_SRC
//   - infra/docker-compose.prod.yml 的 TRACKER_SCRIPT_NAME / COLLECT_API_ENDPOINT
//   - infra/nginx/radar-cf.conf 里那两个精确 location
//
// ── 关于 VISITOR_KEY 这个匿名 ID 的实际作用，别搞错（读过 umami 源码后的结论）──
// umami 的留存报表（src/queries/sql/reports/getRetention.ts）是 `group by
// website_event.session_id` 算的，**完全不消费 distinct_id**。而 session_id 是
// uuid(websiteId, ip, userAgent, salt)，那个 salt 按自然月轮换
// （src/app/api/send/route.ts: `process.env.SALT_ROTATION || 'month'`）。
// 两个后果：
//   1. 面板里的 Retention 只在**同一个自然月内**成立，跨月边界会断——
//      月底首访的人在下个月回访会被当成全新访客，格子显示 0%，那是假象不是事实。
//   2. 这个 ID 修不了上面那条。它的价值在别处：它让 website_event.distinct_id
//      成为一个**跨月稳定**的标识，于是真正的跨月留存可以直接查库算出来
//      （SQL 见 docs/notes/2026-08-14-analytics-selection.md）。
// 换句话说：面板看月内趋势，跨月留存靠这个 ID 自己查。
//
// 纯第一方 localStorage，不设 cookie、不涉及跨站追踪。
const VISITOR_KEY = "ai-radar-visitor";
const SCRIPT_SRC = "/s.js";

function buildScript(websiteId: string) {
  // JSON.stringify 而不是裸插值：websiteId 虽然来自我们自己的构建参数，
  // 但拼进内联脚本的值一律走转义，不给注入留形状。
  return `
(function () {
  try {
    if (location.pathname.indexOf("/admin") === 0) return;

    var id = null;
    try {
      id = localStorage.getItem(${JSON.stringify(VISITOR_KEY)});
      if (!id) {
        id = (window.crypto && crypto.randomUUID)
          ? crypto.randomUUID()
          : String(Date.now()) + Math.random().toString(36).slice(2);
        localStorage.setItem(${JSON.stringify(VISITOR_KEY)}, id);
      }
    } catch (e) {
      // 隐私模式下 localStorage 可能直接抛异常。拿不到 ID 不该连埋点一起废掉，
      // 照常统计，只是这个访客没有跨月标识。
    }

    var s = document.createElement("script");
    s.defer = true;
    s.src = ${JSON.stringify(SCRIPT_SRC)};
    s.setAttribute("data-website-id", ${JSON.stringify(websiteId)});
    if (id) {
      s.addEventListener("load", function () {
        // 签名是 identify(unique_id: string)。传对象是另一个意思——
        // 那是"只附加 session 数据、不设身份"，写成 identify({id: id}) 会静默失效。
        if (window.umami && typeof window.umami.identify === "function") {
          window.umami.identify(id);
        }
      });
    }
    document.head.appendChild(s);
  } catch (e) {}
})();
`;
}

export function AnalyticsScript() {
  // 构建时内联（见 infra/Dockerfile.web 的 ARG）。留空则什么都不渲染，
  // 本地 dev 和没配这个变量的部署天然不埋点。
  const websiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
  if (!websiteId) {
    return null;
  }
  return <script dangerouslySetInnerHTML={{ __html: buildScript(websiteId) }} />;
}
