import { Braces } from "lucide-react";

import { siteUrl } from "@/lib/site";

import { Code, Endpoint, Note, ResourceLink } from "./agent-ui";

const ITEM_PARAMS = [
  ["mode", "selected", "selected 精选（推荐）｜all 同窗口全部收录"],
  ["window", "7d", "24h ｜ 7d。只有这两个原生窗口"],
  ["limit", "50", "1–100"],
  ["offset", "0", "0–10000"],
  ["category", "—", "model / product / industry / research / tutorial"],
  ["focus", "—", "model / product / technology / industry / tutorial"],
  ["q", "—", "关键词，2–200 字"],
];

const KEY_FIELDS = [
  ["title", "中文标题，AI 基于第三方报道生成"],
  ["summary", "中文摘要。引用数字或原话前请回原文核对"],
  ["reason", "推荐理由：这条为什么值得看"],
  ["score", "0–100 综合评分"],
  ["selected", "是否入选精选。阈值按分类不同，不要从 score 反推"],
  ["sourceCount", "几家信源报道了这件事"],
  ["topics", "主题归属，可与 /api/v1/topics 的 id 对上"],
  ["publishedAt", "时间戳。它的性质由 timeBasis 决定，见下"],
  ["links.radar", "站内阅读页。引用时优先给用户这个"],
  ["links.original", "第三方原文地址"],
];

const ERRORS = [
  ["400", "invalid_parameter 等", "参数不合法、未声明或重复。按报错改正，接口不会自动放宽查询。"],
  ["404", "not_found", "事件 ID 或日期不存在。ID 只能来自其它端点的返回。"],
  ["500", "internal_error", "服务端自身异常；请附 X-Request-Id 反馈，不要按 503 反复重试。"],
  ["503", "upstream_unavailable", "数据源暂时不可用。退避后重试，不要并发重试。"],
];

export function ApiReference() {
  return (
    <div className="space-y-6">
      <section className="rounded-md border border-line bg-panel p-5 sm:p-6">
        <h2 className="text-xl font-semibold text-ink">快速开始</h2>
        <p className="mt-2 text-[15px] leading-6 text-ink-mid">
          全部接口都是匿名只读 GET，支持 CORS、ETag 条件请求，并使用 RFC 9457 Problem JSON 返回错误。
        </p>
        <div className="mt-4 space-y-4">
          <ResourceLink
            href="/openapi-v1.json"
            icon={Braces}
            title={
              <>
                OpenAPI 3.1：<code className="readout text-signal">openapi-v1.json</code>
              </>
            }
            desc="参数、响应结构和错误码的机器可读权威定义"
          />
          <Code label="第一个请求" code={`curl '${siteUrl}/api/v1/items?window=24h&limit=10'`} />
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-5 sm:p-6">
        <h2 className="text-lg font-semibold text-ink">端点</h2>
        <div className="mt-3 [&>*:last-child]:border-b-0">
          <Endpoint path="/api/v1/items">
            精选或最近 7 天全部收录；支持时间窗、分类、焦点与关键词筛选，按发布时间倒序。
          </Endpoint>
          <Endpoint path="/api/v1/hot-topics">
            当前热点榜。按多信源热度排序，与按时间排序的 items 是两个口径。
          </Endpoint>
          <Endpoint path="/api/v1/stories/{id}">
            单个事件的详情与多信源报道时间线。id 来自其它端点返回的 items[].id。
          </Endpoint>
          <Endpoint path="/api/v1/dailies">日报期次索引，最新的在前。</Endpoint>
          <Endpoint path="/api/v1/dailies/latest">最新一期日报，含 AI 主线综述与分类简述。</Endpoint>
          <Endpoint path="/api/v1/dailies/{YYYY-MM-DD}">指定日期的日报（上海时区日历日）。</Endpoint>
          <Endpoint path="/api/v1/topics">
            公司、模型与技术方向主题档案，包含周环比计数和本周雷达。
          </Endpoint>
          <Endpoint path="/api/v1/topics/{slug}">单个主题的窗口内条目与近期焦点。</Endpoint>
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-5 sm:p-6">
        <h2 className="text-lg font-semibold text-ink">items 查询参数</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[30rem] text-left text-[13px]">
            <thead className="text-ink-dim">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">参数</th>
                <th className="py-2 pr-3 font-medium">默认</th>
                <th className="py-2 font-medium">取值</th>
              </tr>
            </thead>
            <tbody className="text-ink-mid">
              {ITEM_PARAMS.map(([name, fallback, values]) => (
                <tr key={name} className="border-b border-line/60">
                  <td className="readout py-2 pr-3 text-ink">{name}</td>
                  <td className="readout py-2 pr-3">{fallback}</td>
                  <td className="py-2 leading-5">{values}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-5 sm:p-6">
        <h2 className="text-lg font-semibold text-ink">条目关键字段</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[30rem] text-left text-[13px]">
            <thead className="text-ink-dim">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">字段</th>
                <th className="py-2 font-medium">说明</th>
              </tr>
            </thead>
            <tbody className="text-ink-mid">
              {KEY_FIELDS.map(([name, desc]) => (
                <tr key={name} className="border-b border-line/60">
                  <td className="readout whitespace-nowrap py-2 pr-3 align-top text-ink">{name}</td>
                  <td className="py-2 leading-5">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-5 rounded-md border border-line bg-canvas p-4">
          <h3 className="text-sm font-semibold text-ink">
            <code className="readout text-signal">timeBasis</code> 决定该怎样描述时间
          </h3>
          <p className="mt-1.5 text-[13px] leading-5 text-ink-dim">
            它标注的是时间的性质，不是时间本身；每条记录都有 <code className="readout">publishedAt</code>。
          </p>
          <dl className="mt-3 space-y-2 text-[13px] leading-5 text-ink-dim">
            <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
              <dt className="readout text-ink-mid">published</dt>
              <dd>已确认是原文发布时间，可以说“发布于”。</dd>
            </div>
            <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
              <dt className="readout text-ink-mid">discovered</dt>
              <dd>只有收录时间，必须说“收录于”。</dd>
            </div>
            <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
              <dt className="readout text-ink-mid">null</dt>
              <dd>没有逐条标注；可以直接报时间，但不要主动把它称为“发布于”。</dd>
            </div>
          </dl>
          <p className="mt-3 text-[13px] leading-5 text-ink-dim">
            当前只有个别信源带该标注。抽样 200 条，98% 的时间戳明显早于抓取时刻；GitHub Trending
            等没有发布时间概念的来源可能使用收录时刻。严格场景请回原文核对。
          </p>
        </div>
      </section>

      <section className="rounded-md border border-line bg-panel p-5 sm:p-6">
        <h2 className="text-lg font-semibold text-ink">缓存与错误恢复</h2>
        <div className="mt-4 space-y-5">
          <Code
            label="按 ETag 条件轮询"
            code={`# 首次请求，保存响应里的 ETag
curl -i '${siteUrl}/api/v1/items?window=24h&limit=20'

# 后续请求同一个完整 URL；304 表示内容没有变化
curl -i -H 'If-None-Match: <上次响应的 ETag>' \\
  '${siteUrl}/api/v1/items?window=24h&limit=20'`}
          />

          <div>
            <h3 className="text-sm font-semibold text-ink">Problem JSON</h3>
            <p className="mt-1 text-[13px] leading-5 text-ink-dim">
              按 <code className="readout">code</code> 分支，不要解析 <code className="readout">detail</code>
              文案。反馈时附上响应头里的 <code className="readout">X-Request-Id</code>。
            </p>
            <div className="mt-2 divide-y divide-line">
              {ERRORS.map(([status, code, desc]) => (
                <div key={status} className="flex gap-3 py-2.5">
                  <span className="readout shrink-0 text-sm font-semibold text-signal">{status}</span>
                  <div className="min-w-0">
                    <code className="readout text-[13px] text-ink">{code}</code>
                    <p className="mt-0.5 text-[13px] leading-5 text-ink-dim">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <Note title="接入前需要知道">
            <p>
              <strong className="text-ink">严格参数。</strong>未知、重复和越界参数一律返回 400；不要添加
              <code className="readout"> _ </code>之类的 cache-buster。
            </p>
            <p>
              <strong className="text-ink">正文不在 API 里。</strong>接口返回摘要、推荐理由、站内阅读页和原文链接。
            </p>
            <p>
              <strong className="text-ink">没有推送通道。</strong>请按响应的缓存策略使用 ETag 条件轮询。
            </p>
          </Note>
        </div>
      </section>
    </div>
  );
}
