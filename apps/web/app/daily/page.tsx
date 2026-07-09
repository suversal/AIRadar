import { getDailyReport, getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { CopyMarkdownButton } from "./copy-markdown-button";
import { buildDailyMarkdown } from "@/lib/markdown";
import { buildDailyDigest, latestToDailyReport } from "../reports/report-data";
import { ReportShell, reportModeTabs } from "../reports/report-shell";

async function loadReport() {
  const latest = await getLatestReport();
  if (!latest.report_date) {
    return latestToDailyReport(latest);
  }
  try {
    return await getDailyReport(latest.report_date);
  } catch {
    return latestToDailyReport(latest);
  }
}

function formatChineseDate(reportDate: string) {
  const parsed = new Date(`${reportDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return reportDate;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(parsed);
}

export default async function DailyPage() {
  const report = await loadReport();
  const digest = buildDailyDigest(report);
  const markdown = buildDailyMarkdown(report);

  return (
    <ReportShell
      activeMode="daily"
      secondary={
        <div className="mt-6">
          <div className="text-sm font-semibold text-ink-mid">2026 年 7 月</div>
          <a
            className="mt-3 grid grid-cols-[36px_1fr] gap-3 rounded-md bg-signal/10 px-3 py-3 text-sm text-signal-bright"
            href="/daily"
          >
            <span>{report.report_date.slice(-2)} 日</span>
            <span className="line-clamp-2">{report.items[0]?.title ?? "最新 AI 日报"}</span>
          </a>
          <div className="mt-5 border-t border-line pt-4 text-sm text-ink-dim">
            <a className="hover:text-ink" href="/daily">
              全部日报
            </a>
          </div>
        </div>
      }
    >
      <div className="mx-auto max-w-4xl">
        <header className="py-8">
          <div className="flex items-center gap-4 text-xs font-semibold uppercase tracking-[0.35em] text-ink-dim">
            <span className="h-px w-12 bg-signal" />
            <span>{digest.issueMeta}</span>
          </div>
          <h1
            aria-label="AI·RADAR 日报"
            className="mt-8 text-6xl font-semibold leading-none tracking-normal text-ink md:text-8xl"
          >
            <span className="text-ink">AI</span>
            <span className="text-signal">·RADAR</span> 日报
          </h1>
          <div className="mt-8 grid items-center gap-4 text-sm text-ink-mid md:grid-cols-[auto_1fr_auto]">
            <span>{formatChineseDate(report.report_date)}</span>
            <span className="hidden h-px bg-panel-soft md:block" />
            <span>DAILY · 每日八时</span>
          </div>
        </header>

        <section className="rounded-md border border-line bg-panel p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">今日看点</h2>
            <div className="text-sm text-ink-dim">{report.article_count} 篇报道</div>
          </div>
          <div className="mt-4 divide-y divide-line">
            {digest.highlights.map((highlight, index) => (
              <a
                key={highlight.label}
                className="grid gap-2 py-3 text-sm md:grid-cols-[36px_1fr_40px]"
                href={eventHref(highlight.items[0])}
              >
                <span className="font-semibold text-signal">{String(index + 1).padStart(2, "0")}</span>
                <span>
                  <span className="block font-semibold text-ink">{highlight.label}</span>
                  <span className="mt-1 block text-ink-mid">{highlight.title}</span>
                </span>
                <span className="text-ink-dim md:text-right">{highlight.count}</span>
              </a>
            ))}
          </div>
        </section>

        <div className="mt-6 grid gap-3 md:grid-cols-4">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="rounded-md border border-line bg-panel p-4 text-center">
              <div className="text-2xl font-semibold text-ink">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>

        <div className="mt-6 flex flex-wrap gap-3">
          <CopyMarkdownButton markdown={markdown} />
          {reportModeTabs.map((tab) => (
            <a
              key={tab.id}
              className={`rounded-md border px-4 py-2 text-sm font-semibold ${
                tab.id === "daily"
                  ? "border-signal/50 text-signal-bright"
                  : "border-line text-ink-mid hover:text-ink"
              }`}
              href={tab.href}
            >
              {tab.label}
            </a>
          ))}
        </div>

        <div className="mt-14 space-y-12">
          {digest.sections.map((section, sectionIndex) => (
            <section key={section.key}>
              <div className="flex items-end justify-between gap-4">
                <h2 className="text-3xl font-semibold text-ink">
                  <span className="mr-4 text-5xl text-signal">
                    {String(sectionIndex + 1).padStart(2, "0")}
                  </span>
                  {section.label}
                </h2>
                <span className="text-sm font-semibold text-signal">{section.items.length} 篇</span>
              </div>

              <div className="mt-6 grid gap-5">
                {section.items.map((item) => (
                  <article key={item.event_id} className="rounded-md border border-line bg-panel p-5">
                    <div className="text-sm text-signal-bright">
                      {item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源
                    </div>
                    <h3 className="mt-3 text-xl font-semibold leading-8 text-ink">
                      <a href={eventHref(item)}>{item.title}</a>
                    </h3>
                    <p className="mt-4 text-sm leading-7 text-ink-mid">
                      {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                    </p>
                    <p className="mt-4 rounded-md bg-signal/10 px-4 py-3 text-sm leading-6 text-signal-bright">
                      <span className="font-semibold">为什么重要：</span>
                      {item.reason ?? "暂无推荐理由。"}
                    </p>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </ReportShell>
  );
}
