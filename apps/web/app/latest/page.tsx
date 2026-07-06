import { getLatestReport } from "@/lib/api";

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return score.toFixed(1);
}

export default async function LatestPage() {
  const report = await getLatestReport();
  const topEvents = report.items.slice(0, 3);
  const remainingEvents = report.items.slice(3);

  return (
    <main className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <header className="border-b border-[var(--line)] bg-[var(--panel)]">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-[var(--muted)]">Suversal AI Radar</p>
            <h1 className="mt-2 text-3xl font-semibold">最新 AI 情报</h1>
          </div>
          <div className="text-sm text-[var(--muted)]">
            更新时间：{report.updated_at ?? "暂无日报"}
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-6 px-5 py-6 lg:grid-cols-[280px_1fr]">
        <aside className="border-b border-[var(--line)] pb-5 lg:border-b-0 lg:border-r lg:pr-5">
          <div className="grid grid-cols-3 gap-3 lg:grid-cols-1">
            <div>
              <div className="text-2xl font-semibold">{report.items.length}</div>
              <div className="text-sm text-[var(--muted)]">精选事件</div>
            </div>
            <div>
              <div className="text-2xl font-semibold">{topEvents.length}</div>
              <div className="text-sm text-[var(--muted)]">重点关注</div>
            </div>
            <div>
              <div className="text-2xl font-semibold">
                {new Set(report.items.flatMap((item) => item.tags ?? [])).size}
              </div>
              <div className="text-sm text-[var(--muted)]">标签信号</div>
            </div>
          </div>
        </aside>

        <div className="space-y-8">
          <section>
            <h2 className="text-lg font-semibold">Top 3</h2>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              {topEvents.map((item) => (
                <article
                  key={item.event_id}
                  className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4"
                >
                  <div className="text-sm text-[var(--accent)]">
                    {item.category_label ?? item.category ?? "未分类"} · {formatScore(item.final_score)}
                  </div>
                  <h3 className="mt-3 text-base font-semibold leading-6">{item.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                    {item.one_line_summary ?? item.summary}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section>
            <h2 className="text-lg font-semibold">全部精选</h2>
            <div className="mt-4 divide-y divide-[var(--line)] border-y border-[var(--line)]">
              {remainingEvents.map((item) => (
                <article key={item.event_id} className="grid gap-3 py-5 md:grid-cols-[1fr_160px]">
                  <div>
                    <div className="text-sm text-[var(--accent-strong)]">
                      {item.category_label ?? item.category ?? "未分类"}
                    </div>
                    <h3 className="mt-2 text-xl font-semibold">{item.title}</h3>
                    <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                      {item.summary ?? item.one_line_summary}
                    </p>
                    <p className="mt-3 text-sm leading-6">
                      <span className="font-semibold">推荐理由：</span>
                      {item.reason ?? "暂无推荐理由。"}
                    </p>
                    <p className="mt-2 text-sm leading-6">
                      <span className="font-semibold">下一步：</span>
                      {item.action ?? "阅读原文并评估是否跟进。"}
                    </p>
                  </div>
                  <div className="text-sm text-[var(--muted)] md:text-right">
                    <div>评分 {formatScore(item.final_score)}</div>
                    <div className="mt-2">来源 {item.source_count ?? 1} 个</div>
                    {item.main_source ? (
                      <a
                        className="mt-3 inline-block text-[var(--accent)] underline"
                        href={item.main_source.url}
                      >
                        {item.main_source.name}
                      </a>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
