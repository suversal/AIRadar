import { getPeriodArchive, getPeriodReport } from "@/lib/api";
import { buildWeeklyDigest } from "./report-data";
import {
  MainlineSection,
  PeriodArchiveList,
  PeriodEventCard,
  PeriodHeader,
  SealBanner,
} from "./period-shared";
import { ReportShell } from "./report-shell";

/** 周报页：日报的放大版，结构与 /daily 同构——主线 + 分类概述（本周看点）
 *  + 分类列表。名单 30-40 条全部露出，不再每板块只截 3 条；没入选的
 *  仍在 /all。读者从日报切过来，理解模型不用换。 */
export async function WeeklyReportPage({ periodKey }: { periodKey?: string }) {
  const [period, archive] = await Promise.all([
    getPeriodReport("weekly", periodKey),
    getPeriodArchive("weekly"),
  ]);
  const digest = buildWeeklyDigest(period);
  const activeKey = period.period_key ?? "";
  const archiveList = (
    <PeriodArchiveList mode="weekly" archive={archive} activeKey={activeKey} />
  );
  const header = (
    <PeriodHeader
      mode="weekly"
      issueMeta={digest.issueMeta}
      range={digest.range}
      tagline="WEEKLY · 本周日报的汇总，AI 提炼主线与栏目概述"
    />
  );

  // 接口挂了就只说这件事。降级对象里没有任何真实状态，继续往下渲染会在
  // 错误横幅底下叠出「本期进行中」「内容还不够多」这类凭空编造的状态陈述，
  // 读者反而分不清是故障还是真没内容。
  if (period.error) {
    return (
      <ReportShell activeMode="weekly" secondary={archiveList}>
        <div className="mx-auto max-w-4xl">
          {header}
          <div className="rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
            {period.error}
          </div>
        </div>
      </ReportShell>
    );
  }

  return (
    <ReportShell activeMode="weekly" secondary={archiveList}>
      <div className="mx-auto max-w-4xl">
        {header}

        <SealBanner seal={digest.seal} />

        <MainlineSection label="本周主线" mainline={digest.mainline} />

        <section className="editorial-surface mt-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">本周看点</h2>
            <div className="text-sm text-ink-dim">{period.items.length} 篇入选</div>
          </div>
          <div className="mt-3 divide-y divide-line">
            {digest.categories.map((category, index) => (
              <a
                key={category.key}
                className="flex items-start gap-2 rounded-md px-2 py-2.5 text-sm transition hover:bg-panel-soft/60 md:grid md:grid-cols-[36px_1fr_40px] md:items-start md:gap-2"
                href={`#cat-${category.key}`}
              >
                <span className="shrink-0 font-semibold text-signal">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 flex-1 md:contents">
                  <span>
                    <span className="block font-semibold text-ink">{category.label}</span>
                    <span className="mt-0.5 block leading-6 text-ink-mid">
                      {category.note ?? `${category.count} 条动态`}
                    </span>
                  </span>
                  {/* 移动端隐藏，理由同日报页：窄屏纵向堆叠时计数会单独占一行 */}
                  <span className="mt-0.5 hidden text-ink-dim md:mt-0 md:block md:text-right">
                    {category.count}
                  </span>
                </span>
              </a>
            ))}
          </div>
        </section>

        <div className="mt-5 grid grid-cols-4 divide-x divide-line md:mt-8">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="min-w-0 px-1 py-2.5 text-center md:px-3 md:py-4">
              <div className="whitespace-nowrap text-base font-semibold text-ink md:text-xl">{stat.value}</div>
              <div className="mt-1 text-[10px] leading-4 text-ink-dim md:text-xs">{stat.label}</div>
            </div>
          ))}
        </div>

        <div className="mt-8 space-y-6">
          {/* details/summary 折叠，默认展开——与日报页同一套交互与理由 */}
          {digest.categories.map((category, categoryIndex) => (
            <details
              key={category.key}
              id={`cat-${category.key}`}
              open
              className="group scroll-mt-20"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 border-b border-line pb-3 transition hover:border-signal/40 [&::-webkit-details-marker]:hidden">
                <h2 className="editorial-rule-title text-2xl font-medium text-ink">
                  <span className="mr-3 text-3xl text-signal">
                    {String(categoryIndex + 1).padStart(2, "0")}
                  </span>
                  {category.label}
                </h2>
                <span className="flex shrink-0 items-center gap-3 text-sm font-semibold text-signal">
                  {category.count} 篇
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

              {/* 分类概述只在「本周看点」出一次，这里不重复；锚点直接跳到本板块 */}
              <div className="mt-4 grid gap-3">
                {category.items.map((item) => (
                  <PeriodEventCard key={item.event_id} item={item} />
                ))}
              </div>
            </details>
          ))}
        </div>
      </div>
    </ReportShell>
  );
}
