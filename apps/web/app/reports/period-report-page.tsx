import { getPeriodReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { buildPeriodDigest, type PeriodMode } from "./report-data";
import { ReportShell } from "./report-shell";

function labelFor(mode: PeriodMode) {
  return mode === "weekly" ? "周报" : "月报";
}

export async function PeriodReportPage({
  mode,
  title,
  mainlineLabel,
  highlightsTitle,
  themeLabel,
}: {
  mode: PeriodMode;
  title: string;
  mainlineLabel: string;
  highlightsTitle: string;
  themeLabel: string;
}) {
  const period = await getPeriodReport(mode);
  const digest = buildPeriodDigest(period, mode);

  return (
    <ReportShell
      activeMode={mode}
      secondary={
        <div className="mt-6">
          <div className="text-sm font-semibold text-ink-mid">
            {mode === "weekly" ? "本周" : "本月"}
          </div>
          <div className="mt-3 rounded-md bg-signal/10 px-3 py-3 text-sm text-signal-bright">
            <div className="readout text-xs">{digest.range}</div>
            <div className="mt-2 line-clamp-2">{digest.mainline.title}</div>
          </div>
          <p className="mt-4 text-xs leading-5 text-ink-dim">
            往期{labelFor(mode)}归档将随数据积累逐步开放
          </p>
          <div className="mt-5 border-t border-line pt-4 text-sm text-ink-dim">
            <a className="hover:text-signal" href="/all">
              查看全部动态
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
            aria-label={title}
            className="mt-8 text-5xl font-semibold leading-none tracking-tight text-ink md:text-7xl"
          >
            <span className="text-ink">AI</span>
            <span className="text-signal">·RADAR</span> {labelFor(mode)}
          </h1>
          <div className="mt-8 grid items-center gap-4 text-sm text-ink-mid md:grid-cols-[auto_1fr_auto]">
            <span>{digest.range}</span>
            <span className="hidden h-px bg-panel-soft md:block" />
            <span>{digest.label} · 编辑系统自动融合</span>
          </div>
        </header>

        <section className="rounded-md border-l-4 border-signal bg-signal/10 p-6">
          <div className="text-sm font-semibold text-signal-bright">{mainlineLabel}</div>
          <h2 className="mt-3 text-3xl font-semibold leading-tight text-ink">{digest.mainline.title}</h2>
          <p className="mt-4 text-[15px] leading-7 text-ink-mid">{digest.mainline.body}</p>
        </section>

        <div className="mt-6 grid gap-3 md:grid-cols-4">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="rounded-md border border-line bg-panel p-4 text-center">
              <div className="text-2xl font-semibold text-ink">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>

        <section className="mt-10 rounded-md border border-line bg-panel p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">{highlightsTitle}</h2>
            <div className="text-sm text-ink-dim">
              {digest.highlights.length} 个主题 · {period.items.length} 篇报道
            </div>
          </div>
          <div className="mt-4 divide-y divide-line">
            {digest.highlights.map((highlight, index) => (
              <a
                key={highlight.label}
                className="grid gap-2 rounded-md px-2 py-3 text-sm transition hover:bg-panel-soft/60 md:grid-cols-[36px_1fr_40px]"
                href={eventHref(highlight.items[0])}
              >
                <span className="font-semibold text-signal">{String(index + 1).padStart(2, "0")}</span>
                <span className="font-semibold text-ink">{highlight.label}：{highlight.title}</span>
                <span className="text-ink-dim md:text-right">{highlight.count}</span>
              </a>
            ))}
          </div>
        </section>

        <div className="mt-14 space-y-12">
          {digest.sections.map((section, index) => (
            <section key={section.label}>
              <div className="flex items-end justify-between gap-4">
                <h2 className="text-3xl font-semibold text-ink">
                  <span className="mr-4 text-5xl text-signal">{String(index + 1).padStart(2, "0")}</span>
                  {themeLabel}：{section.label}
                </h2>
                <span className="text-sm font-semibold text-signal">{section.count} 篇</span>
              </div>
              <p className="mt-6 text-sm leading-7 text-ink-mid">
                {section.items[0]?.summary ?? section.items[0]?.one_line_summary ?? "暂无主题摘要。"}
              </p>
              <div className="mt-5 grid gap-4">
                {section.items.slice(0, 3).map((item) => (
                  <article key={item.event_id} className="card-hover rounded-md border border-line bg-panel p-5">
                    <h3 className="text-lg font-semibold text-ink">
                      <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-ink-mid">
                      {item.reason ?? item.one_line_summary ?? "暂无推荐理由。"}
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
