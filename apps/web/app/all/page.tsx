import type { LatestEvent } from "@/lib/api";
import { getAllEvents } from "@/lib/api";
import { searchEvents } from "@/lib/events";
import { CATEGORY_FILTER_OPTIONS, displayCategory } from "@/lib/taxonomy";
import { ChevronDown } from "lucide-react";
import { EventCard, EventTimelineRow } from "@/components/event-card";
import { MobileNav } from "@/components/mobile-nav";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";

type AllSearchParams = Promise<{
  source?: string | string[];
  category?: string | string[];
  q?: string | string[];
  topic?: string | string[];
}>;


const sourceOptions = [
  ["", "全部"],
  ["first_party", "一手信源"],
  ["news", "资讯"],
  ["community", "推文"],
] as const;

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
    month: "long",
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

// maps the source registry's real category (official/research/community/
// media, see apps/api/app/data/default_sources.py) to this page's three
// filter buckets, instead of guessing from the source display name - a name
// heuristic missed real community sources whose name doesn't literally say
// "reddit"/"x.com"/etc. (e.g. "X 推文 (AttentionVC)")
const SOURCE_CATEGORY_TO_BUCKET: Record<string, (typeof sourceOptions)[number][0]> = {
  official: "first_party",
  research: "first_party",
  community: "community",
  media: "news",
};

function sourceBucket(item: LatestEvent) {
  const category = item.main_source?.category;
  if (category && category in SOURCE_CATEGORY_TO_BUCKET) {
    return SOURCE_CATEGORY_TO_BUCKET[category];
  }
  return "news";
}

function sortByPublishedAtDesc(items: LatestEvent[]) {
  return [...items].sort((left, right) => {
    const leftTime = left.published_at ? new Date(left.published_at).getTime() : 0;
    const rightTime = right.published_at ? new Date(right.published_at).getTime() : 0;
    return rightTime - leftTime;
  });
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

function allHref({
  source,
  category,
  q,
}: {
  source?: string;
  category?: string;
  q?: string;
}) {
  const params = new URLSearchParams();
  if (source) {
    params.set("source", source);
  }
  if (category) {
    params.set("category", category);
  }
  if (q) {
    params.set("q", q);
  }
  const query = params.toString();
  return query ? `/all?${query}` : "/all";
}

function sourceLine(item: LatestEvent) {
  const source = item.main_source?.name ?? "未知来源";
  return `来源 · ${source}`;
}

function representativeImage(item: LatestEvent) {
  return item.original_images?.[0];
}

export default async function AllEventsPage({
  searchParams,
}: {
  searchParams: AllSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const selectedSource = firstQueryValue(resolvedSearchParams.source) ?? "";
  const selectedCategory = firstQueryValue(resolvedSearchParams.category) ?? "";
  const selectedTopic = firstQueryValue(resolvedSearchParams.topic)?.trim() ?? "";
  const query = firstQueryValue(resolvedSearchParams.q)?.trim() ?? "";
  const report = await getAllEvents(selectedTopic ? { topic: selectedTopic } : {});
  const searchedItems = searchEvents(report.items, query);
  const filteredItems = sortByPublishedAtDesc(
    searchedItems.filter((item) => {
      const sourceMatches = selectedSource ? sourceBucket(item) === selectedSource : true;
      const categoryMatches = selectedCategory
        ? displayCategory(item.category) === selectedCategory
        : true;
      return sourceMatches && categoryMatches;
    }),
  );
  const dateGroups = groupEventsByDate(filteredItems);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="all" />
        <MobileNav activeNavId="all" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <RadarStatus
              updatedAt={report.updated_at}
              eventCount={report.total}
              scope="ALL DYNAMICS · 30D"
            />
            <div className="mt-4 border-b border-line pb-4">
              <h1 className="text-2xl font-semibold text-ink">全部 AI 动态</h1>
              <p className="mt-1.5 text-sm text-ink-mid">AI 相关资讯全量信息流</p>
            </div>

            <div className="mt-4 grid gap-3 xl:grid-cols-[1fr_1fr_320px]">
              <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                {sourceOptions.map(([source, label]) => (
                  <a
                    key={source || "all-source"}
                    className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                      selectedSource === source
                        ? "bg-signal/15 text-signal"
                        : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                    }`}
                    href={allHref({ source, category: selectedCategory, q: query })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                {categoryOptions.map(([category, label]) => (
                  <a
                    key={category || "all-category"}
                    className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                      selectedCategory === category
                        ? "bg-signal/15 text-signal"
                        : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                    }`}
                    href={allHref({ source: selectedSource, category, q: query })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <form action="/all" className="grid grid-cols-[1fr_auto] gap-2">
                {selectedSource ? <input name="source" type="hidden" value={selectedSource} /> : null}
                {selectedCategory ? <input name="category" type="hidden" value={selectedCategory} /> : null}
                <input
                  className="min-h-10 min-w-0 rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要/正文..."
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

          {selectedTopic ? (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="rounded-full border border-signal/40 bg-signal/10 px-3 py-1.5 font-medium text-signal">
                主题筛选：{selectedTopic} · {report.total} 条
              </span>
              <a className="text-ink-mid hover:text-ink" href="/all">
                清除
              </a>
              <a className="text-ink-mid hover:text-ink" href="/topics">
                返回主题
              </a>
            </div>
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
                    <span className="text-ink-dim">{group.events.length} 条</span>
                  </summary>
                  <div className="relative grid gap-3 md:border-l md:border-line md:pl-6">
                    {group.events.map((item) => (
                      <EventTimelineRow key={item.event_id} time={formatTime(item.published_at)}>
                        <EventCard
                          item={item}
                          sourceLine={sourceLine(item)}
                          score={formatScore(item.final_score)}
                          image={representativeImage(item)}
                          tagHref={(tag) => allHref({ q: tag })}
                          maxTags={5}
                        />
                      </EventTimelineRow>
                    ))}
                  </div>
                </details>
              ))
            ) : (
              <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
                当前筛选条件下没有 AI 动态。
              </div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
