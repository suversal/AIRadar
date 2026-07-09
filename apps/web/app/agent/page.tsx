import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "Agent 接入 · AI·RADAR",
};

const endpoints = [
  {
    method: "GET",
    path: "/api/public/latest",
    description: "最新一期精选日报（12 条精选事件，含摘要、评分、原文与译文）",
  },
  {
    method: "GET",
    path: "/api/public/daily/{YYYY-MM-DD}",
    description: "指定日期的完整日报",
  },
  {
    method: "GET",
    path: "/api/public/events?days=30&category=model&topic=openai&q=agent&limit=50&offset=0",
    description: "全量事件流：日期区间、6 类展示分类、主题、关键词筛选与分页",
  },
  {
    method: "GET",
    path: "/api/public/events/{event_id}",
    description: "单个事件详情，含完整原文段落与中文翻译",
  },
  {
    method: "GET",
    path: "/api/public/reports/weekly/{YYYY-MM-DD}",
    description: "以指定日期为终点的近 7 天周报聚合",
  },
  {
    method: "GET",
    path: "/api/public/reports/monthly/{YYYY-MM}",
    description: "指定自然月的月报聚合",
  },
  {
    method: "GET",
    path: "/api/public/topics",
    description: "三组主题（公司与模型 / 技术方向 / 内容形态）及近 30 天文章计数",
  },
];

export default function AgentPage() {
  return (
    <StaticPage
      activeNavId="agent"
      title="Agent 接入"
      subtitle="所有公开数据都可通过 HTTP API 读取，直接供你的 Agent 或应用消费"
    >
      <section className="rounded-md border border-line bg-panel p-6">
        <h2 className="text-lg font-semibold text-ink">公开端点</h2>
        <div className="mt-4 divide-y divide-line">
          {endpoints.map((endpoint) => (
            <div key={endpoint.path} className="py-4">
              <div className="flex flex-wrap items-center gap-3">
                <span className="readout rounded border border-signal/40 px-2 py-0.5 text-xs font-semibold text-signal">
                  {endpoint.method}
                </span>
                <code className="readout break-all text-sm text-ink">{endpoint.path}</code>
              </div>
              <p className="mt-2 text-sm text-ink-mid">{endpoint.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-6">
        <h2 className="text-lg font-semibold text-ink">快速开始</h2>
        <p className="mt-3 text-sm leading-6 text-ink-mid">
          所有端点返回 JSON，无需鉴权。以本地部署为例：
        </p>
        <pre className="readout mt-4 overflow-x-auto rounded-md border border-line bg-canvas p-4 text-sm leading-6 text-ink">
{`# 今日精选
curl http://127.0.0.1:8000/api/public/latest

# 近 7 天 Anthropic 相关事件
curl "http://127.0.0.1:8000/api/public/events?days=7&topic=anthropic"

# 主题清单与计数
curl http://127.0.0.1:8000/api/public/topics`}
        </pre>
        <p className="mt-4 text-[15px] leading-7 text-ink-mid">
          事件对象的关键字段：<code className="readout text-xs">title</code>（中文标题）、
          <code className="readout text-xs">final_score</code>（0-100 综合评分）、
          <code className="readout text-xs">category</code>（6 类展示分类）、
          <code className="readout text-xs">reason</code>（推荐理由）、
          <code className="readout text-xs">original_url</code>（原文链接）。
          MCP Server 与 RSS 输出在后续版本提供。
        </p>
      </section>
    </StaticPage>
  );
}
