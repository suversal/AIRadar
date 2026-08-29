import { getHotspots, getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { FOCUS_FILTER_OPTIONS, focusCategory } from "@/lib/taxonomy";
import { formatRelativeTime } from "@/lib/time";
import { LatestEventsFeed } from "@/components/latest-events-feed";
import { MobileCategoryNav, MobileSearchForm } from "@/components/mobile-discovery";
import { MobileNav } from "@/components/mobile-nav";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";
import { GridBackground } from "@/components/ui/grid-background";
import { ArrowUpRight, Search, TrendingUp } from "lucide-react";

export const metadata = {
  title: "精选",
  description:
    "AI 每天从数十个信源里筛出的高价值动态，同一件事的多方报道折叠为一条。",
  alternates: { canonical: "/latest" },
};

type LatestSearchParams = Promise<{
  focus?: string | string[];
  category?: string | string[];
  q?: string | string[];
  tag?: string | string[];
}>;

const PAGE_SIZE = 50;
const HOTSPOT_LIMIT = 10;

const categoryOptions = FOCUS_FILTER_OPTIONS;

function firstQueryValue(value?: string | string[]) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "暂无数据";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(parsed)
    .replace(/\//g, "-");
}

function latestHref({ focus, tag, q }: { focus?: string; tag?: string; q?: string }) {
  const params = new URLSearchParams();
  if (focus) {
    params.set("focus", focus);
  }
  if (tag) {
    params.set("tag", tag);
  }
  if (q) {
    params.set("q", q);
  }
  const query = params.toString();
  return query ? `/latest?${query}` : "/latest";
}

export default async function LatestPage({
  searchParams,
}: {
  searchParams: LatestSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const selectedCategory = focusCategory(
    firstQueryValue(resolvedSearchParams.focus),
    firstQueryValue(resolvedSearchParams.category),
  );
  const selectedTag = firstQueryValue(resolvedSearchParams.tag)?.trim() ?? "";
  const query = firstQueryValue(resolvedSearchParams.q)?.trim() ?? "";
  const [report, hotspots] = await Promise.all([
    getLatestReport({
      limit: PAGE_SIZE,
      focus: selectedCategory,
      tag: selectedTag,
      q: query,
    }),
    getHotspots({
      focus: selectedCategory,
      tag: selectedTag,
      q: query,
      limit: HOTSPOT_LIMIT,
    }),
  ]);
  const topEvents = hotspots.items;

  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="latest" />
        <MobileNav activeNavId="latest" />

        <section className="min-w-0 px-4 pb-8 pt-3 md:px-8 md:py-8 xl:px-12">
          <div className="mx-auto max-w-[1320px]">
            <header className="relative overflow-hidden pb-3 pt-1 md:pb-7">
              <GridBackground dense extended className="opacity-25" />
              <div className="relative z-10">
                <RadarStatus
                  compactScope="7天"
                  updatedAt={report.updated_at}
                  eventCount={report.total ?? report.items.length}
                  scope="SELECTED FEED · 7D"
                />
                <div className="mt-6 flex flex-col gap-5 md:mt-12 md:flex-row md:items-end md:justify-between md:gap-6">
                  <div>
                    <p className="readout text-[10px] uppercase tracking-[0.2em] text-signal">AI·RADAR / EDITOR&apos;S PICK</p>
                    <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-2">
                      <h1 className="editorial-display text-[clamp(3.2rem,6vw,5.2rem)] leading-none tracking-[-0.065em] text-ink">
                        精选
                      </h1>
                      <p className="max-w-md pb-1 text-sm leading-6 text-ink-mid">
                        多源聚合、事件折叠，只保留值得花时间的 AI 动态。
                      </p>
                    </div>
                  </div>
                  <dl className="hidden shrink-0 gap-8 text-right md:flex">
                    <div>
                      <dt className="readout text-[9px] uppercase tracking-[0.14em] text-ink-dim">7 天精选</dt>
                      <dd className="editorial-display mt-1 text-2xl text-ink">{report.total ?? report.items.length}</dd>
                    </div>
                    <div>
                      <dt className="readout text-[9px] uppercase tracking-[0.14em] text-ink-dim">近 2 日热点</dt>
                      <dd className="editorial-display mt-1 text-2xl text-ink">{topEvents.length}</dd>
                    </div>
                    <div>
                      <dt className="readout text-[9px] uppercase tracking-[0.14em] text-ink-dim">更新</dt>
                      <dd className="readout mt-2 text-[10px] text-ink-mid">{formatDateTime(report.updated_at)}</dd>
                    </div>
                  </dl>
                </div>
              </div>
            </header>

            <section className="py-2 md:py-3" aria-label="筛选与搜索">
              <MobileSearchForm
                action="/latest"
                defaultValue={query}
                hiddenFields={[
                  ...(selectedCategory ? [{ name: "focus", value: selectedCategory }] : []),
                  ...(selectedTag ? [{ name: "tag", value: selectedTag }] : []),
                ]}
                placeholder="搜索标题或摘要"
              />
              <MobileCategoryNav
                label="精选内容分类"
                options={categoryOptions.map(([category, label]) => ({
                  href: latestHref({ focus: category, tag: selectedTag, q: query }),
                  label,
                  selected: selectedCategory === category,
                }))}
              />

              <div className="hidden items-center gap-4 md:flex">
                <nav aria-label="精选内容分类" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
                  {categoryOptions.map(([category, label]) => (
                    <a
                      key={category || "all"}
                      className={`editorial-filter flex min-h-9 shrink-0 items-center border-b px-2 py-1 text-sm font-medium ${
                        selectedCategory === category
                          ? "border-signal text-signal"
                          : "border-transparent text-ink-mid hover:border-line-strong hover:text-ink"
                      }`}
                      href={latestHref({ focus: category, tag: selectedTag, q: query })}
                    >
                      {label}
                    </a>
                  ))}
                </nav>
                <form action="/latest" className="grid w-[260px] shrink-0 grid-cols-[1fr_auto] border-l border-line pl-3">
                  {selectedCategory ? <input name="focus" type="hidden" value={selectedCategory} /> : null}
                  {selectedTag ? <input name="tag" type="hidden" value={selectedTag} /> : null}
                  <label className="sr-only" htmlFor="latest-search">搜索标题或摘要</label>
                  <input
                    id="latest-search"
                    className="min-h-9 min-w-0 bg-transparent px-2 text-sm text-ink outline-none placeholder:text-ink-dim"
                    defaultValue={query}
                    name="q"
                    placeholder="搜索标题/摘要..."
                    type="search"
                  />
                  <button
                    aria-label="提交搜索"
                    className="flex min-h-9 w-9 items-center justify-center text-ink-mid hover:text-signal"
                    type="submit"
                  >
                    <Search aria-hidden className="h-4 w-4" strokeWidth={1.7} />
                  </button>
                </form>
              </div>
            </section>

            {report.error ? (
              <div className="mt-4 border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
                {report.error}
              </div>
            ) : null}

            {selectedTag ? (
              <div className="mt-4 flex items-center gap-3 bg-panel/45 px-4 py-3 text-sm">
                <span className="font-medium text-signal">
                  标签：{selectedTag} · {report.total ?? report.items.length} 条
                </span>
                <a
                  className="ml-auto text-ink-mid underline decoration-line-strong underline-offset-4 hover:text-ink"
                  href={latestHref({ focus: selectedCategory, q: query })}
                >
                  清除筛选
                </a>
              </div>
            ) : null}

            <div className="grid items-start gap-2 md:gap-7 2xl:grid-cols-[minmax(0,1fr)_320px] 2xl:gap-9">
              <LatestEventsFeed
                initialItems={report.items}
                initialTotal={report.total ?? report.items.length}
                tag={selectedTag}
                selectedCategory={selectedCategory}
                query={query}
              />

              {topEvents.length > 0 ? (
                <aside className="order-first mt-4 border-t border-line-strong md:mt-6 2xl:order-last 2xl:sticky 2xl:top-5" aria-labelledby="hotspot-title">
                  <div className="flex items-center justify-between gap-3 py-2.5 md:py-3">
                    <h2 id="hotspot-title" className="flex items-center gap-2 text-base font-semibold text-ink">
                      当前热点
                      <TrendingUp aria-hidden className="h-4 w-4 text-signal" strokeWidth={1.7} />
                    </h2>
                    <span className="readout text-[10px] uppercase tracking-wider text-ink-dim">近 2 个自然日</span>
                  </div>
                  <ol className="divide-y divide-line/70 md:grid md:grid-cols-3 md:divide-x md:divide-y-0 2xl:block 2xl:divide-x-0 2xl:divide-y">
                    {topEvents.map((item, index) => (
                      <li
                        key={item.event_id}
                        className={`${index > 2 ? "hidden 2xl:block" : ""} md:px-4 md:first:pl-0 md:last:pr-0 2xl:px-0`}
                      >
                        <a
                          className="group/hotspot grid grid-cols-[28px_1fr_auto] items-start gap-2 py-2.5 text-sm md:py-3"
                          href={eventHref(item)}
                        >
                          <span className="readout pt-0.5 text-[10px] text-signal">0{index + 1}</span>
                          <span className="min-w-0 font-medium leading-5 text-ink transition-colors group-hover/hotspot:text-signal">
                            {item.title}
                          </span>
                          <ArrowUpRight
                            aria-hidden
                            className="mt-0.5 h-3.5 w-3.5 text-ink-dim transition-colors group-hover/hotspot:text-signal"
                            strokeWidth={1.6}
                          />
                          <span className="readout col-start-2 col-end-4 text-[10px] text-ink-dim">
                            {item.window_report_count ?? item.source_count ?? 1} 篇报道 ·{" "}
                            {item.window_source_count ?? item.source_count ?? 1} 个信源 ·{" "}
                            {formatRelativeTime(item.last_seen_at ?? item.published_at)}
                          </span>
                        </a>
                      </li>
                    ))}
                  </ol>
                </aside>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
