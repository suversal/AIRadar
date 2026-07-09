import type { LatestEvent } from "@/lib/api";
import { getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { CATEGORY_FILTER_OPTIONS, displayCategory } from "@/lib/taxonomy";
import { RefreshReportButton } from "./refresh-report-button";

type LatestSearchParams = Promise<{
  category?: string | string[];
}>;

type SidebarItem = {
  id: string;
  label: string;
  group: "内容" | "接入" | "更多";
  href?: string;
  active?: boolean;
};

const sidebarItems: SidebarItem[] = [
  { id: "latest", label: "精选", group: "内容", href: "/latest", active: true },
  { id: "all", label: "全部 AI 动态", group: "内容", href: "/all" },
  { id: "daily", label: "AI 日报", group: "内容", href: "/daily" },
  { id: "topics", label: "主题", group: "内容" },
  { id: "bookmarks", label: "收藏", group: "内容" },
  { id: "agent", label: "Agent 接入", group: "接入" },
  { id: "about", label: "关于", group: "更多" },
  { id: "changelog", label: "更新日志", group: "更多" },
  { id: "feedback", label: "反馈", group: "更多" },
];

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

function menuGroupItems(group: SidebarItem["group"]) {
  return sidebarItems.filter((item) => item.group === group);
}

function sidebarMarker(label: string) {
  return label.slice(0, 1);
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
    <article className="rounded-md border border-slate-800 bg-slate-900/80 p-5 shadow-[0_18px_60px_rgba(0,0,0,0.22)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm text-slate-500">{sourceLine(item)}</div>
          <h3 className="mt-3 text-xl font-semibold leading-7 text-slate-100">
            <a href={eventHref(item)}>{item.title}</a>
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full border border-amber-500/40 px-3 py-1 text-xs font-semibold text-amber-300">
            精选
          </span>
          <span className="rounded-full border border-cyan-400/40 px-3 py-1 text-xs font-semibold text-cyan-300">
            {formatScore(item.final_score)}
          </span>
        </div>
      </div>

      <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-400">
        {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
      </p>

      {item.tags?.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {item.tags.slice(0, 4).map((tag) => (
            <span key={tag} className="rounded-md bg-slate-800 px-3 py-1 text-xs text-slate-400">
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-5 border-t border-slate-800 pt-4">
        <p className="rounded-md bg-emerald-400/10 px-4 py-3 text-sm leading-6 text-emerald-300">
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
    <main className="min-h-screen bg-[#070d1a] text-slate-100">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <aside className="border-b border-slate-800 bg-[#080d19] px-4 py-5 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
          <div className="rounded-md border border-slate-800 bg-slate-900/80 px-5 py-6">
            <div aria-label="AIHOT" className="text-2xl font-semibold tracking-[0.2em] text-slate-100">
              AI<span className="text-cyan-300">HOT</span>
            </div>
          </div>

          <nav className="mt-6 space-y-6" aria-label="主导航">
            {(["内容", "接入", "更多"] as const).map((group) => (
              <section key={group}>
                <div className="px-3 text-xs font-semibold text-slate-600">{group}</div>
                <div className="mt-2 space-y-1">
                  {menuGroupItems(group).map((item) => {
                    const className = `flex items-center gap-3 rounded-md px-4 py-3 text-sm font-semibold ${
                      item.active
                        ? "border border-cyan-400/40 bg-cyan-400/10 text-cyan-300"
                        : "text-slate-500 hover:text-slate-300"
                    }`;
                    const content = (
                      <>
                        <span className="flex h-6 w-6 items-center justify-center rounded-md border border-slate-700 text-xs">
                          {sidebarMarker(item.label)}
                        </span>
                        {item.label}
                      </>
                    );
                    return item.href ? (
                      <a
                        key={item.id}
                        aria-current={item.active ? "page" : undefined}
                        className={className}
                        href={item.href}
                      >
                        {content}
                      </a>
                    ) : (
                      <div key={item.id} aria-disabled="true" className={className}>
                        {content}
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </nav>

          <div className="mt-6">
            <RefreshReportButton />
          </div>

          <div className="mt-6 rounded-full border border-slate-800 bg-slate-900/80 p-1 text-xs text-slate-500">
            <div className="grid grid-cols-3 gap-1">
              <button className="rounded-full px-2 py-2" type="button">
                日间
              </button>
              <button className="rounded-full bg-slate-800 px-2 py-2 text-slate-300" type="button">
                跟随系统
              </button>
              <button className="rounded-full px-2 py-2" type="button">
                夜间
              </button>
            </div>
          </div>
        </aside>

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-slate-800 bg-slate-900/80 p-6 shadow-[0_20px_80px_rgba(0,0,0,0.25)]">
            <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
              <div>
                <h1 className="text-3xl font-semibold text-slate-100">精选</h1>
                <p className="mt-2 text-sm text-slate-500">AI 自动挑选的高价值内容</p>
              </div>
              <div className="text-sm text-slate-500">更新时间：{formatDateTime(report.updated_at)}</div>
            </div>

            <div className="mt-6 flex flex-wrap gap-2 rounded-md border border-slate-800 bg-[#0b1220] p-2">
              {categoryOptions.map(([category, label]) => (
                <a
                  key={category || "all"}
                  className={`rounded-md px-5 py-2 text-sm font-semibold ${
                    selectedCategory === category
                      ? "bg-cyan-400/20 text-cyan-300"
                      : "text-slate-500 hover:text-slate-300"
                  }`}
                  href={categoryHref(category)}
                >
                  {label}
                </a>
              ))}
            </div>
          </header>

          {report.error ? (
            <div className="mt-5 rounded-md border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-6 text-amber-200">
              {report.error}
            </div>
          ) : null}

          <section className="mt-5 rounded-md border border-slate-800 bg-slate-900/80 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-100">当前热点</h2>
              <span className="text-sm text-slate-600">多信源热度 · 随时间消退</span>
            </div>
            <div className="mt-4 grid gap-3">
              {topEvents.map((item, index) => (
                <a
                  key={item.event_id}
                  className="grid gap-2 rounded-md px-2 py-1 text-sm md:grid-cols-[32px_1fr_180px]"
                  href={eventHref(item)}
                >
                  <span className="font-semibold text-cyan-300">{index + 1}</span>
                  <span className="font-semibold text-slate-200">{item.title}</span>
                  <span className="text-slate-600 md:text-right">
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
                  <summary className="flex cursor-pointer list-none items-center gap-3 py-4 text-sm font-semibold text-slate-500">
                    <span>{group.dateLabel}</span>
                    <span className="text-slate-700">折叠</span>
                  </summary>
                  <div className="relative grid gap-4 border-l border-slate-800 pl-5 md:pl-8">
                    {group.events.map((item) => (
                      <div key={item.event_id} className="grid gap-3 md:grid-cols-[72px_1fr]">
                        <div className="relative text-2xl font-semibold text-slate-200">
                          <span className="absolute -left-[29px] top-2 h-3 w-3 rounded-full border border-cyan-300 bg-[#070d1a] md:-left-[41px]" />
                          {formatTime(item.published_at)}
                        </div>
                        <EventCard item={item} />
                      </div>
                    ))}
                  </div>
                </details>
              ))
            ) : (
              <div className="rounded-md border border-slate-800 bg-slate-900/80 p-8 text-sm text-slate-500">
                当前分类没有精选内容。
              </div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
