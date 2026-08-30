import {
  ArrowRight,
  BookOpen,
  Braces,
  CheckCircle2,
  Clock3,
  Code2,
  FileCheck2,
  FileText,
  Flame,
  GitBranch,
  Newspaper,
  Radar,
  ShieldCheck,
} from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { StaticPage } from "@/components/static-page";
import { siteUrl } from "@/lib/site";
import { DISPLAY_CATEGORIES } from "@/lib/taxonomy";

import { AccessTabs } from "./access-tabs";
import { Code, Note, PanelHead, ResourceLink } from "./agent-ui";

export const metadata = {
  title: "Agent 接入",
  description:
    "把 AI·RADAR 接入 Claude Code、远程 MCP 客户端、RSS 自动化或自建应用。匿名只读，不需要 API Key。",
  alternates: { canonical: "/agent" },
};

const skillVersion = "1.1.0";
const sourceBase = "https://github.com/suversal/AIRadar/tree/main/apps/web/public/ai-radar-skill";

const OUTCOMES = [
  { icon: Clock3, title: "24 小时重点", example: "过去 24 小时最重要的 5 件事是什么？" },
  { icon: Flame, title: "当前热点", example: "现在 AI 圈哪些话题正在升温？" },
  { icon: Radar, title: "事件脉络", example: "这件事有哪些信源，时间线是什么？" },
  { icon: Newspaper, title: "日报与主题", example: "总结今天的主线，Claude 本周有什么变化？" },
];

const TOOLS = [
  ["radar_get_latest", "过去 24 小时或最近 7 天的精选／全部收录"],
  ["radar_search", "在最近 7 天里搜模型、公司、产品或人物"],
  ["radar_get_hot_topics", "当前热点榜，按多信源热度排序"],
  ["radar_get_story", "一个事件的详情与多信源报道时间线"],
  ["radar_get_daily", "最新或指定日期的 AI 日报"],
  ["radar_get_topics", "主题档案与本周雷达：什么正在变热"],
];

const FEEDS = [
  { name: "精选", recommended: true, path: "/feed.xml", desc: "最新 50 条精选，含中文摘要与推荐理由。第一次接入建议选它。" },
  { name: "全部动态", path: "/feed/all.xml", desc: "最近 7 天全部收录，按发布时间倒序，未经精选阈值过滤。" },
  { name: "日报", path: "/feed/daily.xml", desc: "每天一期的精编日报，含 AI 主线综述，保留最近 10 期。" },
];

// 直接引用 taxonomy 的权威定义，不要在这里手抄一份中文标签。
// 手抄过一版「产业/研究/教程」，而 feed 频道标题与站内筛选用的是
// 「行业/论文/技巧」——读者在这页订阅"研究"，阅读器里收到的却叫"论文"。
const CATEGORY_FEEDS = DISPLAY_CATEGORIES.map(([slug, label]) => [label, slug] as const);

function SkillPanel() {
  return (
    <>
      <PanelHead
        title="把安装提示词发给 Claude Code"
        lead="这是当前唯一完成端到端验证的 Agent Skill 路径。其它支持本机 Agent Skills 的工具也可以尝试，但目录约定以客户端文档为准。"
      />

      <div className="flex flex-wrap gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-700/30 bg-emerald-700/[0.06] px-2.5 py-1 text-emerald-800 dark:border-emerald-400/30 dark:bg-emerald-400/[0.08] dark:text-emerald-300">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
          Claude Code 已验证
        </span>
        <span className="rounded-full border border-line bg-canvas px-2.5 py-1 text-ink-mid">Skill v{skillVersion}</span>
        <span className="rounded-full border border-line bg-canvas px-2.5 py-1 text-ink-mid">安装前可审阅</span>
      </div>

      <div className="grid gap-2.5 sm:grid-cols-3">
        {[
          ["01", "发送安装提示词", "Agent 会先读取 Skill 和安装器，再执行安装。"],
          ["02", "开启新会话", "多数 Agent 只会在会话开始时扫描 Skills。"],
          ["03", "问一句验证", "看到时间窗、中文摘要和站内链接即为成功。"],
        ].map(([step, title, desc]) => (
          <div key={step} className="rounded-md border border-line bg-canvas p-3.5">
            <div className="readout text-[11px] text-signal">{step}</div>
            <div className="mt-1 text-sm font-semibold text-ink">{title}</div>
            <div className="mt-1 text-[13px] leading-5 text-ink-dim">{desc}</div>
          </div>
        ))}
      </div>

      <Code
        label="安装提示词"
        code={`请安装 AI·RADAR Skill：${siteUrl}/ai-radar-skill/SKILL.md
安装器在 ${siteUrl}/ai-radar-skill/install.sh
请先读一遍并说明它会修改哪些目录，再执行。装完告诉我是否需要开启新会话`}
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <ResourceLink href="/ai-radar-skill/SKILL.md" icon={BookOpen} title={<>审阅 <code className="readout text-signal">SKILL.md</code></>} desc="查看会调用哪些端点、措辞规则与能力边界" />
        <ResourceLink href="/ai-radar-skill/install.sh" icon={FileCheck2} title={<>审阅 <code className="readout text-signal">install.sh</code></>} desc="安装器不猜平台、不覆盖其它 Skill，并保留旧版备份" />
        <ResourceLink href="/ai-radar-skill/SHA256SUMS" icon={ShieldCheck} title="SHA-256 校验值" desc="核对当前版本的 SKILL.md、VERSION 与安装器" />
        <ResourceLink href={sourceBase} icon={GitBranch} title="GitHub 源码" desc="查看公开仓库中的 Skill、版本和安装器历史" external />
      </div>

      <details className="group rounded-md border border-line bg-canvas">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-ink marker:hidden">
          <span className="flex items-center justify-between gap-3">
            手动安装与审阅命令
            <span className="text-xs font-normal text-ink-dim group-open:hidden">展开</span>
            <span className="hidden text-xs font-normal text-ink-dim group-open:inline">收起</span>
          </span>
        </summary>
        <div className="space-y-4 border-t border-line p-4">
          <Code label="1. 先审阅安装器" code={`curl -fsSL ${siteUrl}/ai-radar-skill/install.sh | less`} />
          <Code label="2. Claude Code：确认后安装" code={`bash <(curl -fsSL ${siteUrl}/ai-radar-skill/install.sh) --target claude`} />
          <Code label="其它读取 ~/.agents/skills 的工具" code={`bash <(curl -fsSL ${siteUrl}/ai-radar-skill/install.sh) --target agents`} />
          <p className="text-[13px] leading-5 text-ink-dim">
            <code className="readout">--target agents</code> 安装到 <code className="readout">~/.agents/skills/ai-radar</code>；
            <code className="readout">--target claude</code> 会额外创建指向同一目录的软链，不复制第二份正文。
          </p>
        </div>
      </details>

      <Code label="装好后这样验证" code="过去 24 小时 AI 圈最重要的 5 件事是什么？" />
      <p className="text-[13px] leading-5 text-ink-dim">
        成功时，回答会注明“过去 24 小时”，给出中文摘要；当天不足 5 条会如实说明，标题链接到本站阅读页。
      </p>

      <details className="rounded-md border border-signal/30 bg-signal/5 px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-signal-bright">没有触发？查看排查顺序</summary>
        <div className="mt-3 space-y-2 text-sm leading-6 text-ink-mid">
          <p>1. 确认文件名严格为 SKILL.md，并位于客户端支持的 Skills 目录。</p>
          <p>2. 关闭旧会话，新开一个会话后再次验证。</p>
          <p>3. 让 Agent 列出它发现的 Skills，确认其中包含 ai-radar。</p>
          <p>4. 仍然失败时，把平台、版本和安装路径提交到 <a className="text-signal underline" href="/feedback">反馈页</a>；不要附带 token 或本地文件内容。</p>
        </div>
      </details>
    </>
  );
}

function McpPanel() {
  return (
    <>
      <PanelHead title="添加一个远程 MCP 地址" lead="适合支持 Streamable HTTP 的 Agent 与开发工具。服务匿名只读，不需要 token，也不会读取登录态。" />
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-full border border-signal/35 bg-signal/10 px-2.5 py-1 text-signal">远程 MCP 推荐</span>
        <span className="rounded-full border border-line bg-canvas px-2.5 py-1 text-ink-mid">6 个只读工具</span>
        <span className="rounded-full border border-line bg-canvas px-2.5 py-1 text-ink-mid">无需 token</span>
      </div>
      <Code label="MCP 端点" code={`${siteUrl}/api/mcp`} />
      <Code label="通用 MCP 配置" code={`{
  "mcpServers": {
    "ai-radar": {
      "type": "http",
      "url": "${siteUrl}/api/mcp"
    }
  }
}`} />
      <Code label="Claude Code" code={`claude mcp add --transport http ai-radar '${siteUrl}/api/mcp'`} />
      <p className="text-[13px] leading-5 text-ink-dim">不同客户端的配置入口名称可能不同，核心只有 server 名称和 URL。客户端若不支持远程 HTTP，需要使用它自己的远程 MCP 代理。</p>
      <div>
        <h3 className="text-sm font-semibold text-ink">连接后会看到六个工具</h3>
        <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
          {TOOLS.map(([name, desc]) => (
            <div key={name} className="rounded-md border border-line bg-canvas px-3 py-2.5">
              <code className="readout text-xs text-signal">{name}</code>
              <p className="mt-1 text-[13px] leading-5 text-ink-dim">{desc}</p>
            </div>
          ))}
        </div>
      </div>
      <Code label="验证一次真实调用" code="请调用 radar_get_latest，告诉我过去 24 小时最重要的 5 条 AI 资讯，并附上链接。" />
      <Note title="连接与查询边界">
        <p>普通查询最多 30 条，热点榜最多 10 条；越界输入会返回明确错误，不会自动放宽。</p>
        <p><code className="readout">radar_get_story</code> 的事件 ID 必须来自其它工具返回。</p>
        <p>连接失败时检查 URL、远程 Streamable HTTP 支持和工具列表；对 /api/mcp 直接发 GET 返回 405 是正常行为。</p>
      </Note>
    </>
  );
}

function FeedRow({ name, path, desc, recommended = false }: { name: string; path: string; desc: string; recommended?: boolean }) {
  return (
    <div className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-ink">{name}</span>
        {recommended ? <span className="rounded border border-signal/40 px-1.5 py-0.5 text-[11px] text-signal">推荐</span> : null}
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <code className="readout min-w-0 break-all text-[13px] text-ink-mid">{siteUrl}{path}</code>
        <CopyButton text={`${siteUrl}${path}`} />
      </div>
      <p className="mt-1.5 text-[13px] leading-5 text-ink-dim">{desc}</p>
    </div>
  );
}

function RssPanel() {
  return (
    <>
      <PanelHead title="复制地址即可订阅" lead="兼容主流 RSS 2.0 阅读器，以及 n8n、Zapier 等自动化工具。第一次接入建议选择“精选”。" />
      <div className="divide-y divide-line">
        {FEEDS.map((feed) => <FeedRow key={feed.path} {...feed} />)}
      </div>
      <details className="rounded-md border border-line bg-canvas">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-ink">按分类订阅（5 个可复制地址）</summary>
        <div className="grid gap-2 border-t border-line p-4 sm:grid-cols-2">
          {CATEGORY_FEEDS.map(([label, slug]) => {
            const path = `/feed/category/${slug}.xml`;
            return (
              <div key={slug} className="flex min-w-0 items-center justify-between gap-2 rounded-md border border-line px-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-ink">{label}</div>
                  <code className="readout block truncate text-xs text-ink-dim">{path}</code>
                </div>
                <CopyButton text={`${siteUrl}${path}`} />
              </div>
            );
          })}
        </div>
      </details>
      <Note title="给阅读器与自动化工具的合同">
        <p>支持 ETag 条件请求，未变化返回 304；建议每 30 分钟或更慢轮询。</p>
        <p>条目 link 指向站内阅读页，第三方原文放在 description；guid 使用事件 ID，站内地址改版不会重推旧条目。</p>
        <p><strong className="text-ink">Feed 只输出摘要，不内联第三方正文。</strong></p>
      </Note>
    </>
  );
}

function RestPanel() {
  return (
    <>
      <PanelHead title="用一个匿名 GET 开始" lead="适合脚本、服务端程序和自建应用。支持 CORS、ETag 条件请求；完整字段与错误码以 OpenAPI 为准。" />
      <div className="grid gap-3 sm:grid-cols-2">
        <ResourceLink href="/agent/api" icon={Code2} title="人类可读 API 参考" desc="端点、参数、字段、缓存和错误恢复" />
        <ResourceLink href="/openapi-v1.json" icon={Braces} title={<>OpenAPI 3.1：<code className="readout text-signal">openapi-v1.json</code></>} desc="机器可读的权威契约" />
      </div>
      <Code label="第一个请求" code={`curl '${siteUrl}/api/v1/items?window=24h&limit=10'`} />
      <div className="rounded-md border border-line bg-canvas p-4">
        <h3 className="text-sm font-semibold text-ink">成功响应会包含</h3>
        <div className="mt-3 grid gap-2 text-[13px] text-ink-mid sm:grid-cols-2">
          {[
            ["page", "分页、总数与是否还有下一页"],
            ["items[].title", "AI 生成的中文标题"],
            ["items[].summary", "中文摘要与推荐理由"],
            ["items[].links", "站内阅读页与第三方原文"],
          ].map(([field, desc]) => (
            <div key={field} className="rounded border border-line px-3 py-2">
              <code className="readout text-signal">{field}</code>
              <p className="mt-1 text-ink-dim">{desc}</p>
            </div>
          ))}
        </div>
      </div>
      <a href="/agent/api" className="inline-flex min-h-11 items-center gap-2 self-start rounded-md border border-signal/40 bg-signal/10 px-4 text-sm font-semibold text-signal transition-colors hover:border-signal/60 hover:text-signal-bright">
        查看完整 REST API 参考
        <ArrowRight className="h-4 w-4" aria-hidden />
      </a>
    </>
  );
}

export default function AgentPage() {
  return (
    <StaticPage compact activeNavId="agent" title="把 AI·RADAR 接入你的 Agent" subtitle="无需 API Key，匿名只读；选择你正在使用的工具，约 3 分钟完成接入">
      <section>
        <div className="flex flex-wrap gap-2 text-xs">
          {["匿名只读", "无需 API Key", "REST v1 稳定契约", "重要事实可回原文核验"].map((item) => (
            <span key={item} className="rounded-full border border-line-strong/70 bg-canvas/70 px-2.5 py-1 text-ink-mid">{item}</span>
          ))}
        </div>
        <h2 className="editorial-rule-title mt-4 text-2xl font-medium leading-relaxed text-ink">接入后，Agent 可以直接回答</h2>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {OUTCOMES.map(({ icon: Icon, title, example }) => (
            <div key={title} className="rounded-md border border-line bg-canvas/75 p-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink"><Icon className="h-4 w-4 text-signal" aria-hidden />{title}</div>
              <p className="mt-1.5 text-[13px] leading-5 text-ink-dim">“{example}”</p>
            </div>
          ))}
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-ink"><FileText className="h-4 w-4 text-signal" aria-hidden />让 Agent 自己选择接入路径</div>
            <p className="mt-1 text-[13px] leading-5 text-ink-dim">把下面地址发给 Agent；它会读到四条路径、能力边界和使用许可。</p>
          </div>
          <a href="/llms.txt" className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-signal/40 bg-signal/10 px-3 text-sm font-semibold text-signal hover:border-signal/60 hover:text-signal-bright">
            查看 llms.txt<ArrowRight className="h-4 w-4" aria-hidden />
          </a>
        </div>
        <div className="mt-3 rounded-md border border-line bg-canvas">
          <div className="flex items-center justify-between gap-3 px-3 py-2">
            <code className="readout min-w-0 break-all text-[13px] text-ink">{siteUrl}/llms.txt</code>
            <CopyButton text={`${siteUrl}/llms.txt`} label="复制地址" />
          </div>
        </div>
      </section>

      <section id="paths" className="scroll-mt-4">
        <div className="mb-3">
          <h2 className="text-lg font-semibold text-ink">你正在使用什么工具？</h2>
          <p className="mt-1 text-sm leading-6 text-ink-mid">选择最接近的一项；每条路径互相独立，不需要全部配置。</p>
        </div>
        <AccessTabs tabs={[
          { id: "skill", name: "Claude Code", method: "Agent Skill", hint: "已完成端到端验证", badge: "已验证", panel: <SkillPanel /> },
          { id: "mcp", name: "MCP 客户端", method: "远程 MCP", hint: "一个地址，六个工具", badge: "推荐", panel: <McpPanel /> },
          { id: "rss", name: "RSS / 自动化", method: "RSS 2.0", hint: "阅读器、n8n、Zapier", panel: <RssPanel /> },
          { id: "rest", name: "自建应用", method: "REST API v1", hint: "脚本、服务端与 SDK", panel: <RestPanel /> },
        ]} />
      </section>

      <section className="bg-panel/45 px-5 py-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-signal-bright">共同能力边界</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li><strong className="text-ink">原生时间窗是过去 24 小时和最近 7 天。</strong>超过 7 天的历史检索暂不支持。</li>
          <li><strong className="text-ink">周报与月报目前仅提供网页。</strong>最近 7 天精选不等同于编辑完成的周报。</li>
          <li><strong className="text-ink">重要事实请回原文核验。</strong>标题、摘要与翻译由 AI 基于第三方报道生成，引用数字、政策或原话前应查看原文URL复核。</li>
          <li><strong className="text-ink">v1 保持向后兼容，但不承诺 SLA。</strong>关键链路请自行配置缓存、重试和降级。</li>
        </ul>
        <div className="mt-5 rounded-md border border-line bg-canvas p-4">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-signal" aria-hidden />
            <div>
              <h3 className="font-semibold text-ink">匿名访问不等于商业授权</h3>
              <p className="mt-1 text-sm leading-6 text-ink-mid">个人非商业、公益非商业和组织内部使用免费；面向外部的商业产品、收费服务、客户交付、代理接口、数据转售、公开镜像或批量再分发，需要先取得书面授权。</p>
            </div>
          </div>
        </div>
        <p className="mt-4">
          Skill 漏触发，或需要新端点？欢迎向我{" "}
          <a className="text-signal underline underline-offset-4 hover:text-signal-bright" href="/feedback">
            反馈
          </a>
          。
        </p>
      </section>
    </StaticPage>
  );
}
