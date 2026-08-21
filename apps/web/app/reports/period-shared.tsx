import type { LatestEvent, PeriodArchiveEntry } from "@/lib/api";
import { BookmarkButton } from "@/components/bookmark-button";
import { eventHref, formatScore } from "@/lib/events";
import type { PeriodMode } from "./report-data";

export function periodLabel(mode: PeriodMode) {
  return mode === "weekly" ? "周报" : "月报";
}

/** 往期归档侧栏：周月报共用，样式沿用改版前。 */
export function PeriodArchiveList({
  mode,
  archive,
  activeKey,
}: {
  mode: PeriodMode;
  archive: PeriodArchiveEntry[];
  activeKey: string;
}) {
  return (
    <div className="mt-6">
      <div className="text-sm font-semibold text-ink-mid">往期 AI {periodLabel(mode)}</div>
      <div className="mt-3 space-y-1">
        {archive.length === 0 ? (
          <p className="text-xs leading-5 text-ink-dim">
            第一期{periodLabel(mode)}生成后会出现在这里
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
  );
}

/** 页头：报头、期次范围、副标语，与日报页同构。 */
export function PeriodHeader({
  mode,
  issueMeta,
  range,
  tagline,
}: {
  mode: PeriodMode;
  issueMeta: string;
  range: string;
  tagline: string;
}) {
  return (
    <header className="pb-8">
      <div className="flex items-center gap-4 text-xs font-semibold uppercase tracking-[0.35em] text-ink-dim">
        <span className="h-px w-12 bg-signal" />
        <span>{issueMeta}</span>
      </div>
      <h1
        aria-label={`AI·RADAR ${periodLabel(mode)}`}
        className="mt-6 text-[26px] font-semibold leading-tight tracking-tight text-ink md:text-4xl md:leading-none lg:text-5xl"
      >
        <span className="text-ink">AI</span>
        <span className="text-signal">·RADAR</span> {periodLabel(mode)}
      </h1>
      <div className="mt-6 grid items-center gap-4 text-sm text-ink-mid md:grid-cols-[auto_1fr_auto]">
        <span>{range}</span>
        <span className="hidden h-px bg-panel-soft md:block" />
        <span>{tagline}</span>
      </div>
    </header>
  );
}

/** 进行中的期次要明说：文字和名单都还会随日报刷新变化，X 日定稿。
 *
 *  已封版、以及已经翻篇但没定稿的期次都不挂横幅：前者定稿是常态不值得说，
 *  后者说「进行中，X 日定稿」是双重虚假陈述——内容早就没人再碰，日期也已
 *  经过去了。 */
export function SealBanner({
  seal,
}: {
  seal: { sealed: boolean; sealDate: string | null; live: boolean };
}) {
  if (seal.sealed || !seal.live) {
    return null;
  }
  return (
    <div className="mb-5 rounded-md border border-signal/40 bg-signal/10 px-4 py-3 text-sm text-signal-bright">
      本期进行中，内容随日报每日更新{seal.sealDate ? `，${seal.sealDate} 定稿` : ""}。
    </div>
  );
}

/** 主线综述块：周月报共用，样式与日报的「今日主线」一致。 */
export function MainlineSection({
  label,
  mainline,
}: {
  label: string;
  mainline: { title: string; body: string; ai: boolean };
}) {
  return (
    <section className="rounded-md border-l-4 border-signal bg-signal/10 p-4">
      <div className="flex items-center gap-3 text-sm font-semibold text-signal-bright">
        {label}
        {mainline.ai ? (
          <span className="readout rounded border border-signal/40 px-2 py-0.5 text-[10px] uppercase tracking-wider">
            AI 综述
          </span>
        ) : null}
      </div>
      <h2 className="mt-2.5 text-2xl font-semibold leading-tight text-ink">{mainline.title}</h2>
      <div className="mt-3 space-y-2.5 text-sm leading-6 text-ink-mid">
        {mainline.body
          .split(/\n+/)
          .map((paragraph) => paragraph.trim())
          .filter(Boolean)
          .map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
      </div>
    </section>
  );
}

/** 事件卡：样式、评分徽章、收藏按钮全部照日报页的卡片来——同一条内容
 *  在日/周/月三个页面上必须长得一样。周月报多一个「连报 N 天」徽章，
 *  这是它们独有的持续度信号。 */
export function PeriodEventCard({ item, rank }: { item: LatestEvent; rank?: number }) {
  return (
    <article className="card-hover min-w-0 rounded-md border border-line bg-panel p-4 [overflow-wrap:anywhere]">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 truncate text-xs leading-5 text-signal-bright">
          {rank !== undefined ? (
            <span className="readout shrink-0 font-semibold text-signal">
              {String(rank).padStart(2, "0")}
            </span>
          ) : null}
          <span className="min-w-0 truncate">
            {item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源
            {(item.days_covered ?? 1) > 1 ? ` · 连报 ${item.days_covered} 天` : ""}
          </span>
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
  );
}
