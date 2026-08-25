import { DailyReport, getDailyArchive, getDailyReport, getLatestReport } from "@/lib/api";
import { BookmarkButton } from "@/components/bookmark-button";
import { eventHref, formatScore } from "@/lib/events";
import { buildDailyDigest, latestToDailyReport, splitParagraphs } from "../reports/report-data";
import { ReportShell } from "../reports/report-shell";

type DailySearchParams = Promise<{ date?: string | string[] }>;

export async function generateMetadata({
  searchParams,
}: {
  searchParams: DailySearchParams;
}) {
  const resolved = await searchParams;
  const date = Array.isArray(resolved.date) ? resolved.date[0] : resolved.date;
  return {
    title: date ? `AI 日报 ${date}` : "AI 日报",
    description: "全天滚动更新的 AI 精选日报：当日高价值动态、重点栏目与标签一页读完，次日定稿。",
    // 每一期日报是独立内容，带上 date 参数才不会被判成同一页的重复副本
    alternates: { canonical: date ? `/daily?date=${date}` : "/daily" },
  };
}

type LoadedReport =
  | { kind: "report"; report: DailyReport }
  // "today" (explicit or implicit) hasn't had its pipeline run persist a
  // daily_reports row yet - show the rolling 精选 pool as a stand-in, but the
  // caller must say so instead of passing this off as the real thing
  | { kind: "pending"; report: DailyReport }
  // an explicit past date that never got (and never will get) a report -
  // showing unrelated rolling content here would be actively misleading
  | { kind: "empty"; date: string };

function todayInShanghai(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
}

async function loadReport(
  preferredDate: string | undefined,
  archiveDates: string[]
): Promise<LoadedReport> {
  // 优先用显式请求的日期，否则用归档里真实存在的最新一期——不能信
  // getLatestReport().report_date：那是滚动窗口拼出来的"今天"，在今天
  // 的日报还没生成之前，这个日期在 daily_reports 里根本不存在
  const targetDate = preferredDate ?? archiveDates[0];
  if (targetDate) {
    try {
      const report = await getDailyReport(targetDate);
      if (report.article_count > 0) {
        return { kind: "report", report };
      }
    } catch {
      // 请求的日期没有真实日报，继续往下判断该不该兜底
    }
  }
  // 只有"今天"（未显式指定日期，或显式请求的就是今天）才用滚动精选池
  // 顶替——流水线是按小时跑的，今天的日报可能确实还没生成完。显式请求
  // 的其它日期永远不会自动补出一份，用空状态如实告知
  const isTodayOrUnspecified = !preferredDate || preferredDate === todayInShanghai();
  if (isTodayOrUnspecified) {
    const latest = await getLatestReport();
    return { kind: "pending", report: latestToDailyReport(latest) };
  }
  return { kind: "empty", date: targetDate ?? preferredDate ?? todayInShanghai() };
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

export default async function DailyPage({
  searchParams,
}: {
  searchParams: DailySearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const requestedDate = Array.isArray(resolvedSearchParams.date)
    ? resolvedSearchParams.date[0]
    : resolvedSearchParams.date;
  const archiveDates = await getDailyArchive();
  const loaded = await loadReport(requestedDate, archiveDates);
  const monthGroups = groupDatesByMonth(archiveDates);
  const activeDate = loaded.kind === "empty" ? loaded.date : loaded.report.report_date;
  const digest = loaded.kind === "empty" ? null : buildDailyDigest(loaded.report);

  return (
    <ReportShell
      activeMode="daily"
      secondary={
        <div className="mt-6">
          <div className="text-sm font-semibold text-ink-mid">往期 AI 日报</div>
          {monthGroups.length === 0 ? (
            <p className="mt-3 text-xs leading-5 text-ink-dim">第一期日报生成后会出现在这里</p>
          ) : (
            <div className="mt-3 divide-y divide-line">
              {monthGroups.map(([month, dates], index) => {
                const activeMonth = dates.includes(activeDate);
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
                            value === activeDate
                              ? "bg-signal/10 text-signal-bright"
                              : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                          }`}
                          href={`/daily?date=${value}`}
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
        <header className="pb-5 md:pb-8">
          <div className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.25em] text-ink-dim md:gap-4 md:text-xs md:tracking-[0.35em]">
            <span className="h-px w-8 bg-signal md:w-12" />
            <span>
              {digest ? digest.issueMeta : `VOL.${activeDate.replaceAll("-", ".")} · NO REPORT`}
            </span>
          </div>
          <h1
            aria-label="AI·RADAR 日报"
            className="editorial-rule-title mt-4 text-[34px] font-medium leading-tight text-ink md:mt-6 md:text-5xl md:leading-none lg:text-6xl"
          >
            <span className="text-ink">AI</span>
            <span className="text-signal">·RADAR</span> 日报
          </h1>
          <div className="mt-5 grid items-center gap-2 border-b border-line-strong pb-4 text-sm text-ink-mid md:mt-7 md:grid-cols-[auto_1fr_auto] md:gap-4 md:pb-6">
            <span>{formatChineseDate(activeDate)}</span>
            <span className="hidden h-px bg-panel-soft md:block" />
            <span>DAILY · 全天滚动更新，次日定稿</span>
          </div>
          {(() => {
            const index = archiveDates.indexOf(activeDate);
            const newer = index > 0 ? archiveDates[index - 1] : null;
            const older =
              index >= 0 && index < archiveDates.length - 1 ? archiveDates[index + 1] : null;
            if (!newer && !older) return null;
            return (
              <div className="readout mt-4 flex gap-4 text-xs text-ink-dim">
                {older ? (
                  <a className="hover:text-signal" href={`/daily?date=${older}`}>
                    ← 前一日 {older}
                  </a>
                ) : null}
                {newer ? (
                  <a className="hover:text-signal" href={`/daily?date=${newer}`}>
                    后一日 {newer} →
                  </a>
                ) : null}
              </div>
            );
          })()}
          {loaded.kind === "pending" ? (
            <div className="mt-5 bg-signal/5 px-4 py-3 text-sm text-signal-bright">
              今日日报还在生成中，先展示近期精选内容，稍后刷新即可查看正式版本。
            </div>
          ) : null}
        </header>

        {loaded.kind === "empty" ? (
          <section className="rounded-md border border-line bg-panel p-8 text-center">
            <p className="text-base font-semibold text-ink">{formatChineseDate(activeDate)} 暂无日报</p>
            <p className="mt-2 text-sm leading-6 text-ink-dim">
              这一天没有生成过日报，可能早于本站上线，或当日未更新。可从归档里选择其他日期。
            </p>
          </section>
        ) : (
          <>
            {digest!.mainline ? (
              <section className="border-l-2 border-signal py-1 pl-5 pr-2">
                <div className="flex items-center gap-3 text-sm font-semibold text-signal-bright">
                  今日主线
                  <span className="readout rounded border border-signal/40 px-2 py-0.5 text-[10px] uppercase tracking-wider">
                    AI 综述
                  </span>
                </div>
                <h2 className="editorial-rule-title mt-2.5 text-3xl font-medium leading-tight text-ink">
                  {digest!.mainline.title}
                </h2>
                <div className="mt-3 space-y-2.5 text-sm leading-6 text-ink-mid">
                  {splitParagraphs(digest!.mainline.body).map((paragraph, index) => (
                    <p key={index}>{paragraph}</p>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="editorial-surface mt-8">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-ink">今日看点</h2>
                <div className="text-sm text-ink-dim">{loaded.report.article_count} 篇报道</div>
              </div>
              <div className="mt-3 divide-y divide-line">
                {digest!.categories.map((category, index) => (
                  <a
                    key={category.key}
                    className="flex items-start gap-2 rounded-md px-2 py-2.5 text-sm transition hover:bg-panel-soft/60 md:grid md:grid-cols-[36px_1fr_40px] md:items-start md:gap-2"
                    href={`#cat-${category.key}`}
                  >
                    <span className="shrink-0 font-semibold text-signal">{String(index + 1).padStart(2, "0")}</span>
                    <span className="min-w-0 flex-1 md:contents">
                      <span>
                        <span className="block font-semibold text-ink">{category.label}</span>
                        <span className="mt-0.5 block leading-6 text-ink-mid">
                          {category.note ?? `${category.count} 条动态`}
                        </span>
                      </span>
                      {/* 移动端隐藏：这一行在窄屏是纵向堆叠的，计数会单独占一行
                          杵在简述下面。桌面端是三列网格，它有自己的列，不碍事。 */}
                      <span className="mt-0.5 hidden text-ink-dim md:mt-0 md:block md:text-right">
                        {category.count}
                      </span>
                    </span>
                  </a>
                ))}
              </div>
            </section>

            <div className="mt-5 grid grid-cols-4 divide-x divide-line md:mt-8">
              {digest!.stats.map((stat) => (
                <div key={stat.label} className="min-w-0 px-1 py-2.5 text-center md:px-3 md:py-4">
                  <div className="whitespace-nowrap text-base font-semibold text-ink md:text-xl">{stat.value}</div>
                  <div className="mt-1 text-[10px] leading-4 text-ink-dim md:text-xs">{stat.label}</div>
                </div>
              ))}
            </div>

            <div className="mt-8 space-y-6">
              {/* details/summary 而不是 useState：这一页是服务端组件，折叠用
                  原生元素就够，不必为了一个开合把整棵树变成客户端组件。
                  默认展开——折叠是新增能力，不是新的默认隐藏。 */}
              {digest!.categories.map((category, categoryIndex) => (
                <details
                  key={category.key}
                  id={`cat-${category.key}`}
                  open
                  className="group scroll-mt-20"
                >
                  {/* list-none 去掉默认三角，Safari 还要单独关掉 webkit 的那个 */}
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 border-b border-line pb-3 transition hover:border-signal/40 [&::-webkit-details-marker]:hidden">
                    <h2 className="editorial-rule-title text-2xl font-medium text-ink">
                      <span className="mr-3 text-3xl text-signal">
                        {String(categoryIndex + 1).padStart(2, "0")}
                      </span>
                      {category.label}
                    </h2>
                    <span className="flex shrink-0 items-center gap-3 text-sm font-semibold text-signal">
                      {category.count} 篇
                      {/* 原来只是一个 ▾ 字符，跟计数挤在一起、又是 dim 色，
                          看不出可以点。改成有边框有底色的圆形按钮。 */}
                      <span
                        className="flex h-7 w-7 items-center justify-center rounded-full border border-line bg-panel-soft text-ink-mid transition group-hover:border-signal/50 group-hover:bg-signal/10 group-hover:text-signal group-open:rotate-180"
                        aria-hidden
                      >
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                          <path
                            d="M2.5 4.5L6 8L9.5 4.5"
                            stroke="currentColor"
                            strokeWidth="1.75"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </span>
                    </span>
                  </summary>

                  {/* 分类简述只在「今日看点」出一次；这里再放一遍就是同一页
                      里把同一段话读两遍。看点那行的锚点直接跳到这里。 */}
                  <div className="mt-4 grid gap-3">
                    {category.items.map((item) => (
                      <article key={item.event_id} className="card-hover editorial-feed-hover rounded-md border border-line bg-panel p-4">
                        {/* 评分徽章与收藏按钮的样式、位置、compact 档位都照
                            components/event-card.tsx 来——精选页用的就是它，
                            同一条内容在两个页面上必须长得一样。 */}
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 truncate text-xs leading-5 text-signal-bright">
                            {item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源
                          </div>
                          <div className="flex shrink-0 items-center gap-1.5">
                            <span className="readout inline-flex h-5 items-center justify-center rounded-full border border-signal/40 px-1.5 text-[11px] font-semibold leading-none text-signal">
                              {formatScore(item.final_score)}
                            </span>
                            <BookmarkButton eventId={item.event_id} compact />
                          </div>
                        </div>
                        <h3 className="mt-3 text-base font-semibold leading-6 text-ink">
                          <a className="title-link" href={eventHref(item)}>{item.title}</a>
                        </h3>
                        <p className="mt-3 text-sm leading-6 text-ink-mid">
                          {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                        </p>
                      </article>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </>
        )}
      </div>
    </ReportShell>
  );
}
