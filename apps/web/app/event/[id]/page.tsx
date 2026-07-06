import { notFound } from "next/navigation";
import { getLatestReport } from "@/lib/api";
import { findEventById } from "@/lib/events";

type EventParams = Promise<{
  id: string;
}>;

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return score.toFixed(1);
}

export default async function EventDetailPage({ params }: { params: EventParams }) {
  const { id } = await params;
  const report = await getLatestReport();
  const event = findEventById(report.items, id);

  if (!event) {
    notFound();
  }

  return (
    <main className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
      <header className="border-b border-[var(--line)] bg-[var(--panel)]">
        <div className="mx-auto flex max-w-5xl flex-col gap-4 px-5 py-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm text-[var(--muted)]">Suversal AI Radar</p>
            <h1 className="mt-2 text-3xl font-semibold">{event.title}</h1>
          </div>
          <a className="text-sm text-[var(--accent)] underline" href="/latest">
            返回最新情报
          </a>
        </div>
      </header>

      <section className="mx-auto grid max-w-5xl gap-6 px-5 py-6 lg:grid-cols-[280px_1fr]">
        <aside className="border-b border-[var(--line)] pb-5 lg:border-b-0 lg:border-r lg:pr-5">
          <div className="text-sm text-[var(--accent-strong)]">
            {event.category_label ?? event.category ?? "未分类"}
          </div>
          <div className="mt-3 text-3xl font-semibold">{formatScore(event.final_score)}</div>
          <div className="text-sm text-[var(--muted)]">综合评分</div>

          <div className="mt-6 space-y-4 text-sm">
            <div>
              <div className="font-semibold">主来源</div>
              {event.main_source ? (
                <a className="mt-2 inline-block text-[var(--accent)] underline" href={event.main_source.url}>
                  {event.main_source.name}
                </a>
              ) : (
                <p className="mt-2 text-[var(--muted)]">暂无主来源。</p>
              )}
            </div>
            <div>
              <div className="font-semibold">相关来源</div>
              <p className="mt-2 text-[var(--muted)]">{event.source_count ?? 1} 个来源参与该事件聚合。</p>
            </div>
            <div>
              <div className="font-semibold">标签</div>
              <p className="mt-2 text-[var(--muted)]">{(event.tags ?? []).join(" / ") || "暂无标签"}</p>
            </div>
          </div>
        </aside>

        <div className="space-y-8">
          <section className="border-b border-[var(--line)] pb-5">
            <h2 className="text-xl font-semibold">摘要</h2>
            <p className="mt-3 text-base leading-7 text-[var(--muted)]">
              {event.summary ?? event.one_line_summary ?? "暂无摘要。"}
            </p>
          </section>

          <section className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4">
              <h2 className="text-lg font-semibold">推荐理由</h2>
              <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                {event.reason ?? "暂无推荐理由。"}
              </p>
            </div>
            <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4">
              <h2 className="text-lg font-semibold">下一步</h2>
              <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                {event.action ?? "阅读原文并评估是否跟进。"}
              </p>
            </div>
          </section>

          <section>
            <h2 className="text-xl font-semibold">时间线</h2>
            <div className="mt-4 divide-y divide-[var(--line)] border-y border-[var(--line)]">
              <div className="grid gap-2 py-4 md:grid-cols-[160px_1fr]">
                <div className="text-sm font-semibold">发布时间</div>
                <div className="text-sm text-[var(--muted)]">{event.published_at ?? "暂无发布时间"}</div>
              </div>
              <div className="grid gap-2 py-4 md:grid-cols-[160px_1fr]">
                <div className="text-sm font-semibold">收录日报</div>
                <div className="text-sm text-[var(--muted)]">{report.report_date ?? report.updated_at ?? "暂无日报"}</div>
              </div>
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
