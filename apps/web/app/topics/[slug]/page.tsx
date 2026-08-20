import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTopicDetail } from "@/lib/api";
import { formatDateKey, formatTime, groupEventsByDate } from "@/lib/event-format";
import { eventHref, formatScore } from "@/lib/events";
import { topicLabel } from "@/lib/topics";
import { DateGroupSection } from "@/components/date-group-section";
import { EventCard, EventTimelineRow } from "@/components/event-card";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";

/** 同 /topics:内容全部来自后端 API,构建期 API 不可达,预渲染会把降级
 *  文案烤进静态 HTML(2026-08-13 真踩过,见 app/topics/page.tsx 的注释)。
 *  HTML 靠 nginx 缓存、取数靠 lib/api.ts 的 cacheFor,性能不受影响。 */
export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  // 同一 URL 的 fetch 在一次渲染里会被 Next 去重,不会真的打两次 API
  const payload = await getTopicDetail(slug);
  if (!payload) {
    return { title: "主题" };
  }
  const name = payload.topic.name || topicLabel(slug);
  return {
    title: `${name} 最新动态与精选`,
    description: payload.topic.description || `${name} 的 AI 动态持续追踪。`,
    // 旧 id(如 claude)会被后端重定向到合并后的主题,canonical 指向新 id
    alternates: { canonical: `/topics/${payload.topic.id || slug}` },
  };
}

export default async function TopicDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const payload = await getTopicDetail(slug);
  if (!payload) {
    notFound();
  }
  const { topic } = payload;
  const allHref = `/all?topic=${encodeURIComponent(topic.id || slug)}`;
  const dateGroups = groupEventsByDate(payload.items);
  const shownCount = payload.offset + payload.items.length;

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="topics" />
        <MobileNav activeNavId="topics" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <nav className="text-xs text-ink-dim">
              <a className="hover:text-signal" href="/topics">
                主题
              </a>
              {topic.group_name ? <span> / {topic.group_name}</span> : null}
            </nav>
            <h1 className="mt-2 text-2xl font-semibold text-ink">{topic.name}</h1>
            {topic.description ? (
              <p className="mt-1.5 text-sm leading-6 text-ink-mid">{topic.description}</p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-mid">
              <span className="tabular-nums">
                近 {payload.window_days} 天收录 {payload.total_count} 条
              </span>
              <span className="tabular-nums">精选 {payload.selected_count} 条</span>
              {payload.latest_published_at ? (
                <span>最近更新 {payload.latest_published_at}</span>
              ) : null}
              <a className="text-ink-mid underline-offset-2 hover:text-signal hover:underline" href={allHref}>
                在全部动态中筛选 →
              </a>
            </div>
          </header>

          {payload.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {payload.error}
            </div>
          ) : null}

          {payload.focus.length > 0 ? (
            <section className="mt-4 rounded-md border border-line bg-panel p-5">
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-base font-semibold text-ink">近期焦点</h2>
                <span className="text-xs text-ink-dim">
                  近 {payload.focus_window_days} 天 · 按多源报道热度
                </span>
              </div>
              <ol className="mt-3 space-y-2.5">
                {payload.focus.map((item, index) => (
                  <li key={item.event_id} className="flex items-baseline gap-3">
                    <span className="readout w-4 shrink-0 text-sm font-semibold text-signal">
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <a className="title-link text-sm font-medium leading-6 text-ink" href={eventHref(item)}>
                        {item.title}
                      </a>
                      <span className="ml-2 whitespace-nowrap text-xs tabular-nums text-ink-dim">
                        {item.source_count ?? 1} 家信源 · {formatDateKey(item.published_at)}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          <section className="mt-3 md:mt-6">
            {dateGroups.map((group) => (
              <DateGroupSection
                key={group.dateLabel}
                dateLabel={group.dateLabel}
                weekday={group.weekday}
                count={group.events.length}
              >
                {group.events.map((item) => (
                  <EventTimelineRow key={item.event_id} time={formatTime(item.published_at)}>
                    <EventCard
                      item={item}
                      score={formatScore(item.final_score)}
                      image={item.original_images?.[0]}
                      tagHref={(tag) => `/all?${new URLSearchParams({ tag })}`}
                      maxTags={4}
                      clampSummary
                    />
                  </EventTimelineRow>
                ))}
              </DateGroupSection>
            ))}
            {payload.items.length === 0 && !payload.error ? (
              <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
                这个主题最近 {payload.window_days} 天还没有精选内容。
                <a className="ml-1 text-signal hover:text-signal-bright" href={allHref}>
                  去全部动态看看收录 →
                </a>
              </div>
            ) : null}
          </section>

          {payload.selected_count > shownCount || payload.total_count > payload.selected_count ? (
            <div className="mt-6 rounded-md border border-line bg-panel p-4 text-sm text-ink-mid">
              {payload.selected_count > shownCount
                ? `还有 ${payload.selected_count - shownCount} 条更早的精选,`
                : `另有 ${payload.total_count - payload.selected_count} 条未进精选的收录,`}
              <a className="text-signal hover:text-signal-bright" href={allHref}>
                在全部动态中继续看 →
              </a>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
