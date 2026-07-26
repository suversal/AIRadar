import { getHotspots, getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { FOCUS_FILTER_OPTIONS, focusCategory } from "@/lib/taxonomy";
import { formatRelativeTime } from "@/lib/time";
import { LatestEventsFeed } from "@/components/latest-events-feed";
import { MobileNav } from "@/components/mobile-nav";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";

type LatestSearchParams = Promise<{
  focus?: string | string[];
  category?: string | string[];
  q?: string | string[];
  tag?: string | string[];
}>;

const PAGE_SIZE = 50;
const HOTSPOT_LIMIT = 3;

const categoryOptions = FOCUS_FILTER_OPTIONS;

function firstQueryValue(value?: string | string[]) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
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
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="latest" />
        <MobileNav activeNavId="latest" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <RadarStatus
              updatedAt={report.updated_at}
              eventCount={report.total ?? report.items.length}
              scope="SELECTED FEED · 7D"
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
                    href={latestHref({ focus: category, tag: selectedTag, q: query })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <form action="/latest" className="grid grid-cols-[1fr_auto] gap-2">
                {selectedCategory ? <input name="focus" type="hidden" value={selectedCategory} /> : null}
                {selectedTag ? <input name="tag" type="hidden" value={selectedTag} /> : null}
                <input
                  className="min-h-10 min-w-0 rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要..."
                  type="search"
                />
                <button
                  className="min-h-10 rounded-md border border-signal/40 bg-signal/10 px-4 py-2 text-sm font-medium text-signal transition hover:border-signal/60 hover:text-signal-bright"
                  type="submit"
                >
                  搜索
                </button>
              </form>
            </div>
          </header>

          {report.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {report.error}
            </div>
          ) : null}

          {selectedTag ? (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="rounded-full border border-signal/40 bg-signal/10 px-3 py-1.5 font-medium text-signal">
                标签筛选：{selectedTag} · {report.total ?? report.items.length} 条
              </span>
              <a
                className="text-ink-mid hover:text-ink"
                href={latestHref({ focus: selectedCategory, q: query })}
              >
                清除
              </a>
            </div>
          ) : null}

          {topEvents.length > 0 ? (
            <section className="mt-4 rounded-md border border-signal/25 bg-panel p-4">
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

          <LatestEventsFeed
            initialItems={report.items}
            initialTotal={report.total ?? report.items.length}
            tag={selectedTag}
            selectedCategory={selectedCategory}
            query={query}
          />
        </section>
      </div>
    </main>
  );
}
