import { getPeriodArchive, getPeriodReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { BookmarkButton } from "@/components/bookmark-button";
import { buildPeriodDigest, splitParagraphs, type PeriodMode } from "./report-data";
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
  periodKey,
}: {
  mode: PeriodMode;
  title: string;
  mainlineLabel: string;
  highlightsTitle: string;
  themeLabel: string;
  periodKey?: string;
}) {
  const [period, archive] = await Promise.all([
    getPeriodReport(mode, periodKey),
    getPeriodArchive(mode),
  ]);
  const digest = buildPeriodDigest(period, mode);
  const activeKey = period.period_key ?? "";

  return (
    <ReportShell
      activeMode={mode}
      secondary={
        <div className="mt-6">
          <div className="text-sm font-semibold text-ink-mid">往期 AI {labelFor(mode)}</div>
          <div className="mt-3 space-y-1">
            {archive.length === 0 ? (
              <p className="text-xs leading-5 text-ink-dim">
                第一期{labelFor(mode)}生成后会出现在这里
              </p>
            ) : (
              archive.map((entry) => (
                <a
                  key={entry.period_key}
                  className={`block rounded-md px-3 py-2.5 text-sm transition ${
                    entry.period_key === activeKey
                      ? "bg-signal/10 text-signal-bright"
                      : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                  }`}
                  href={`/${mode}/${encodeURIComponent(entry.period_key)}`}
                >
                  <span className="readout block text-xs">{entry.period_key}</span>
                  <span className="mt-0.5 line-clamp-2 block text-xs leading-5">
                    {entry.mainline_title || `${entry.article_count} 条动态`}
                  </span>
                </a>
              ))
            )}
          </div>
          <div className="mt-5 border-t border-line pt-4 text-sm text-ink-dim">
            <a className="hover:text-signal" href="/all">
              查看全部
            </a>
          </div>
        </div>
      }
    >
      <div className="mx-auto max-w-4xl">
        <header className="pb-8">
          <div className="flex items-center gap-4 text-xs font-semibold uppercase tracking-[0.35em] text-ink-dim">
            <span className="h-px w-12 bg-signal" />
            <span>{digest.issueMeta}</span>
          </div>
          <h1
            aria-label={title}
            className="mt-6 text-[26px] font-semibold leading-tight tracking-tight text-ink md:text-4xl md:leading-none lg:text-5xl"
          >
            <span className="text-ink">AI</span>
            <span className="text-signal">·RADAR</span> {labelFor(mode)}
          </h1>
          <div className="mt-6 grid items-center gap-4 text-sm text-ink-mid md:grid-cols-[auto_1fr_auto]">
            <span>{digest.range}</span>
            <span className="hidden h-px bg-panel-soft md:block" />
            <span>
              {digest.label} · {mode === "weekly" ? "本周日报的汇总，AI 提炼主线" : "当月日报的汇总，AI 提炼主线"}
            </span>
          </div>
        </header>

        {period.error ? (
          <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
            {period.error}
          </div>
        ) : null}

        <section className="rounded-md border-l-4 border-signal bg-signal/10 p-4">
          <div className="flex items-center gap-3 text-sm font-semibold text-signal-bright">
            {mainlineLabel}
            {digest.mainline.ai ? (
              <span className="readout rounded border border-signal/40 px-2 py-0.5 text-[10px] uppercase tracking-wider">
                AI 综述
              </span>
            ) : null}
          </div>
          <h2 className="mt-2.5 text-2xl font-semibold leading-tight text-ink">{digest.mainline.title}</h2>
          <div className="mt-3 space-y-2.5 text-sm leading-6 text-ink-mid">
            {splitParagraphs(digest.mainline.body).map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
          </div>
          {digest.themeNotes.length > 0 ? (
            <div className="mt-4 grid gap-2.5 border-t border-signal/20 pt-3 sm:grid-cols-2">
              {digest.themeNotes.map((note) => (
                <div key={note.label} className="rounded-md border border-signal/15 bg-panel/60 px-3 py-2">
                  <div className="text-xs font-semibold uppercase tracking-wide text-signal">{note.label}</div>
                  <div className="mt-1 text-sm leading-6 text-ink-mid">{note.note}</div>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="rounded-md border border-line bg-panel p-3 text-center">
              <div className="text-xl font-semibold text-ink">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>

        <section className="mt-8 rounded-md border border-line bg-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">{highlightsTitle}</h2>
            <div className="text-sm text-ink-dim">
              {digest.highlights.length} 个主题 · {period.items.length} 篇报道
            </div>
          </div>
          <div className="mt-3 divide-y divide-line">
            {digest.highlights.map((highlight, index) => (
              <a
                key={highlight.label}
                className="flex items-start gap-2 rounded-md px-2 py-2.5 text-sm transition hover:bg-panel-soft/60 md:grid md:grid-cols-[36px_1fr_40px] md:items-center md:gap-2"
                href={`#theme-${index}`}
              >
                <span className="shrink-0 font-semibold text-signal">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 flex-1 md:contents">
                  <span className="font-semibold text-ink">{highlight.label}：{highlight.title}</span>
                  {/* 移动端隐藏，理由同日报页：窄屏纵向堆叠时计数会单独占一行 */}
                  <span className="mt-0.5 hidden text-ink-dim md:mt-0 md:block md:text-right">
                    {highlight.count}
                  </span>
                </span>
              </a>
            ))}
          </div>
        </section>

        <div className="mt-10 space-y-8">
          {digest.sections.map((section, index) => (
            <section key={section.label} id={`theme-${index}`} className="scroll-mt-20">
              <div className="flex items-end justify-between gap-4">
                <h2 className="text-xl font-semibold text-ink">
                  <span className="mr-3 text-3xl text-signal">{String(index + 1).padStart(2, "0")}</span>
                  {themeLabel}：{section.label}
                </h2>
                <span className="text-sm font-semibold text-signal">{section.count} 篇</span>
              </div>
              <p className="mt-4 text-sm leading-6 text-ink-mid">
                {section.items[0]?.summary ?? section.items[0]?.one_line_summary ?? "暂无主题摘要。"}
              </p>
              <div className="mt-4 grid gap-3">
                {section.items.slice(0, 3).map((item) => (
                  <article key={item.event_id} className="card-hover rounded-md border border-line bg-panel p-4">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-base font-semibold text-ink">
                        <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
                      </h3>
                      <div className="flex shrink-0 items-center gap-2">
                        {(item.source_count ?? 1) > 1 && (
                          <span className="whitespace-nowrap text-xs text-ink-dim">
                            相关来源 {item.source_count} 个
                          </span>
                        )}
                        <BookmarkButton eventId={item.event_id} />
                      </div>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-ink-mid">
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
