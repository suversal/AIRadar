import type { LatestEvent } from "@/lib/api";
import { getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { CATEGORY_FILTER_OPTIONS, displayCategory } from "@/lib/taxonomy";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";
import { RefreshReportButton } from "./refresh-report-button";

type LatestSearchParams = Promise<{
  category?: string | string[];
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


function categoryHref(category: string) {
  return category ? `/latest?category=${encodeURIComponent(category)}` : "/latest";
}

function sourceLine(item: LatestEvent) {
  const source = item.main_source?.name ?? "未知来源";
  return `${source} · ${item.source_count ?? 1} 个来源`;
}

function EventCard({ item }: { item: LatestEvent }) {
  return (
    <article className="card-hover rounded-md border border-line bg-panel p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm text-ink-mid">{sourceLine(item)}</div>
          <h3 className="mt-3 text-xl font-semibold leading-7 text-ink">
            <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full border border-signal/60 bg-signal/15 px-3 py-1 text-xs font-semibold text-signal-bright">
            精选
          </span>
          <span className="readout rounded-full border border-signal/40 px-3 py-1 text-xs font-semibold text-signal">
            {formatScore(item.final_score)}
          </span>
        </div>
      </div>

      <p className="mt-4 line-clamp-3 text-[15px] leading-7 text-ink-mid">
        {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
      </p>

      {item.tags?.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {item.tags.slice(0, 4).map((tag) => (
            <span key={tag} className="rounded-md bg-panel-soft px-3 py-1 text-xs text-ink-mid transition hover:bg-line hover:text-signal-bright">
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-5 border-t border-line pt-4">
        <p className="rounded-md bg-signal/10 px-4 py-3 text-[15px] leading-7 text-signal-bright">
          <span className="font-semibold">推荐理由：</span>
          {item.reason ?? "暂无推荐理由。"}
        </p>
      </div>
    </article>
  );
}

export default async function LatestPage({
  searchParams,
}: {
  searchParams: LatestSearchParams;
}) {
  const report = await getLatestReport();
  const resolvedSearchParams = await searchParams;
  const selectedCategory = firstQueryValue(resolvedSearchParams.category) ?? "";
  const filteredItems = selectedCategory
    ? report.items.filter((item) => displayCategory(item.category) === selectedCategory)
    : report.items;
  const topEvents = filteredItems.slice(0, 3);
  const dateGroups = groupEventsByDate(filteredItems);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="latest" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-6 shadow-[0_20px_80px_rgba(0,0,0,0.25)]">
            <RadarStatus
              updatedAt={report.updated_at}
              eventCount={report.items.length}
              scope="SELECTED FEED"
            />
            <div className="mt-5 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
              <div>
                <h1 className="text-3xl font-semibold text-ink">精选</h1>
                <p className="mt-2 text-sm text-ink-mid">AI 自动挑选的高价值内容</p>
              </div>
              <div className="text-sm text-ink-mid">更新时间：{formatDateTime(report.updated_at)}</div>
            </div>

            <div className="mt-6 flex flex-wrap gap-2 rounded-md border border-line bg-canvas p-2">
              {categoryOptions.map(([category, label]) => (
                <a
                  key={category || "all"}
                  className={`rounded-md px-5 py-2 text-sm font-semibold ${
                    selectedCategory === category
                      ? "bg-signal/15 text-signal"
                      : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                  }`}
                  href={categoryHref(category)}
                >
                  {label}
                </a>
              ))}
            </div>
          </header>

          {report.error ? (
            <div className="mt-5 rounded-md border border-red-400/40 bg-red-400/10 p-4 text-sm leading-6 text-red-200">
              {report.error}
            </div>
          ) : null}

          <section className="mt-5 rounded-md border border-line bg-panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-ink">当前热点</h2>
              <span className="text-sm text-ink-dim">多信源热度 · 随时间消退</span>
            </div>
            <div className="mt-4 grid gap-3">
              {topEvents.map((item, index) => (
                <a
                  key={item.event_id}
                  className="grid gap-2 rounded-md px-2 py-2 text-sm transition hover:bg-panel-soft/60 md:grid-cols-[32px_1fr_180px]"
                  href={eventHref(item)}
                >
                  <span className="font-semibold text-signal">{index + 1}</span>
                  <span className="font-semibold text-ink">{item.title}</span>
                  <span className="text-ink-dim md:text-right">
                    {item.source_count ?? 1} 个信源 · {formatScore(item.final_score)}
                  </span>
                </a>
              ))}
            </div>
          </section>

          <section className="mt-8">
            {dateGroups.length > 0 ? (
              dateGroups.map((group) => (
                <details key={group.dateLabel} open className="group">
                  <summary className="flex cursor-pointer list-none items-center gap-3 py-4 text-sm font-semibold text-ink-mid">
                    <span>{group.dateLabel}</span>
                    <span className="text-ink-dim">折叠</span>
                  </summary>
                  <div className="relative grid gap-4 border-l border-line pl-5 md:pl-8">
                    {group.events.map((item) => (
                      <div key={item.event_id} className="grid gap-3 md:grid-cols-[72px_1fr]">
                        <div className="readout relative text-2xl font-semibold text-ink">
                          <span className="absolute -left-[29px] top-2 h-3 w-3 rounded-full border border-signal bg-canvas md:-left-[41px]" />
                          {formatTime(item.published_at)}
                        </div>
                        <EventCard item={item} />
                      </div>
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
