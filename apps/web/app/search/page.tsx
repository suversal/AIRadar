import { getLatestReport } from "@/lib/api";
import { eventHref, searchEvents } from "@/lib/events";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";

export const metadata = {
  title: "搜索",
  description: "在近 7 天精选内容里按标题、标签、来源或摘要检索。",
};

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
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="search" />
        <MobileNav activeNavId="search" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <h1 className="text-2xl font-semibold text-ink">搜索</h1>
            <p className="mt-1.5 text-sm text-ink-mid">在近 7 天精选内容里检索，更早的内容可去「全部 AI 动态」查找</p>

            <form className="mt-4 grid gap-3 md:grid-cols-[1fr_120px]" action="/search">
              <input
                className="min-h-11 rounded-md border border-line bg-canvas px-3 text-base text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
                type="search"
                name="q"
                defaultValue={query}
                placeholder="搜索标题、标签、来源或摘要"
              />
              <button
                className="min-h-11 rounded-md border border-signal/40 bg-signal/10 px-4 text-sm font-semibold text-signal transition hover:border-signal/60 hover:text-signal-bright"
                type="submit"
              >
                搜索
              </button>
            </form>
          </header>

          {report.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {report.error}
            </div>
          ) : null}

          <div className="mt-6 flex flex-col gap-2 border-b border-line pb-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-ink">搜索结果</h2>
              <p className="mt-2 text-sm text-ink-mid">
                {query.trim() ? `关键词：${query.trim()}` : "未输入关键词时，展示近 7 天全部精选内容。"}
              </p>
            </div>
            <div className="text-sm text-ink-mid">{results.length} 条</div>
          </div>

          <div className="divide-y divide-line border-b border-line">
            {results.length > 0 ? (
              results.map((item) => (
                <article key={item.event_id} className="grid gap-2 py-4 md:grid-cols-[1fr_180px]">
                  <div className="min-w-0">
                    <div className="text-xs text-signal-dim">
                      {item.category_label ?? item.category ?? "未分类"}
                    </div>
                    <h3 className="mt-1.5 text-base font-semibold leading-6 text-ink">
                      <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-ink-mid">
                      {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                    </p>
                  </div>
                  <div className="text-sm text-ink-mid md:text-right">
                    <div>评分 {formatScore(item.final_score)}</div>
                    <div className="mt-2">来源 {item.source_count ?? 1} 个</div>
                    <div className="mt-3">{(item.tags ?? []).join(" / ")}</div>
                  </div>
                </article>
              ))
            ) : (
              <p className="py-8 text-sm text-ink-mid">没有找到匹配的内容。</p>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
