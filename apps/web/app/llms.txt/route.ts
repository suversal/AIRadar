import { siteUrl } from "@/lib/site";
import { CACHE, conditionalText } from "@/lib/v1/http";

/**
 * llms.txt —— 给 LLM 与 Agent 的站点导航（llmstxt.org 约定）。
 *
 * 存在的意义是"一个地址讲清全部接入方式"：Agent 抓到它就知道有 REST、
 * MCP、RSS 和 Skill 四条路，以及各自的边界，不用去猜端点或爬 HTML。
 */
function render(): string {
  const u = (path: string) => new URL(path, siteUrl).toString();
  return `# AI·RADAR

> 为创作者和开发者准备的中文 AI 情报雷达。持续监听数十个高信噪比 AI 信源，用 AI 评分、聚类、去重，每天沉淀一期精编日报。全部公开数据都可匿名只读访问，不需要 API Key。

四条接入路径，按接入成本从低到高：

## Agent Skill

装一次，之后直接用中文提问，不用记端点。适合 Claude Code、Codex、Gemini CLI 等支持 Agent Skills 的工具。

- [SKILL.md](${u("/ai-radar-skill/SKILL.md")}): Skill 正文，含端点、参数与措辞规范
- [install.sh](${u("/ai-radar-skill/install.sh")}): 安装器。用法 \`bash <(curl -fsSL ${u("/ai-radar-skill/install.sh")}) --target claude\`
- [VERSION](${u("/ai-radar-skill/VERSION")}): 当前版本号

## MCP Server

支持远程 MCP 的客户端加一个地址即可，标准 Streamable HTTP，匿名只读，无需 token。

- [MCP 端点](${u("/api/mcp")}): POST JSON-RPC。八个工具：radar_get_latest、radar_search、radar_get_hot_topics、radar_get_story、radar_get_daily、radar_get_weekly、radar_get_monthly、radar_get_topics
- Claude Code 接入：\`claude mcp add --transport http ai-radar '${u("/api/mcp")}'\`

## REST API v1

匿名 GET，支持 CORS 与 ETag 条件请求，错误为 RFC 9457 Problem JSON。

- [OpenAPI 3.1](${u("/openapi-v1.json")}): 字段、参数与错误码以此为准
- [REST API 人类可读参考](${u("/agent/api")}): 端点、参数、字段、缓存与错误恢复
- [/api/v1/items](${u("/api/v1/items")}): 精选或全部收录；支持 24h/7d 窗口、分类与关键词
- [/api/v1/hot-topics](${u("/api/v1/hot-topics")}): 当前热点榜，按多信源热度排序
- [/api/v1/stories/{id}](${u("/openapi-v1.json")}): 单个事件的详情与报道时间线。id 来自 items[].id，不要自行构造——链接指向它在 OpenAPI 里的定义
- [/api/v1/dailies/latest](${u("/api/v1/dailies/latest")}): 最新一期日报
- [/api/v1/dailies](${u("/api/v1/dailies")}): 日报期次索引
- [/api/v1/weeklies/latest](${u("/api/v1/weeklies/latest")}): 最新可用周报；finalizedAt 标注是否已封版
- [/api/v1/weeklies](${u("/api/v1/weeklies")}): 周报期次索引
- [/api/v1/monthlies/latest](${u("/api/v1/monthlies/latest")}): 最新可用月报；finalizedAt 标注是否已封版
- [/api/v1/monthlies](${u("/api/v1/monthlies")}): 月报期次索引
- [/api/v1/topics](${u("/api/v1/topics")}): 主题档案与本周雷达

## RSS

兼容主流 RSS 2.0 阅读器与 n8n、Zapier 这类自动化工具。

- [精选](${u("/feed.xml")}): 最新 50 条精选，第一次接入选这个
- [全部动态](${u("/feed/all.xml")}): 最近 7 天全部收录，量大且未过滤
- [日报](${u("/feed/daily.xml")}): 每天一期的精编日报，保留最近 10 期
- [周报](${u("/feed/weekly.xml")}): 只发布已封版周报
- [月报](${u("/feed/monthly.xml")}): 只发布已封版月报
- 分类订阅：\`/feed/category/{model|product|industry|research|tutorial}.xml\`

## 能力边界

- 原生时间窗只有过去 24 小时和最近 7 天。超过 7 天的历史检索不支持，查不到不代表没发生过。
- 不提供第三方原文正文。返回摘要、推荐理由与链接；正文请打开原文或站内阅读页。
- 周报与月报可通过 REST、MCP 与 RSS 读取。RSS 只发布已封版期次；REST/MCP 的 latest 可能仍在更新，请检查 finalizedAt。
- 面向读者提供已封版周报的双重确认邮件订阅；面向机器仍不提供 SSE、Webhook 或流式订阅，REST/RSS 请按 s-maxage 条件轮询。
- 标题与摘要由 AI 基于第三方报道生成，只能当线索。引用数字、政策或原话前请回原文核对。

## 频率与授权

- 用带 If-None-Match 的条件请求轮询，间隔取响应里的 s-maxage（items 60 秒、hot-topics 300 秒）；RSS 建议 30 分钟或更慢。
- 个人非商业、公益非商业、组织内部使用免费。面向外部的商业产品、收费服务、客户交付、代理接口、数据转售、公开镜像或批量再分发，须先取得书面授权——匿名可访问不等于授权。
- 接入问题、需要新端点或申请授权：[反馈页](${u("/feedback")})
`;
}

export async function GET(request: Request) {
  return conditionalText(request, render(), "text/plain; charset=utf-8", CACHE.feed);
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
