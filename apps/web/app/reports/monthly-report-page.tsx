import { getPeriodArchive, getPeriodReport } from "@/lib/api";
import { buildMonthlyDigest } from "./report-data";
import {
  MainlineSection,
  PeriodArchiveList,
  PeriodEventCard,
  PeriodHeader,
  SealBanner,
} from "./period-shared";
import { ReportShell } from "./report-shell";

/** 月报页：刻意不与周报同构。月尺度上「模型动态」这类分类每月都有、
 *  每月都差不多，按它组织正文，8 月月报和 7 月长得一样。月报答的是
 *  「这个月什么在变」——正文主体是 2-3 条跨分类的趋势线，每条挂
 *  后端校验过的证据事件；收尾是完整榜单（20-25 条名单序）和月度数据面。 */
export async function MonthlyReportPage({ periodKey }: { periodKey?: string }) {
  const [period, archive] = await Promise.all([
    getPeriodReport("monthly", periodKey),
    getPeriodArchive("monthly"),
  ]);
  const digest = buildMonthlyDigest(period);
  const activeKey = period.period_key ?? "";
  const maxCategoryCount = Math.max(
    1,
    ...digest.categoryDistribution.map(([, count]) => count),
  );

  return (
    <ReportShell
      activeMode="monthly"
      secondary={<PeriodArchiveList mode="monthly" archive={archive} activeKey={activeKey} />}
    >
      <div className="mx-auto max-w-4xl">
        <PeriodHeader
          mode="monthly"
          issueMeta={digest.issueMeta}
          range={digest.range}
          tagline="MONTHLY · 当月趋势提炼，代表事件为证"
        />

        {period.error ? (
          <div className="mb-5 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
            {period.error}
          </div>
        ) : null}

        <SealBanner seal={digest.seal} />

        <MainlineSection label="本月总述" mainline={digest.mainline} />

        {/* 月度数据面：把生成时冻结的 stats 真正用起来 */}
        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="rounded-md border border-line bg-panel p-3 text-center">
              <div className="text-xl font-semibold text-ink">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>

        {digest.categoryDistribution.length > 0 ? (
          <section className="mt-5 rounded-md border border-line bg-panel p-4">
            <h2 className="text-base font-semibold text-ink">收录分布</h2>
            <div className="mt-3 space-y-2">
              {digest.categoryDistribution.map(([label, count]) => (
                <div key={label} className="grid grid-cols-[5.5rem_1fr_2.5rem] items-center gap-3 text-sm">
                  <span className="text-ink-mid">{label}</span>
                  <span className="h-2 overflow-hidden rounded-full bg-panel-soft">
                    <span
                      className="block h-full rounded-full bg-signal/60"
                      style={{ width: `${Math.max(4, Math.round((count / maxCategoryCount) * 100))}%` }}
                    />
                  </span>
                  <span className="readout text-right text-xs text-ink-dim">{count}</span>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {/* 趋势线：月报的正文主体 */}
        {digest.trends.length > 0 ? (
          <div className="mt-10 space-y-8">
            {digest.trends.map((trend, index) => (
              <section key={trend.label} className="scroll-mt-20">
                <div className="flex items-end gap-4">
                  <h2 className="text-xl font-semibold text-ink">
                    <span className="mr-3 text-3xl text-signal">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    {trend.label}
                  </h2>
                </div>
                <p className="mt-4 text-sm leading-7 text-ink-mid">{trend.note}</p>
                {/* 证据事件：后端已按入选名单校验 event_ids，这里只解析不补位。
                    空列表就只显示论述——宁缺毋假。 */}
                {trend.items.length > 0 ? (
                  <div className="mt-4 grid gap-3">
                    {trend.items.map((item) => (
                      <PeriodEventCard key={item.event_id} item={item} />
                    ))}
                  </div>
                ) : null}
              </section>
            ))}
          </div>
        ) : null}

        {/* 完整榜单：名单序（多信源 → 持续度 → 分位），趋势线之外的入选
            条目也在这里露出，一条不藏 */}
        {digest.ranked.length > 0 ? (
          <section className="mt-10">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
              <h2 className="text-xl font-semibold text-ink">本月榜单</h2>
              <span className="text-sm text-ink-dim">{digest.ranked.length} 条入选 · 全量见 /all</span>
            </div>
            <div className="mt-4 grid gap-3">
              {digest.ranked.map((item, index) => (
                <div key={item.event_id} className="flex items-start gap-3">
                  <span className="readout mt-4 w-7 shrink-0 text-right text-sm font-semibold text-signal">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <PeriodEventCard item={item} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </ReportShell>
  );
}
