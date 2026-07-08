import type { LatestEvent } from "@/lib/api";
import { getLatestReport } from "@/lib/api";
import { eventHref, searchEvents } from "@/lib/events";

type AllSearchParams = Promise<{
  source?: string | string[];
  category?: string | string[];
  q?: string | string[];
}>;

type NavItem = {
  id: string;
  label: string;
  group: "内容" | "接入" | "更多";
  href?: string;
};

const navItems: NavItem[] = [
  { id: "latest", label: "精选", group: "内容", href: "/latest" },
  { id: "all", label: "全部 AI 动态", group: "内容", href: "/all" },
  { id: "daily", label: "AI 日报", group: "内容", href: "/daily" },
  { id: "topics", label: "主题", group: "内容" },
  { id: "bookmarks", label: "收藏", group: "内容" },
  { id: "agent", label: "Agent 接入", group: "接入" },
  { id: "about", label: "关于", group: "更多" },
  { id: "changelog", label: "更新日志", group: "更多" },
  { id: "feedback", label: "反馈", group: "更多" },
];

const sourceOptions = [
  ["", "全部"],
  ["first_party", "一手信源"],
  ["news", "资讯"],
  ["community", "推文"],
] as const;

const categoryOptions = [
  ["", "全部"],
  ["model_release", "模型"],
  ["product_release", "产品"],
  ["industry", "行业"],
  ["research", "论文"],
  ["tutorial", "技巧"],
] as const;

function firstQueryValue(value?: string | string[]) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function navGroupItems(group: NavItem["group"]) {
  return navItems.filter((item) => item.group === group);
}

function navMarker(label: string) {
  return label.slice(0, 1);
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

function sourceBucket(item: LatestEvent) {
  const sourceName = (item.main_source?.name ?? "").toLowerCase();
  if (
    sourceName.includes("openai") ||
    sourceName.includes("anthropic") ||
    sourceName.includes("deepmind") ||
    sourceName.includes("hugging face") ||
    sourceName.includes("arxiv") ||
    sourceName.includes("github")
  ) {
    return "first_party";
  }
  if (
    sourceName.includes("reddit") ||
    sourceName.includes("hacker news") ||
    sourceName.includes("x.com") ||
    sourceName.includes("twitter")
  ) {
    return "community";
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

function AllEventCard({ item }: { item: LatestEvent }) {
  const image = representativeImage(item);
  const score = formatScore(item.final_score);

  return (
    <article className="rounded-md border border-slate-800 bg-slate-900/80 p-5 shadow-[0_18px_60px_rgba(0,0,0,0.22)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-xs font-semibold text-cyan-300">
            {navMarker(item.main_source?.name ?? "AI")}
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm text-slate-500">{sourceLine(item)}</div>
            <h2 className="mt-3 text-xl font-semibold leading-8 text-slate-100">
              <a href={eventHref(item)}>{item.title}</a>
            </h2>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {typeof item.final_score === "number" && item.final_score >= 65 ? (
            <span className="rounded-full border border-amber-500/40 px-3 py-1 text-xs font-semibold text-amber-300">
              精选
            </span>
          ) : null}
          <span className="rounded-full border border-cyan-400/40 px-3 py-1 text-xs font-semibold text-cyan-300">
            评分 {score}
          </span>
        </div>
      </div>

      <p className="mt-4 text-sm leading-6 text-slate-400">
        {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
      </p>

      {image ? (
        <img
          alt={image.alt ?? item.title}
          className="mt-4 max-h-72 w-full max-w-xl rounded-md border border-slate-800 object-cover"
          src={image.url}
        />
      ) : null}

      {item.tags?.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {item.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="rounded-md bg-slate-800 px-3 py-1 text-xs text-slate-400">
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      {item.reason ? (
        <div className="mt-5 border-t border-slate-800 pt-4">
          <p className="rounded-md bg-emerald-400/10 px-4 py-3 text-sm leading-6 text-emerald-300">
            <span className="font-semibold">推荐理由：</span>
            {item.reason}
          </p>
        </div>
      ) : null}
    </article>
  );
}

export default async function AllEventsPage({
  searchParams,
}: {
  searchParams: AllSearchParams;
}) {
  const report = await getLatestReport();
  const resolvedSearchParams = await searchParams;
  const selectedSource = firstQueryValue(resolvedSearchParams.source) ?? "";
  const selectedCategory = firstQueryValue(resolvedSearchParams.category) ?? "";
  const query = firstQueryValue(resolvedSearchParams.q)?.trim() ?? "";
  const activeNavId = "all";
  const searchedItems = searchEvents(report.items, query);
  const filteredItems = sortByPublishedAtDesc(
    searchedItems.filter((item) => {
      const sourceMatches = selectedSource ? sourceBucket(item) === selectedSource : true;
      const categoryMatches = selectedCategory
        ? (item.category ?? "uncategorized") === selectedCategory
        : true;
      return sourceMatches && categoryMatches;
    }),
  );
  const dateGroups = groupEventsByDate(filteredItems);

  return (
    <main className="min-h-screen bg-[#070d1a] text-slate-100">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <aside className="border-b border-slate-800 bg-[#080d19] px-4 py-5 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
          <a className="block rounded-md border border-slate-800 bg-slate-900/80 px-5 py-6" href="/latest">
            <div aria-label="AIHOT" className="text-2xl font-semibold tracking-[0.2em] text-slate-100">
              AI<span className="text-cyan-300">HOT</span>
            </div>
          </a>

          <nav className="mt-6 space-y-6" aria-label="主导航">
            {(["内容", "接入", "更多"] as const).map((group) => (
              <section key={group}>
                <div className="px-3 text-xs font-semibold text-slate-600">{group}</div>
                <div className="mt-2 space-y-1">
                  {navGroupItems(group).map((item) => {
                    const active = item.id === activeNavId;
                    const className = `flex items-center gap-3 rounded-md px-4 py-3 text-sm font-semibold ${
                      active
                        ? "border border-cyan-400/40 bg-cyan-400/10 text-cyan-300"
                        : "text-slate-500 hover:text-slate-300"
                    }`;
                    const content = (
                      <>
                        <span className="flex h-6 w-6 items-center justify-center rounded-md border border-slate-700 text-xs">
                          {navMarker(item.label)}
                        </span>
                        {item.label}
                      </>
                    );
                    return item.href ? (
                      <a
                        key={item.id}
                        aria-current={active ? "page" : undefined}
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
            <div className="border-b border-slate-800 pb-5">
              <h1 className="text-3xl font-semibold text-slate-100">全部 AI 动态</h1>
              <p className="mt-2 text-sm text-slate-500">AI 相关资讯全量信息流</p>
            </div>

            <div className="mt-5 grid gap-4 xl:grid-cols-[1fr_1fr_320px]">
              <div className="flex flex-wrap gap-2 rounded-md border border-slate-800 bg-[#0b1220] p-2">
                {sourceOptions.map(([source, label]) => (
                  <a
                    key={source || "all-source"}
                    className={`rounded-md px-5 py-2 text-sm font-semibold ${
                      selectedSource === source
                        ? "bg-cyan-400/20 text-cyan-300"
                        : "text-slate-500 hover:text-slate-300"
                    }`}
                    href={allHref({ source, category: selectedCategory, q: query })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <div className="flex flex-wrap gap-2 rounded-md border border-slate-800 bg-[#0b1220] p-2">
                {categoryOptions.map(([category, label]) => (
                  <a
                    key={category || "all-category"}
                    className={`rounded-md px-5 py-2 text-sm font-semibold ${
                      selectedCategory === category
                        ? "bg-cyan-400/20 text-cyan-300"
                        : "text-slate-500 hover:text-slate-300"
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
                  className="min-w-0 rounded-md border border-slate-800 bg-[#0b1220] px-4 py-3 text-sm text-slate-200 outline-none placeholder:text-slate-600 focus:border-cyan-400/60"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要/正文..."
                  type="search"
                />
                <button
                  className="rounded-md border border-cyan-400/40 bg-cyan-400/10 px-5 py-3 text-sm font-semibold text-cyan-300"
                  type="submit"
                >
                  搜索
                </button>
              </form>
            </div>
          </header>

          {report.error ? (
            <div className="mt-5 rounded-md border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-6 text-amber-200">
              {report.error}
            </div>
          ) : null}

          <section className="mt-8">
            {dateGroups.length > 0 ? (
              dateGroups.map((group) => (
                <details key={group.dateLabel} open className="group">
                  <summary className="flex cursor-pointer list-none items-center gap-3 py-4 text-sm font-semibold text-slate-500">
                    <span>{group.dateLabel}</span>
                    <span className="text-slate-700">折叠</span>
                    <span className="text-slate-700">{group.events.length} 条</span>
                  </summary>
                  <div className="relative grid gap-4 border-l border-slate-800 pl-5 md:pl-8">
                    {group.events.map((item) => (
                      <div key={item.event_id} className="grid gap-3 md:grid-cols-[72px_1fr]">
                        <div className="relative text-2xl font-semibold text-slate-200">
                          <span className="absolute -left-[29px] top-2 h-3 w-3 rounded-full border border-emerald-400 bg-[#070d1a] md:-left-[41px]" />
                          {formatTime(item.published_at)}
                        </div>
                        <AllEventCard item={item} />
                      </div>
                    ))}
                  </div>
                </details>
              ))
            ) : (
              <div className="rounded-md border border-slate-800 bg-slate-900/80 p-8 text-sm text-slate-500">
                当前筛选条件下没有 AI 动态。
              </div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
