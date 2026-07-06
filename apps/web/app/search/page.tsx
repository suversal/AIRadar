import { getLatestReport } from "@/lib/api";
import { eventHref, searchEvents } from "@/lib/events";

type SearchParams = Promise<{
  q?: string | string[];
}>;

function firstQueryValue(value?: string | string[]) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return score.toFixed(1);
}

export default async function SearchPage({ searchParams }: { searchParams: SearchParams }) {
  const report = await getLatestReport();
  const resolvedSearchParams = await searchParams;
  const query = firstQueryValue(resolvedSearchParams.q) ?? "";
  const results = searchEvents(report.items, query);

  return (
    <main className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <header className="border-b border-[var(--line)] bg-[var(--panel)]">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-[var(--muted)]">Suversal AI Radar</p>
            <h1 className="mt-2 text-3xl font-semibold">搜索</h1>
          </div>
          <nav className="flex flex-wrap gap-3 text-sm text-[var(--accent)]" aria-label="页面导航">
            <a className="underline" href="/latest">
              最新情报
            </a>
            <a className="underline" href="/all">
              全部事件
            </a>
            <a className="underline" href="/daily">
              日报
            </a>
          </nav>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-5 py-6">
        <form className="grid gap-3 border-b border-[var(--line)] pb-5 md:grid-cols-[1fr_120px]" action="/search">
          <input
            className="min-h-11 rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 text-base"
            type="search"
            name="q"
            defaultValue={query}
            placeholder="搜索标题、标签、来源或摘要"
          />
          <button
            className="min-h-11 rounded-md border border-[var(--accent)] bg-[var(--accent)] px-4 text-sm font-semibold text-white"
            type="submit"
          >
            搜索
          </button>
        </form>

        <div className="mt-6 flex flex-col gap-2 border-b border-[var(--line)] pb-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-xl font-semibold">搜索结果</h2>
            <p className="mt-2 text-sm text-[var(--muted)]">
              {query.trim() ? `关键词：${query.trim()}` : "未输入关键词时展示全部当前事件。"}
            </p>
          </div>
          <div className="text-sm text-[var(--muted)]">{results.length} 条</div>
        </div>

        <div className="divide-y divide-[var(--line)] border-b border-[var(--line)]">
          {results.length > 0 ? (
            results.map((item) => (
              <article key={item.event_id} className="grid gap-3 py-5 md:grid-cols-[1fr_180px]">
                <div>
                  <div className="text-sm text-[var(--accent-strong)]">
                    {item.category_label ?? item.category ?? "未分类"}
                  </div>
                  <h3 className="mt-2 text-xl font-semibold">
                    <a href={eventHref(item)}>{item.title}</a>
                  </h3>
                  <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                    {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                  </p>
                </div>
                <div className="text-sm text-[var(--muted)] md:text-right">
                  <div>评分 {formatScore(item.final_score)}</div>
                  <div className="mt-2">来源 {item.source_count ?? 1} 个</div>
                  <div className="mt-3">{(item.tags ?? []).join(" / ")}</div>
                </div>
              </article>
            ))
          ) : (
            <p className="py-8 text-sm text-[var(--muted)]">没有匹配的事件。</p>
          )}
        </div>
      </section>
    </main>
  );
}
