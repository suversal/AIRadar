import { ArrowUpRight, BookOpen, Braces, FileText, type LucideIcon } from "lucide-react";
import { AccessTabs } from "./access-tabs";
import { CopyButton } from "@/components/copy-button";
import { StaticPage } from "@/components/static-page";
import { siteUrl } from "@/lib/site";
import type { ReactNode } from "react";

export const metadata = {
  title: "Agent 接入",
  description:
    "AI·RADAR 的公开数据有四条接入路径：Agent Skill、MCP Server、RSS 与 REST API v1。全部匿名只读，不需要 API Key。",
  alternates: { canonical: "/agent" },
};

const host = siteUrl.replace(/^https?:\/\//, "");

/**
 * 配套文件入口。
 *
 * 刻意不做成页面顶部的一排 chip：那样每个只剩一个裸标签，读者第一眼认不出
 * 是什么。改成挂在它服务的那段说明旁边——OpenAPI 出现在讲字段的地方，
 * SKILL.md 出现在"装之前先读一遍"旁边——链接自带语境。
 */
function ResourceLink({
  href,
  icon: Icon,
  title,
  desc,
}: {
  href: string;
  icon: LucideIcon;
  title: ReactNode;
  desc: string;
}) {
  return (
    <a
      href={href}
      className="flex items-center gap-3 rounded-md border border-line bg-canvas px-3.5 py-3 transition-colors hover:border-signal/50"
    >
      <Icon className="h-[17px] w-[17px] shrink-0 text-signal" aria-hidden />
      <span className="min-w-0 grow">
        <span className="block text-[13px] text-ink">{title}</span>
        <span className="mt-0.5 block text-xs leading-[18px] text-ink-dim">{desc}</span>
      </span>
      <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-ink-dim" aria-hidden />
    </a>
  );
}

function Code({ label, code }: { label: string; code: string }) {
  return (
    <div className="rounded-md border border-line bg-canvas">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-1.5">
        <span className="text-xs text-ink-dim">{label}</span>
        <CopyButton text={code} />
      </div>
      <pre className="readout overflow-x-auto px-3 py-3 text-xs leading-6 text-ink">{code}</pre>
    </div>
  );
}

function PanelHead({ title, lead }: { title: string; lead: string }) {
  return (
    <div>
      <h2 className="text-[17px] font-semibold text-ink">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-ink-mid">{lead}</p>
    </div>
  );
}

function Note({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border-l-4 border-signal bg-signal/10 p-4 text-sm leading-6 text-ink-mid">
      <p className="font-semibold text-signal-bright">{title}</p>
      <div className="mt-1.5 space-y-1.5">{children}</div>
    </div>
  );
}

function Endpoint({ path, children }: { path: string; children: ReactNode }) {
  return (
    <div className="border-b border-line py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="readout rounded border border-signal/40 px-1.5 py-0.5 text-[10px] font-semibold text-signal">
          GET
        </span>
        <code className="readout min-w-0 break-all text-[13px] text-ink">{path}</code>
      </div>
      <p className="mt-1 text-xs leading-5 text-ink-dim">{children}</p>
    </div>
  );
}

const TOOLS = [
  ["radar_get_latest", "过去 24 小时或最近 7 天的精选／全部收录"],
  ["radar_search", "在最近 7 天里搜模型、公司、产品或人物"],
  ["radar_get_hot_topics", "当前热点榜，按多信源热度排序"],
  ["radar_get_story", "一个事件的详情与多信源报道时间线"],
  ["radar_get_daily", "最新或指定日期的 AI 日报"],
  ["radar_get_topics", "主题档案与本周雷达：什么正在变热"],
];

const FEEDS = [
  {
    name: "精选",
    recommended: true,
    path: "/feed.xml",
    desc: "最新 50 条精选，含中文摘要与推荐理由。第一次接入选这个。",
  },
  {
    name: "全部动态",
    path: "/feed/all.xml",
    desc: "最近 7 天全部收录，按发布时间倒序，未经精选阈值过滤。量比精选大一个量级。",
  },
  {
    name: "日报",
    path: "/feed/daily.xml",
    desc: "每天一期的精编日报，含 AI 主线综述，保留最近 10 期。当天那一期会随抓取滚动补充。",
  },
  {
    name: "分类",
    path: "/feed/category/{model|product|industry|research|tutorial}.xml",
    desc: "精选中归入某个分类的条目。",
  },
];

const ITEM_PARAMS = [
  ["mode", "selected", "selected 精选（推荐）｜all 同窗口全部收录"],
  ["window", "7d", "24h ｜ 7d。只有这两个原生窗口"],
  ["limit", "50", "1–100"],
  ["offset", "0", "0–10000"],
  ["category", "—", "model / product / industry / research / tutorial"],
  ["focus", "—", "model / product / technology / industry / tutorial"],
  ["q", "—", "关键词，2–200 字"],
];

// timeBasis 不在这张表里：它有三态且缺省值反直觉，一格说明写不下，
// 单独做成表格下面那个说明块。
const KEY_FIELDS = [
  ["title", "中文标题，AI 基于第三方报道生成"],
  ["summary", "中文摘要。引用数字或原话前请回原文核对"],
  ["reason", "推荐理由：这条为什么值得看"],
  ["score", "0–100 综合评分"],
  ["selected", "是否入选精选。阈值按分类不同，别从 score 反推"],
  ["sourceCount", "几家信源报道了这件事"],
  ["topics", "主题归属，可与 /api/v1/topics 的 id 对上"],
  ["publishedAt", "时间戳。它的性质由 timeBasis 决定，见下"],
  ["links.radar", "站内阅读页。引用时优先给用户这个"],
  ["links.original", "第三方原文地址"],
];

const ERRORS = [
  ["400", "invalid_parameter 等", "参数不合法、未声明或重复。按报错改正，不要退化成更宽的查询——接口不会自动改成边界值。"],
  ["404", "not_found", "事件 ID 或日期不存在。ID 只能来自其它端点的返回，不要自行构造。"],
  ["500", "internal_error", "服务端自己的问题，重试不会改善。别按 503 那样反复重试，把 requestId 提交到反馈页。"],
  ["503", "upstream_unavailable", "数据源暂时不可用。退避后重试，不要并发重试。"],
];

function SkillPanel() {
  return (
    <>
      <PanelHead
        title="装一次，之后直接用中文问"
        lead="不用记端点也不用写代码。适合 Claude Code，以及其它会从本机 skills 目录加载 Agent Skill 的工具。"
      />

      <div className="grid gap-2.5 sm:grid-cols-3">
        {[
          ["01", "把提示词发给 Agent", "安装器不猜平台、不覆盖别家 Skill，发现重复副本会停下来问你。"],
          ["02", "开一个新会话", "多数 Agent 只在会话开始时扫描 Skill，当前对话不一定看得到。"],
          ["03", "问一句验证", "看到时间窗、中文摘要和站内链接，就算接上了。"],
        ].map(([step, title, desc]) => (
          <div key={step} className="rounded-md border border-line bg-canvas p-3">
            <div className="readout text-[11px] text-signal">{step}</div>
            <div className="mt-1 text-[13px] font-semibold text-ink">{title}</div>
            <div className="mt-1 text-xs leading-[18px] text-ink-dim">{desc}</div>
          </div>
        ))}
      </div>

      <Code
        label="安装提示词"
        code={`请安装 AI·RADAR Skill：${siteUrl}/ai-radar-skill/SKILL.md
安装器在 ${siteUrl}/ai-radar-skill/install.sh，请先读一遍再执行。
装完告诉我是否需要开启新会话。`}
      />

      <ResourceLink
        href="/ai-radar-skill/SKILL.md"
        icon={BookOpen}
        title={
          <>
            装之前可以先读一遍 <code className="readout text-signal">SKILL.md</code>
          </>
        }
        desc="Skill 正文：它会让 Agent 调哪些端点、怎么措辞、哪些事做不到"
      />

      <div>
        <p className="text-sm font-semibold text-ink">或者手动安装</p>
        <p className="mt-1 text-xs leading-5 text-ink-dim">
          <code className="readout">--target agents</code> 装到共享目录{" "}
          <code className="readout">~/.agents/skills/ai-radar</code>
          ；如果你的 Agent 从这里加载 Skill，装一次就能被发现。
          <code className="readout">--target claude</code> 会额外创建一个指向同一目录的软链，
          不复制第二份正文，升级只需动一处。我们只在 Claude Code 上验证过，其它工具的 skills
          目录约定请以它自己的文档为准。执行前请先审阅 install.sh 与 SKILL.md。
        </p>
        <div className="mt-3 space-y-3">
          <Code
            label="通用 Agent Skills 目录"
            code={`bash <(curl -fsSL ${siteUrl}/ai-radar-skill/install.sh) --target agents`}
          />
          <Code
            label="Claude Code"
            code={`bash <(curl -fsSL ${siteUrl}/ai-radar-skill/install.sh) --target claude`}
          />
        </div>
      </div>

      <Code label="装好后这样验证" code="过去 24 小时 AI 圈最重要的 5 件事是什么？" />
      <p className="text-xs leading-5 text-ink-dim">
        成功的样子：回答注明「过去 24 小时」，给出 5 条中文摘要（当天不足就如实说明只有几条），
        标题链接到本站阅读页。
      </p>

      <Note title="没触发？按这个顺序排查">
        <p>1. 文件名必须严格是 SKILL.md，且在当前 Agent 支持的 skills 目录里。</p>
        <p>2. 关掉旧会话，新开一个，再问一次上面的验证问题。</p>
        <p>3. 让 Agent 列出它发现的 skills，确认里面有 ai-radar。</p>
        <p>
          4. 仍失败：把平台、版本和安装路径提交到{" "}
          <a className="text-signal underline hover:text-signal-bright" href="/feedback">
            反馈页
          </a>
          ，别贴 token 或本地文件内容。
        </p>
      </Note>
    </>
  );
}

function McpPanel() {
  return (
    <>
      <PanelHead
        title="加一个地址，Agent 直接调六个工具"
        lead="适合支持远程 MCP 的 Agent 与开发工具。标准 Streamable HTTP，匿名只读，不需要 token，也不会读取登录态。"
      />

      <Code label="MCP 端点" code={`${siteUrl}/api/mcp`} />

      <Code
        label="通用 MCP 配置"
        code={`{
  "mcpServers": {
    "ai-radar": {
      "type": "http",
      "url": "${siteUrl}/api/mcp"
    }
  }
}`}
      />

      <Code label="Claude Code" code={`claude mcp add --transport http ai-radar '${siteUrl}/api/mcp'`} />

      <p className="text-xs leading-5 text-ink-dim">
        不同客户端的配置入口名称各异，核心只有 server 名称与上面这个 URL，不要填 API Key。
        客户端若只接受本地命令、不支持远程 HTTP，需要先用它自己的远程 MCP 代理。
      </p>

      <div>
        <p className="text-sm font-semibold text-ink">连上后应该看到这六个工具</p>
        <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
          {TOOLS.map(([name, desc]) => (
            <div key={name} className="rounded-md border border-line bg-canvas px-3 py-2.5">
              <code className="readout text-xs text-signal">{name}</code>
              <p className="mt-1 text-xs leading-[18px] text-ink-dim">{desc}</p>
            </div>
          ))}
        </div>
      </div>

      <Code
        label="验证一次真实调用"
        code="请调用 radar_get_latest，告诉我过去 24 小时最重要的 5 条 AI 资讯，并附上链接。"
      />

      <Note title="工具边界与恢复方式">
        <p>
          普通查询最多 30 条，热点榜最多 10 条。输入越界会明确报错，
          <strong className="text-ink">不会静默改成更宽的查询</strong>——拿到 30 条却以为是全部，
          会让 Agent 说出「本周只有 30 条动态」这种错话。
        </p>
        <p>radar_get_story 的事件 ID 只能来自其它工具的返回，不要猜。</p>
        <p>
          连接失败先确认 URL 完整、客户端支持远程 Streamable HTTP，并刷新工具列表。
          本服务无会话状态，不提供 SSE 推送流，对 <code className="readout">/api/mcp</code> 发 GET
          会返回 405，这是正常的。
        </p>
      </Note>
    </>
  );
}

function RssPanel() {
  return (
    <>
      <PanelHead
        title="复制地址即可订阅"
        lead="兼容主流 RSS 2.0 阅读器，以及 n8n、Zapier 这类自动化工具。第一次接入选精选。"
      />

      <div className="divide-y divide-line">
        {FEEDS.map((feed) => (
          <div key={feed.path} className="py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-ink">{feed.name}</span>
              {feed.recommended ? (
                <span className="rounded border border-signal/40 px-1.5 py-0.5 text-[11px] text-signal">
                  推荐
                </span>
              ) : null}
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <code className="readout min-w-0 break-all text-xs text-ink-mid">
                {host}
                {feed.path}
              </code>
              {feed.path.includes("{") ? null : <CopyButton text={`${siteUrl}${feed.path}`} />}
            </div>
            <p className="mt-1.5 text-xs leading-5 text-ink-dim">{feed.desc}</p>
          </div>
        ))}
      </div>

      <Note title="给阅读器与自动化工具的合同">
        <p>支持 ETag 条件请求，未变化返回 304；建议每 30 分钟或更慢轮询。</p>
        <p>
          条目 <code className="readout">link</code> 指向站内阅读页，第三方原文放在{" "}
          <code className="readout">description</code> 里。
          <code className="readout">guid</code> 是事件 ID 而非 URL，站内地址改版不会让旧条目被重推一遍。
        </p>
        <p>
          <strong className="text-ink">只输出摘要，不内联正文。</strong>
          内联第三方原文等于替信源做再分发，我们没有拿到那份授权。
        </p>
      </Note>
    </>
  );
}

function RestPanel() {
  return (
    <>
      <PanelHead
        title="匿名 GET，字段以 OpenAPI 为准"
        lead="响应支持 CORS 与 ETag 条件请求，错误是 RFC 9457 Problem JSON。"
      />

      <ResourceLink
        href="/openapi-v1.json"
        icon={Braces}
        title={
          <>
            完整字段定义在 <code className="readout text-signal">openapi-v1.json</code>
          </>
        }
        desc="参数、响应结构与错误码以它为准，本页只挑常用的说"
      />

      <Code label="第一个请求" code={`curl '${siteUrl}/api/v1/items?window=24h&limit=10'`} />

      <div className="[&>*:last-child]:border-b-0">
        <Endpoint path="/api/v1/items">
          精选或最近 7 天全部收录；支持 24h／7d 窗口、分类、焦点与关键词筛选，按发布时间倒序。
        </Endpoint>
        <Endpoint path="/api/v1/hot-topics">
          当前热点榜。按多信源热度排序，回答「现在什么最热」，与按时间排序的 items 是两个口径。
        </Endpoint>
        <Endpoint path="/api/v1/stories/{id}">
          单个事件的详情与多信源报道时间线。id 来自其它端点返回的 items[].id。
        </Endpoint>
        <Endpoint path="/api/v1/dailies">日报期次索引，最新的在前。</Endpoint>
        <Endpoint path="/api/v1/dailies/latest">最新一期日报，含 AI 主线综述与分类简述。</Endpoint>
        <Endpoint path="/api/v1/dailies/{YYYY-MM-DD}">指定日期的日报（上海时区日历日）。</Endpoint>
        <Endpoint path="/api/v1/topics">
          两组主题档案（公司与模型 / 技术方向）、周环比计数，以及本周雷达。
        </Endpoint>
        <Endpoint path="/api/v1/topics/{slug}">单个主题的档案：窗口内全部条目 + 近期焦点。</Endpoint>
      </div>

      <div>
        <p className="text-sm font-semibold text-ink">items 查询参数</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[30rem] text-left text-xs">
            <thead className="text-ink-dim">
              <tr className="border-b border-line">
                <th className="py-1.5 pr-3 font-medium">参数</th>
                <th className="py-1.5 pr-3 font-medium">默认</th>
                <th className="py-1.5 font-medium">取值</th>
              </tr>
            </thead>
            <tbody className="text-ink-mid">
              {ITEM_PARAMS.map(([name, fallback, values]) => (
                <tr key={name} className="border-b border-line/60">
                  <td className="readout py-1.5 pr-3 text-ink">{name}</td>
                  <td className="readout py-1.5 pr-3">{fallback}</td>
                  <td className="py-1.5 leading-5">{values}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <p className="text-sm font-semibold text-ink">条目里的关键字段</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[30rem] text-left text-xs">
            <thead className="text-ink-dim">
              <tr className="border-b border-line">
                <th className="py-1.5 pr-3 font-medium">字段</th>
                <th className="py-1.5 font-medium">说明</th>
              </tr>
            </thead>
            <tbody className="text-ink-mid">
              {KEY_FIELDS.map(([name, desc]) => (
                <tr key={name} className="border-b border-line/60">
                  <td className="readout py-1.5 pr-3 align-top whitespace-nowrap text-ink">
                    {name}
                  </td>
                  <td className="py-1.5 leading-5">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* timeBasis 单独拎出来讲：它是这套字段里最容易用错的一个——
            三态、且缺省值反直觉。混在字段表的一格里说不清楚。 */}
        <div className="mt-4 rounded-md border border-line bg-canvas p-4">
          <p className="text-[13px] font-semibold text-ink">
            <code className="readout text-signal">timeBasis</code> 决定你该怎么写时间
          </p>
          <p className="mt-1.5 text-xs leading-5 text-ink-dim">
            注意它标注的是<strong className="text-ink-mid">时间的性质</strong>，不是时间本身——
            <code className="readout">publishedAt</code> 每条都有值。
          </p>
          <dl className="mt-2.5 space-y-1.5 text-xs leading-5 text-ink-dim">
            <div className="flex gap-2">
              <dt className="readout w-[5.5rem] shrink-0 text-ink-mid">published</dt>
              <dd>已确认是原文发布时间，可以说「发布于」。</dd>
            </div>
            <div className="flex gap-2">
              <dt className="readout w-[5.5rem] shrink-0 text-ink-mid">discovered</dt>
              <dd>已确认只有收录时间，必须说「收录于」，不得写成发布时间。</dd>
            </div>
            <div className="flex gap-2">
              <dt className="readout w-[5.5rem] shrink-0 text-ink-mid">null</dt>
              <dd>没有逐条标注。实践中基本都是原文发布时间，但我们不为单条打包票。</dd>
            </div>
          </dl>
          <p className="mt-3 text-xs leading-5 text-ink-dim">
            <strong className="text-ink-mid">现状与建议</strong>：这个标注目前只有个别信源会带，
            站内绝大多数条目是 <code className="readout">null</code>。抽样 200 条，98%
            的时间戳明显早于抓取时刻，确实是原文发布时间；少数没有发布时间概念的来源
            （如 GitHub Trending）会用收录时刻。所以对 null 的条目，直接报时间即可，
            不必逐条声明存疑，但也不要主动写成「发布于」——要严格区分请回原文核对。
          </p>
        </div>
      </div>

      <Code
        label="按 s-maxage 条件轮询"
        code={`# 首次请求，保存响应里的 ETag
curl -i '${siteUrl}/api/v1/items?window=24h&limit=20'

# 之后请求同一个完整 URL；304 表示内容没有变化
curl -i -H 'If-None-Match: <上次响应的 ETag>' \\
  '${siteUrl}/api/v1/items?window=24h&limit=20'`}
      />

      <div>
        <p className="text-sm font-semibold text-ink">错误是 Problem JSON</p>
        <p className="mt-1 text-xs leading-5 text-ink-dim">
          统一 RFC 9457 格式。按 <code className="readout">code</code> 分支，不要解析{" "}
          <code className="readout">detail</code> 文案。反馈时附上响应头里的{" "}
          <code className="readout">X-Request-Id</code> 即可定位。
        </p>
        <div className="mt-2 divide-y divide-line">
          {ERRORS.map(([status, code, desc]) => (
            <div key={status} className="flex gap-3 py-2">
              <span className="readout shrink-0 text-sm font-semibold text-signal">{status}</span>
              <div className="min-w-0">
                <code className="readout text-xs text-ink">{code}</code>
                <p className="mt-0.5 text-xs leading-5 text-ink-dim">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <Note title="先知道这几件事">
        <p>
          <strong className="text-ink">严格参数。</strong>未声明的参数、重复的参数、越界的值一律 400。
          请移除 <code className="readout">_</code> 这类 cache-buster 与未知参数——拼错的参数名（
          <code className="readout">?limits=10</code>）会因此在第一次调用就暴露，而不是被当成没传。
        </p>
        <p>
          <strong className="text-ink">正文不在 API 里。</strong>
          返回摘要、推荐理由、站内阅读页与原文链接。要正文请打开链接。
        </p>
        <p>
          <strong className="text-ink">没有推送通道。</strong>
          不提供 SSE、Webhook 或流式订阅，这是刻意的：响应走共享缓存，它的 TTL
          已经决定了任何客户端能有多新，按 s-maxage 条件轮询拿到的新鲜度是一样的，还不用维持长连接。
        </p>
      </Note>
    </>
  );
}

export default function AgentPage() {
  return (
    <StaticPage
      activeNavId="agent"
      title="Agent 接入"
      subtitle="四条路径都是匿名只读、不需要 API Key"
    >
      <section className="rounded-md border border-signal/25 bg-gradient-to-br from-signal/10 via-panel to-panel p-6">
        <h2 className="text-xl font-semibold leading-relaxed text-ink">让 Agent 直接用 AI·RADAR</h2>
        <p className="mt-3 text-sm leading-6 text-ink-mid">
          全部公开数据都能匿名读取：不需要 API Key，不读取登录态，浏览器跨域、curl
          与默认 HTTP SDK 都是正式支持的路径。下面四条路互相独立，按你手上的工具挑一条走即可。
        </p>
        {/* 这一句刻意做成 Hero 文案的一部分，而不是像各 tab 里那样的资源卡片：
            llms.txt 是四条路的总览，不属于其中任何一条，切 tab 时它不该变。
            早先它用了和面板内资源卡片一样的样式又紧贴 tab 条，被读成面板的一部分，
            切了 tab 不动就显得像卡住了。 */}
        <p className="mt-4 flex items-start gap-2 text-sm leading-6 text-ink-mid">
          <FileText className="mt-1 h-4 w-4 shrink-0 text-ink-dim" aria-hidden />
          <span>
            不想自己读？把{" "}
            <a
              href="/llms.txt"
              className="readout text-signal underline decoration-signal/40 underline-offset-4 hover:text-signal-bright"
            >
              llms.txt
            </a>{" "}
            交给你的 Agent——那一个地址就讲清了四条路各自怎么用、边界在哪，它不必翻这个页面。
          </span>
        </p>
      </section>

      <AccessTabs
        tabs={[
          { id: "skill", name: "Agent Skill", hint: "装一次，用中文问", panel: <SkillPanel /> },
          { id: "mcp", name: "MCP", hint: "一个地址，六个工具", panel: <McpPanel /> },
          { id: "rss", name: "RSS", hint: "复制即订阅", panel: <RssPanel /> },
          { id: "rest", name: "REST API", hint: "匿名 GET", panel: <RestPanel /> },
        ]}
      />

      <section className="rounded-md border border-signal/30 bg-signal/5 p-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-signal-bright">做得到，和暂时做不到的</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>
            <strong className="text-ink">原生时间窗只有过去 24 小时和最近 7 天。</strong>
            超过 7 天的历史检索暂不支持——查不到不代表没发生过。
          </li>
          <li>
            <strong className="text-ink">周报与月报目前只有网页</strong>，没有 Skill／MCP／API／RSS 合同。
            「最近 7 天精选」不等于编辑成品周报，别拿前者冒充后者。
          </li>
          <li>
            <strong className="text-ink">重要事实回原文核对。</strong>
            标题、摘要与翻译由 AI 基于第三方报道生成，只能当线索。引用数字、政策条款或当事人原话前，
            请打开返回的原文 URL 复核。
          </li>
          <li>
            <strong className="text-ink">用途不同，许可不同。</strong>
            个人非商业、公益非商业与组织内部使用免费；任何面向外部的商业产品、收费服务、客户交付、
            代理接口、数据转售、公开镜像或批量再分发，须先取得书面授权。匿名可访问不等于授权。
          </li>
          <li>
            <strong className="text-ink">稳定契约，不承诺 SLA。</strong>
            v1 不删除、不改名、不改变既有字段的类型；新增字段是安全的。关键链路仍请自行设置缓存、重试与降级。
          </li>
        </ul>
        <p className="mt-4">
          接入失败、MCP 工具不可见、Skill 漏触发，或需要新端点？走{" "}
          <a className="text-signal underline hover:text-signal-bright" href="/feedback">
            反馈页
          </a>
          。
        </p>
      </section>
    </StaticPage>
  );
}
