import { getDailyArchive, getDailyReport, getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { buildDailyDigest, latestToDailyReport } from "../reports/report-data";
import { ReportShell } from "../reports/report-shell";

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

function groupDatesByMonth(dates: string[]) {
  const groups = new Map<string, string[]>();
  for (const value of dates) {
    const month = value.slice(0, 7);
    groups.set(month, [...(groups.get(month) ?? []), value]);
  }
  return Array.from(groups.entries());
}

export default async function DailyPage() {
  const [report, archiveDates] = await Promise.all([loadReport(), getDailyArchive()]);
  const monthGroups = groupDatesByMonth(archiveDates);
  const digest = buildDailyDigest(report);

  return (
    <ReportShell
      activeMode="daily"
      secondary={
        <div className="mt-6">
          <div className="text-sm font-semibold text-ink-mid">往期 AI 日报</div>
          {monthGroups.length === 0 ? (
            <p className="mt-3 text-xs leading-5 text-ink-dim">日报归档随每日生成自动积累</p>
          ) : (
            <div className="mt-3 divide-y divide-line">
              {monthGroups.map(([month, dates], index) => {
                const activeMonth = dates.includes(report.report_date);
                return (
                  <details key={month} className="group py-1" open={index === 0 || activeMonth}>
                    <summary className="flex cursor-pointer list-none items-center justify-between rounded-md px-3 py-2.5 text-sm font-semibold text-ink-mid transition hover:bg-panel-soft hover:text-ink">
                      <span className="flex items-center gap-2">
                        <span className="text-ink-dim transition group-open:rotate-90">›</span>
                        {month.replace("-", " 年 ")} 月
                      </span>
                      <span className="readout text-xs text-ink-dim">{dates.length}</span>
                    </summary>
                    <div className="mt-1 space-y-1 pb-2 pl-4">
                      {dates.map((value) => (
                        <a
                          key={value}
                          className={`block rounded-md px-3 py-2 text-sm transition ${
                            value === report.report_date
                              ? "bg-signal/10 text-signal-bright"
                              : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                          }`}
                          href={`/daily/${value}`}
                        >
                          <span className="readout">{value.slice(-2)} 日</span>
                        </a>
                      ))}
                    </div>
                  </details>
                );
              })}
            </div>
          )}
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
            className="mt-6 text-4xl font-semibold leading-none tracking-tight text-ink md:text-5xl"
          >
            <span className="text-ink">AI</span>
            <span className="text-signal">·RADAR</span> 日报
          </h1>
          <div className="mt-6 grid items-center gap-4 text-sm text-ink-mid md:grid-cols-[auto_1fr_auto]">
            <span>{formatChineseDate(report.report_date)}</span>
            <span className="hidden h-px bg-panel-soft md:block" />
            <span>DAILY · 每日八时</span>
          </div>
          {(() => {
            const index = archiveDates.indexOf(report.report_date);
            const newer = index > 0 ? archiveDates[index - 1] : null;
            const older =
              index >= 0 && index < archiveDates.length - 1 ? archiveDates[index + 1] : null;
            if (!newer && !older) return null;
            return (
              <div className="readout mt-4 flex gap-4 text-xs text-ink-dim">
                {older ? (
                  <a className="hover:text-signal" href={`/daily/${older}`}>
                    ← 前一日 {older}
                  </a>
                ) : null}
                {newer ? (
                  <a className="hover:text-signal" href={`/daily/${newer}`}>
                    后一日 {newer} →
                  </a>
                ) : null}
              </div>
            );
          })()}
        </header>

        <section className="rounded-md border border-line bg-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">今日看点</h2>
            <div className="text-sm text-ink-dim">{report.article_count} 篇报道</div>
          </div>
          <div className="mt-3 divide-y divide-line">
            {digest.highlights.map((highlight, index) => (
              <a
                key={highlight.label}
                className="grid gap-2 rounded-md px-2 py-2.5 text-sm transition hover:bg-panel-soft/60 md:grid-cols-[36px_1fr_40px]"
                href={eventHref(highlight.items[0])}
              >
                <span className="font-semibold text-signal">{String(index + 1).padStart(2, "0")}</span>
                <span>
                  <span className="block font-semibold text-ink">{highlight.label}</span>
                  <span className="mt-0.5 block text-ink-mid">{highlight.title}</span>
                </span>
                <span className="text-ink-dim md:text-right">{highlight.count}</span>
              </a>
            ))}
          </div>
        </section>

        <div className="mt-5 grid gap-3 md:grid-cols-4">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="rounded-md border border-line bg-panel p-3 text-center">
              <div className="text-xl font-semibold text-ink">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>

        <div className="mt-8 space-y-8">
          {digest.sections.map((section, sectionIndex) => (
            <section key={section.key}>
              <div className="flex items-end justify-between gap-4">
                <h2 className="text-xl font-semibold text-ink">
                  <span className="mr-3 text-3xl text-signal">
                    {String(sectionIndex + 1).padStart(2, "0")}
                  </span>
                  {section.label}
                </h2>
                <span className="text-sm font-semibold text-signal">{section.items.length} 篇</span>
              </div>

              <div className="mt-4 grid gap-3">
                {section.items.map((item) => (
                  <article key={item.event_id} className="card-hover rounded-md border border-line bg-panel p-4">
                    <div className="text-xs text-signal-bright">
                      {item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源
                    </div>
                    <h3 className="mt-1.5 text-base font-semibold leading-6 text-ink">
                      <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-ink-mid">
                      {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                    </p>
                    <p className="mt-3 rounded-md bg-signal/10 px-3 py-2.5 text-sm leading-6 text-signal-bright">
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
