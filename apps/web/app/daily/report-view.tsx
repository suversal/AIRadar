import type { DailyReport, LatestEvent } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { buildDailyMarkdown, getDailySections } from "@/lib/markdown";
import { CopyMarkdownButton } from "./copy-markdown-button";

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return score.toFixed(1);
}

function shiftDate(reportDate: string, days: number) {
  const date = new Date(`${reportDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function renderSource(item: LatestEvent) {
  if (!item.main_source) {
    return <div>来源 {item.source_count ?? 1} 个</div>;
  }
  return (
    <a className="text-signal underline" href={item.main_source.url}>
      {item.main_source.name}
    </a>
  );
}

export function DailyReportView({ report }: { report: DailyReport }) {
  const sections = getDailySections(report);
  const markdown = buildDailyMarkdown(report);
  const previousDate = shiftDate(report.report_date, -1);
  const nextDate = shiftDate(report.report_date, 1);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-ink-mid">Suversal AI Radar</p>
            <h1 className="mt-2 text-3xl font-semibold">{report.title}</h1>
          </div>
          <a className="text-sm text-signal underline" href="/latest">
            最新情报
          </a>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-6 px-5 py-6 lg:grid-cols-[280px_1fr]">
        <aside className="border-b border-line pb-5 lg:border-b-0 lg:border-r lg:pr-5">
          <div className="grid grid-cols-3 gap-3 lg:grid-cols-1">
            <div>
              <div className="text-2xl font-semibold">{report.article_count}</div>
              <div className="text-sm text-ink-mid">精选事件</div>
            </div>
            <div>
              <div className="text-2xl font-semibold">{sections.length}</div>
              <div className="text-sm text-ink-mid">分类</div>
            </div>
            <div>
              <div className="text-2xl font-semibold">
                {new Set(report.items.flatMap((item) => item.tags ?? [])).size}
              </div>
              <div className="text-sm text-ink-mid">标签信号</div>
            </div>
          </div>

          <div className="mt-6">
            <CopyMarkdownButton markdown={markdown} />
          </div>

          <nav className="mt-6 space-y-2 text-sm" aria-label="按日期归档">
            <div className="font-semibold">按日期归档</div>
            <div className="flex flex-wrap gap-2">
              {previousDate ? (
                <a className="rounded-md border border-line px-3 py-2" href={`/daily/${previousDate}`}>
                  前一天
                </a>
              ) : null}
              <a className="rounded-md border border-signal px-3 py-2 text-signal" href="/daily">
                最新日报
              </a>
              {nextDate ? (
                <a className="rounded-md border border-line px-3 py-2" href={`/daily/${nextDate}`}>
                  后一天
                </a>
              ) : null}
            </div>
          </nav>
        </aside>

        <div className="space-y-8">
          <section className="border-b border-line pb-5">
            <div className="text-sm text-ink-mid">{report.report_date}</div>
            <p className="mt-3 max-w-3xl text-base leading-7 text-ink-mid">{report.summary}</p>
          </section>

          {sections.length > 0 ? (
            sections.map((section) => (
              <section key={section.key}>
                <h2 className="text-xl font-semibold">{section.label}</h2>
                <div className="mt-4 divide-y divide-line border-y border-line">
                  {section.items.map((item) => (
                    <article key={item.event_id} className="grid gap-3 py-5 md:grid-cols-[1fr_170px]">
                      <div>
                        <div className="text-sm text-signal-dim">
                          {section.label} · {formatScore(item.final_score)}
                        </div>
                        <h3 className="mt-2 text-xl font-semibold">
                          <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
                        </h3>
                        <p className="mt-3 text-sm leading-6 text-ink-mid">
                          {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                        </p>
                        <p className="mt-3 text-sm leading-6">
                          <span className="font-semibold">为什么重要：</span>
                          {item.reason ?? "暂无推荐理由。"}
                        </p>
                        <p className="mt-2 text-sm leading-6">
                          <span className="font-semibold">下一步：</span>
                          {item.action ?? "阅读原文并评估是否跟进。"}
                        </p>
                      </div>
                      <div className="text-sm text-ink-mid md:text-right">
                        <div>相关来源 {item.source_count ?? 1} 个</div>
                        <div className="mt-3">{renderSource(item)}</div>
                        <div className="mt-3">{(item.tags ?? []).join(" / ")}</div>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))
          ) : (
            <section className="border-y border-line py-8">
              <h2 className="text-xl font-semibold">暂无日报</h2>
              <p className="mt-3 text-sm text-ink-mid">这个日期还没有生成可展示的日报。</p>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}
