import { notFound } from "next/navigation";
import { ExternalLink } from "lucide-react";
import type { LatestEvent, OriginalBlock } from "@/lib/api";
import { getEventDetail, getLatestReport } from "@/lib/api";
import { findEventById } from "@/lib/events";
import { formatRelativeTime } from "@/lib/time";
import { ArticleReadingToggle } from "./article-reading-toggle";
import { renderOriginalBlock } from "@/components/original-block";
import { BookmarkButton } from "@/components/bookmark-button";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";
import { adminFetch } from "@/lib/admin-api";

type EventParams = Promise<{
  id: string;
}>;

type EventSearchParams = Promise<{
  admin_preview?: string;
}>;

// 详情页是站外分享与搜索收录的落地页，metadata 必须带上文章自己的标题与摘要
export async function generateMetadata({ params }: { params: EventParams }) {
  const { id } = await params;
  const event = await getEventDetail(id);
  if (!event) {
    return { title: "内容详情" };
  }
  const description = (event.summary ?? event.one_line_summary ?? "").slice(0, 120) || undefined;
  return { title: event.title, description };
}

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return Math.round(score).toString();
}

function formatDateTime(value?: string, _contentOrigin?: string, timeBasis?: string) {
  if (!value) {
    return "发布时间未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const formatted = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  // SourcePilot 契约: time_basis="discovered" 的条目只有收录时间,
  // 不得伪称原文发布时间
  return timeBasis === "discovered" ? `收录于 ${formatted}` : formatted;
}

function hostFromUrl(value?: string) {
  if (!value) {
    return "";
  }
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function tagHref(tag: string) {
  return `/all?${new URLSearchParams({ tag })}`;
}

function originalBlocksFor(event: LatestEvent): OriginalBlock[] {
  // known unscrapable read-original domain (e.g. WeChat) - the backend
  // deliberately withheld original_*, so don't synthesize a fake 原文 block
  // from the AI summary (which is already shown in its own section above)
  if (event.content_origin === "aihot_item_page_link_only") {
    return [];
  }
  if (event.original_blocks?.length) {
    return event.original_blocks;
  }
  if (event.original_paragraphs?.length) {
    return event.original_paragraphs.map((paragraph) => ({
      type: "paragraph",
      text: paragraph,
    }));
  }
  if (event.original_content) {
    return [{ type: "paragraph", text: event.original_content }];
  }
  if (event.original_images?.length) {
    return event.original_images.map((image) => ({
      type: "image",
      url: image.url,
      alt: image.alt,
      caption: image.caption,
    }));
  }
  return [
    {
      type: "paragraph",
      text: event.summary ?? event.one_line_summary ?? "暂无可展示的原文正文。",
    },
  ];
}

function translatedBlocksFor(event: LatestEvent): OriginalBlock[] {
  if (event.translated_blocks?.length) {
    return event.translated_blocks;
  }
  if (event.translated_paragraphs?.length) {
    return event.translated_paragraphs.map((paragraph) => ({
      type: "paragraph",
      text: paragraph,
    }));
  }
  if (event.translated_content) {
    return [{ type: "paragraph", text: event.translated_content }];
  }
  return [];
}

export default async function EventDetailPage({
  params,
  searchParams,
}: {
  params: EventParams;
  searchParams: EventSearchParams;
}) {
  const { id } = await params;
  const { admin_preview: adminPreview } = await searchParams;
  let adminEvent: LatestEvent | null = null;
  if (adminPreview === "1") {
    const response = await adminFetch(
      `/api/admin/events/${encodeURIComponent(id)}`,
    );
    if (response.ok) {
      adminEvent = (await response.json()) as LatestEvent;
    }
  }
  const report = await getLatestReport();
  // getEventDetail is the only path that resolves full article content and
  // per-source coverage (report.items is a lightweight list-view payload) -
  // it must win whenever it resolves; the list match is just a fallback for
  // when there's no database repository configured at all.
  const event =
    adminEvent ?? (await getEventDetail(id)) ?? findEventById(report.items, id);

  if (!event) {
    notFound();
  }

  const originalUrl =
    event.content_origin === "manual_editor"
      ? undefined
      : event.original_url ?? event.main_source?.url;
  const originalHost = hostFromUrl(originalUrl);
  const isTelegramRss = event.content_origin === "telegram_rss_description";
  const originalBlocks = originalBlocksFor(event);
  const translatedBlocks = translatedBlocksFor(event);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-[minmax(0,1fr)] content-start lg:grid-cols-[224px_minmax(0,1fr)]">
        <Sidebar activeNavId="latest" />
        <MobileNav activeNavId="latest" />

        <section className="min-w-0 px-5 pt-4 pb-8 md:py-12">
          <div className="mx-auto max-w-3xl">
            {adminPreview === "1" && event.hidden ? (
              <aside className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
                <span>管理员预览：该文章当前处于隐藏状态，公开页面仍不可访问。</span>
                <a
                  className="font-semibold underline underline-offset-4 hover:text-ink"
                  href="/admin/events?status=hidden"
                >
                  返回隐藏文章列表
                </a>
              </aside>
            ) : null}
            <header>
              <div className="flex items-start justify-between gap-3 md:items-center">
                <div className="min-w-0 flex-1">
                  <div className="flex h-5 min-w-0 items-center gap-x-3 text-sm text-ink-mid md:h-6">
                    <span className="min-w-0 truncate font-semibold text-ink">
                      {event.main_source?.name ?? "未知来源"}
                    </span>
                    <span className="hidden md:inline">
                      {formatDateTime(event.published_at, event.content_origin, event.time_basis)}
                    </span>
                    <span className="hidden md:inline">
                      {event.category_label ?? event.category ?? "未分类"}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-ink-mid md:hidden">
                    <span>{formatDateTime(event.published_at, event.content_origin, event.time_basis)}</span>
                    <span>{event.category_label ?? event.category ?? "未分类"}</span>
                  </div>
                </div>

                <div className="flex shrink-0 items-center gap-1.5 md:gap-2">
                  <span className="inline-flex h-5 items-center justify-center rounded-full border border-signal/60 bg-signal/15 px-1.5 text-[11px] font-semibold leading-none text-signal-bright md:h-6 md:px-2 md:text-xs">
                    精选
                  </span>
                  <span className="readout inline-flex h-5 items-center justify-center rounded-full border border-signal/40 px-1.5 text-[11px] font-semibold leading-none text-signal md:h-6 md:px-2 md:text-xs">
                    {formatScore(event.final_score)}
                  </span>
                  <BookmarkButton eventId={event.event_id} labelOnDesktop />
                </div>
              </div>

              <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-normal text-ink md:text-3xl">
                {event.title}
              </h1>
              {originalUrl ? (
                <a
                  className="mt-4 flex w-fit items-center gap-2 text-sm font-medium text-signal hover:text-signal-bright"
                  href={originalUrl}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  <ExternalLink aria-hidden className="h-4 w-4" strokeWidth={2} />
                  {isTelegramRss ? "查看 Telegram 原帖" : "阅读原文"}
                  {originalHost ? <span className="text-ink-dim"> · {originalHost}</span> : null}
                </a>
              ) : null}
            </header>

            <section className="mt-4 rounded-md border border-signal/30 bg-signal/5 p-4">
              <h2 className="text-xs font-semibold text-signal-bright">推荐理由</h2>
              <p className="mt-2 text-sm leading-6 text-ink-mid">{event.reason ?? "暂无推荐理由。"}</p>
            </section>

            <section className="mt-4 rounded-md border border-line-strong bg-panel p-4">
              <h2 className="text-xs font-semibold text-signal">AI 摘要</h2>
              <p className="mt-2 text-sm leading-6 text-ink-mid">
                {event.summary ?? event.one_line_summary ?? "暂无摘要。"}
              </p>
            </section>

            {event.content_origin === "aihot_item_page_link_only" ? null : translatedBlocks.length ||
              event.original_markdown ? (
              <ArticleReadingToggle
                originalBlocks={originalBlocks}
                originalMarkdown={event.original_markdown}
                translatedBlocks={translatedBlocks}
              />
            ) : (
              <article className="mt-4 border-t border-line pt-4">
                <h2 className="text-sm font-semibold text-ink-mid">原文</h2>
                <div className="mt-4 space-y-4">{originalBlocks.map(renderOriginalBlock)}</div>
              </article>
            )}

            {event.tags?.length ? (
              <section className="mt-8 flex flex-wrap gap-2" aria-label="标签">
                {event.tags.map((tag) => (
                  <a
                    key={tag}
                    href={tagHref(tag)}
                    className="rounded-md bg-panel-soft px-3 py-1.5 text-xs text-ink-mid transition hover:bg-line hover:text-signal-bright"
                  >
                    {tag}
                  </a>
                ))}
              </section>
            ) : null}

            {originalUrl ? (
              <a
                className="mt-8 inline-flex items-center gap-2 rounded-md border border-signal/50 bg-panel px-4 py-2.5 text-sm font-semibold text-signal transition hover:border-signal hover:text-signal-bright"
                href={originalUrl}
                rel="noopener noreferrer"
                target="_blank"
              >
                {isTelegramRss ? "查看 Telegram 原帖" : "阅读原文"}
                <ExternalLink aria-hidden className="h-4 w-4" strokeWidth={2} />
                {originalHost ? <span className="text-ink-dim">{originalHost}</span> : null}
              </a>
            ) : null}

            {event.coverage && event.coverage.length > 1 ? (
              <section className="mt-8 rounded-md border border-line bg-panel p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-base font-semibold text-signal">
                    同一事件 · {event.source_count ?? 1} 个信源 ·{" "}
                    {event.coverage.length} 篇报道
                  </h2>
                  <span className="text-sm text-ink-dim">按发布时间排序</span>
                </div>
                <div className="mt-3 divide-y divide-line">
                  {event.coverage.map((member) => (
                    <a
                      key={member.raw_article_id}
                      className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-3 text-sm transition hover:bg-panel-soft/60 md:grid md:grid-cols-[100px_1fr] md:gap-1"
                      href={`/event/${member.event_id}`}
                    >
                      <span className="readout text-ink-dim">{formatRelativeTime(member.published_at)}</span>
                      <span>
                        <span className="font-semibold text-ink">{member.title}</span>
                        <span className="ml-2 text-ink-dim">
                          {member.source_name}
                          {member.is_main ? " · 主要来源" : ""}
                        </span>
                      </span>
                    </a>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
