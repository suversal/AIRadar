import type { LatestEvent } from "@/lib/api";
import { getHotspots, getLatestReport } from "@/lib/api";
import { eventHref, searchEvents } from "@/lib/events";
import { CATEGORY_FILTER_OPTIONS, displayCategory } from "@/lib/taxonomy";
import { formatRelativeTime } from "@/lib/time";
import { ChevronDown } from "lucide-react";
import { EventCard, EventTimelineRow } from "@/components/event-card";
import { MobileNav } from "@/components/mobile-nav";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";

type LatestSearchParams = Promise<{
  category?: string | string[];
  q?: string | string[];
}>;


const categoryOptions = CATEGORY_FILTER_OPTIONS;

function firstQueryValue(value?: string | string[]) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "--";
  }
  return Math.round(score).toString();
}

function formatDateKey(value?: string) {
  if (!value) {
    return "日期未知";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 10) || "日期未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(parsed);
}

function formatTime(value?: string) {
  if (!value) {
    return "--:--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "暂无日报";
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

function groupEventsByDate(items: LatestEvent[]) {
  const groups = new Map<string, LatestEvent[]>();
  for (const item of items) {
    const key = formatDateKey(item.published_at);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return Array.from(groups.entries()).map(([dateLabel, events]) => ({
    dateLabel,
    events,
  }));
}


function latestHref({ category, q }: { category?: string; q?: string }) {
  const params = new URLSearchParams();
  if (category) {
    params.set("category", category);
  }
  if (q) {
    params.set("q", q);
  }
  const query = params.toString();
  return query ? `/latest?${query}` : "/latest";
}

function sourceLine(item: LatestEvent) {
  const source = item.main_source?.name ?? "未知来源";
  return `${source} · ${item.source_count ?? 1} 个来源`;
}

export default async function LatestPage({
  searchParams,
}: {
  searchParams: LatestSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const selectedCategory = firstQueryValue(resolvedSearchParams.category) ?? "";
  const query = firstQueryValue(resolvedSearchParams.q)?.trim() ?? "";
  const [report, hotspots] = await Promise.all([
    getLatestReport(),
    getHotspots({ category: selectedCategory, q: query }),
  ]);
  const searchedItems = searchEvents(report.items, query);
  const filteredItems = selectedCategory
    ? searchedItems.filter((item) => displayCategory(item.category) === selectedCategory)
    : searchedItems;
  const topEvents = hotspots.items;
  const dateGroups = groupEventsByDate(filteredItems);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="latest" />
        <MobileNav activeNavId="latest" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <RadarStatus
              updatedAt={report.updated_at}
              eventCount={filteredItems.length}
              scope="SELECTED FEED"
            />
            <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-ink">精选</h1>
                <p className="mt-1.5 text-sm text-ink-mid">AI 自动挑选的高价值内容</p>
              </div>
              <div className="text-sm text-ink-mid">更新时间：{formatDateTime(report.updated_at)}</div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_320px]">
              <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                {categoryOptions.map(([category, label]) => (
                  <a
                    key={category || "all"}
                    className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                      selectedCategory === category
                        ? "bg-signal/15 text-signal"
                        : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                    }`}
                    href={latestHref({ category, q: query })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <form action="/latest" className="grid grid-cols-[1fr_auto] gap-2">
                {selectedCategory ? <input name="category" type="hidden" value={selectedCategory} /> : null}
                <input
                  className="min-h-10 min-w-0 rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要..."
                  type="search"
                />
                <button
                  className="min-h-10 rounded-md border border-signal/40 bg-signal/10 px-4 py-2 text-sm font-medium text-signal"
                  type="submit"
                >
                  搜索
                </button>
              </form>
            </div>
          </header>

          {report.error ? (
            <div className="mt-4 rounded-md border border-red-400/40 bg-red-400/10 p-4 text-sm leading-6 text-red-200">
              {report.error}
            </div>
          ) : null}

          {topEvents.length > 0 ? (
            <section className="mt-4 rounded-md border border-signal/25 bg-gradient-to-br from-signal/10 via-panel to-panel p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
                  <span aria-hidden>🔥</span>
                  当前热点
                </h2>
                <span className="text-xs text-ink-dim">近48小时 · 按热度与评分</span>
              </div>
              <div className="mt-3 grid gap-1">
                {topEvents.map((item, index) => (
                  <a
                    key={item.event_id}
                    className="flex items-start gap-2 rounded-md px-2 py-2 text-sm transition hover:bg-panel-soft/60 md:grid md:grid-cols-[32px_1fr_180px] md:items-center md:gap-2 md:py-1.5"
                    href={eventHref(item)}
                  >
                    <span className="shrink-0 font-semibold text-signal">{index + 1}</span>
                    <span className="min-w-0 flex-1 md:contents">
                      <span className="font-semibold text-ink">{item.title}</span>
                      <span className="mt-0.5 block text-ink-dim md:mt-0 md:text-right">
                        {item.source_count ?? 1} 个信源 ·{" "}
                        {formatRelativeTime(item.last_seen_at ?? item.published_at)}
                      </span>
                    </span>
                  </a>
                ))}
              </div>
            </section>
          ) : null}

          <section className="mt-6">
            {dateGroups.length > 0 ? (
              dateGroups.map((group) => (
                <details key={group.dateLabel} open className="group">
                  <summary className="flex cursor-pointer list-none items-center gap-3 py-3 text-sm font-semibold text-ink-mid">
                    <span>{group.dateLabel}</span>
                    <span className="flex items-center gap-1 text-ink-dim">
                      折叠
                      <ChevronDown
                        aria-hidden
                        className="h-4 w-4 -rotate-90 transition-transform group-open:rotate-0"
                        strokeWidth={2}
                      />
                    </span>
                  </summary>
                  <div className="relative grid gap-3 md:border-l md:border-line md:pl-6">
                    {group.events.map((item) => (
                      <EventTimelineRow key={item.event_id} time={formatTime(item.published_at)}>
                        <EventCard
                          item={item}
                          sourceLine={sourceLine(item)}
                          score={formatScore(item.final_score)}
                          tagHref={(tag) => latestHref({ q: tag })}
                          maxTags={4}
                          clampSummary
                          alwaysSelected
                        />
                      </EventTimelineRow>
                    ))}
                  </div>
                </details>
              ))
            ) : (
              <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
                当前分类没有精选内容。
              </div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
