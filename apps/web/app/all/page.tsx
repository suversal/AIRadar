import { getLatestReport } from "@/lib/api";
import { eventHref } from "@/lib/events";

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return score.toFixed(1);
}

export default async function AllEventsPage() {
  const report = await getLatestReport();

  return (
    <main className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <header className="border-b border-[var(--line)] bg-[var(--panel)]">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-[var(--muted)]">Suversal AI Radar</p>
            <h1 className="mt-2 text-3xl font-semibold">全部事件</h1>
          </div>
          <nav className="flex flex-wrap gap-3 text-sm text-[var(--accent)]" aria-label="页面导航">
            <a className="underline" href="/latest">
              最新情报
            </a>
            <a className="underline" href="/daily">
              日报
            </a>
            <a className="underline" href="/search">
              搜索
            </a>
          </nav>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-5 py-6">
        <div className="grid gap-3 border-b border-[var(--line)] pb-5 md:grid-cols-4">
          <div>
            <div className="text-2xl font-semibold">{report.items.length}</div>
            <div className="text-sm text-[var(--muted)]">当前可读事件</div>
          </div>
          <div>
            <div className="text-2xl font-semibold">
              {new Set(report.items.map((item) => item.category ?? "uncategorized")).size}
            </div>
            <div className="text-sm text-[var(--muted)]">分类</div>
          </div>
          <div>
            <div className="text-2xl font-semibold">
              {new Set(report.items.flatMap((item) => item.tags ?? [])).size}
            </div>
            <div className="text-sm text-[var(--muted)]">标签</div>
          </div>
          <div>
            <div className="text-sm text-[var(--muted)]">更新时间</div>
            <div className="mt-1 text-sm">{report.updated_at ?? "暂无日报"}</div>
          </div>
        </div>

        <div className="mt-6 divide-y divide-[var(--line)] border-y border-[var(--line)]">
          {report.items.map((item) => (
            <article key={item.event_id} className="grid gap-3 py-5 md:grid-cols-[1fr_180px]">
              <div>
                <div className="text-sm text-[var(--accent-strong)]">
                  {item.category_label ?? item.category ?? "未分类"}
                </div>
                <h2 className="mt-2 text-xl font-semibold">
                  <a href={eventHref(item)}>{item.title}</a>
                </h2>
                <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                  {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                </p>
              </div>
              <div className="text-sm text-[var(--muted)] md:text-right">
                <div>评分 {formatScore(item.final_score)}</div>
                <div className="mt-2">来源 {item.source_count ?? 1} 个</div>
                {item.main_source ? (
                  <a className="mt-3 inline-block text-[var(--accent)] underline" href={item.main_source.url}>
                    {item.main_source.name}
                  </a>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
