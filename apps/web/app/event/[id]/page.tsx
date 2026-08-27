import { notFound } from "next/navigation";
import { ExternalLink, Sparkles } from "lucide-react";
import type { LatestEvent, OriginalBlock } from "@/lib/api";
import { getEventDetailResult, getLatestReport } from "@/lib/api";
import { findEventById } from "@/lib/events";
import { formatRelativeTime } from "@/lib/time";
import { ArticleReadingToggle } from "./article-reading-toggle";
import { renderOriginalBlock } from "@/components/original-block";
import { BookmarkButton } from "@/components/bookmark-button";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";
import { GridBackground } from "@/components/ui/grid-background";
import { adminFetch } from "@/lib/admin-api";

type EventParams = Promise<{
  id: string;
}>;

type EventSearchParams = Promise<{
  admin_preview?: string;
}>;

// 摘要里可能混进换行、连续空格和 markdown 残留，直接塞进 meta description
// 会让搜索结果和分享卡片出现断行与符号。先压平再截断。
//
// 截断点选在标点上而不是硬切第 N 个字：中文摘要被从半句腰斩，
// 在搜索结果里读起来像内容缺失。找不到合适标点时才回退到硬截。
const DESCRIPTION_MAX = 150;

function cleanDescription(raw?: string): string | undefined {
  const flat = (raw ?? "").replace(/[#*`>_~]/g, "").replace(/\s+/g, " ").trim();
  if (!flat) {
    return undefined;
  }
  if (flat.length <= DESCRIPTION_MAX) {
    return flat;
  }
  const head = flat.slice(0, DESCRIPTION_MAX);
  // 在后半段里找最后一个句读，避免为了断句把描述砍得过短
  const cut = Math.max(
    head.lastIndexOf("。"),
    head.lastIndexOf("；"),
    head.lastIndexOf("！"),
    head.lastIndexOf("？"),
    head.lastIndexOf("."),
  );
  return cut > DESCRIPTION_MAX * 0.6 ? head.slice(0, cut + 1) : `${head}…`;
}

// app/opengraph-image.tsx 那张站点默认分享图的路由。裸路径可直接访问
// （实测 200 image/png），metadataBase 会把它补成绝对 URL。
const DEFAULT_SHARE_IMAGE = "/opengraph-image";

// 分享卡片的图必须是**站外抓取器能直接拿到**的绝对 URL，所以这里返回原始外链图，
// 不套 /api/image-proxy：robots.txt 禁掉了整个 /api，而 image-proxy 又是全站
// 最贵的端点（SSRF 校验 + 最大 8MB 回源），没有理由为了一张分享图把它对全网抓取器敞开。
// 原图带防盗链的情况这里能接受：抓取器不带 Referer，多数防盗链对空 Referer 是放行的；
// 真抓不到时平台自己会回退，卡片退化成无图，不会出错。
//
// 拿不到文章图时回退到 DEFAULT_SHARE_IMAGE。这个回退是必须的，别想着"留空
// 让 Next 自己补默认图"——实测（2026-08-17，Next 16.2.10）：只要页面自己
// 定义了 openGraph 对象，app/opengraph-image.tsx 生成的默认图就**不再注入**，
// 哪怕完全没写 images 键。表现是 /latest 有 og:image、/event/xxx 一个都没有，
// 分享出去是一张没有配图的裸卡片，而且不报任何错。
function shareImageUrl(event: LatestEvent): string {
  const fromImages = event.original_images?.find((image) => /^https?:\/\//i.test(image.url));
  if (fromImages) {
    return fromImages.url;
  }
  // OriginalBlock 是按 type 区分的联合类型，只有 image 分支才有 url，
  // 所以先 filter 出 image 再取——直接在 find 的谓词里判断不会让 TS 窄化。
  const imageBlocks = event.original_blocks?.filter(
    (block): block is Extract<OriginalBlock, { type: "image" }> => block.type === "image",
  );
  return (
    imageBlocks?.find((block) => /^https?:\/\//i.test(block.url))?.url ?? DEFAULT_SHARE_IMAGE
  );
}

// 详情页是站外分享与搜索收录的落地页，metadata 必须带上文章自己的标题与摘要。
//
// 补齐 canonical / OG / Twitter 之前，这里只有 title + description，后果有两个：
//   1. 分享到微信、X 时卡片显示的是**站点通用标题和默认图**，每一次分享都白费；
//   2. 没有自引用 canonical，规范 URL 交给搜索引擎自己猜——而同一事件的
//      不同信源成员各有自己的 /event/{id}，猜错就是内容重复。
export async function generateMetadata({
  params,
  searchParams,
}: {
  params: EventParams;
  searchParams: EventSearchParams;
}) {
  const { id } = await params;
  const { admin_preview: adminPreview } = await searchParams;
  const detail = await getEventDetailResult(id);
  if (detail.status === "not_found") {
    return { title: "内容详情", robots: { index: false, follow: false } };
  }

  // 上游临时失败不能伪装成"页面不存在"并发出 noindex。先用精选列表里
  // 同一事件的轻量缓存生成稳定 metadata；旧事件不在缓存里时直接抛错，
  // 让搜索引擎收到可重试的 5xx，而不是永久移除信号。
  let event: LatestEvent;
  if (detail.status === "ok") {
    event = detail.event;
  } else {
    const report = await getLatestReport({ limit: 200 });
    const cachedEvent = findEventById(report.items, id);
    if (!cachedEvent) {
      throw new Error(`Event metadata temporarily unavailable: ${detail.error}`);
    }
    event = cachedEvent;
  }

  // 用后端返回的 event_id 而不是 URL 里的 id 做 canonical：
  // 后端若对旧 id 做过归一，canonical 会自动指向规范页，不用前端再维护一张映射表。
  const canonicalPath = `/event/${event.event_id}`;
  const description = cleanDescription(event.summary ?? event.one_line_summary);
  const image = shareImageUrl(event);

  // 管理员预览会渲染尚未公开（hidden）的内容，绝不能进索引，也不能让爬虫
  // 顺着它往下爬。同理，后端把文章标成 hidden 时也一律 noindex。
  const isPrivateView = adminPreview === "1" || event.hidden === true;

  return {
    title: event.title,
    description,
    alternates: { canonical: canonicalPath },
    ...(isPrivateView ? { robots: { index: false, follow: false } } : {}),
    openGraph: {
      type: "article",
      url: canonicalPath,
      title: event.title,
      description,
      images: [image],
      // time_basis="discovered" 时 published_at 只是我们的收录时间，不是原文发布时间。
      // 这是 SourcePilot 的契约红线：页面上写「收录于」，机器可读字段同样不能伪称发布时间，
      // 否则等于用结构化数据把页面上诚实标注的东西又谎报了一遍。
      ...(event.published_at && event.time_basis !== "discovered"
        ? { publishedTime: event.published_at }
        : {}),
    },
    twitter: {
      card: "summary_large_image",
      title: event.title,
      description,
      images: [image],
    },
  };
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

type TextBearingBlock = {
  type: "paragraph" | "heading" | "code";
  text: string;
};

function textBearingBlocks(blocks: OriginalBlock[]): TextBearingBlock[] {
  const result: TextBearingBlock[] = [];
  for (const block of blocks) {
    if (block.type === "paragraph" || block.type === "heading" || block.type === "code") {
      result.push({ type: block.type, text: block.text });
    } else if (block.type === "quote" || block.type === "callout") {
      result.push(...textBearingBlocks(block.children));
    } else if (block.type === "list") {
      result.push(...block.items.map((item) => ({ type: "paragraph" as const, text: item.text })));
    } else if (block.type === "table") {
      result.push(
        ...[block.headers, ...block.rows]
          .flat()
          .map((cell) => ({ type: "paragraph" as const, text: cell.text })),
      );
    }
  }
  return result;
}

function translationLooksAligned(
  originalBlocks: OriginalBlock[],
  translatedBlocks: OriginalBlock[],
) {
  const originalText = textBearingBlocks(originalBlocks);
  const translatedText = textBearingBlocks(translatedBlocks);
  // Positional translation is only safe when every source text slot has one
  // translated counterpart. Accepting a shorter result shifts all later text
  // into the wrong heading/code/list slots even if the block shell survives.
  if (!translatedText.length || translatedText.length !== originalText.length) {
    return false;
  }

  return translatedText.every((translated, index) => {
    const original = originalText[index];
    if (!original || original.type !== translated.type) {
      return false;
    }
    // A real heading remains a heading after translation. A short source
    // heading receiving an entire body paragraph is the strongest signal that
    // one provider output went missing and shifted all following positions.
    if (
      original.type === "heading" &&
      original.text.length <= 100 &&
      translated.text.length > Math.max(100, original.text.length * 6)
    ) {
      return false;
    }
    return true;
  });
}

function translatedBlocksFor(
  event: LatestEvent,
  originalBlocks: OriginalBlock[],
): OriginalBlock[] {
  let blocks: OriginalBlock[] = [];
  if (event.translated_blocks?.length) {
    blocks = event.translated_blocks;
  } else if (event.translated_paragraphs?.length) {
    blocks = event.translated_paragraphs.map((paragraph) => ({
      type: "paragraph",
      text: paragraph,
    }));
  } else if (event.translated_content) {
    blocks = [{ type: "paragraph", text: event.translated_content }];
  }
  return translationLooksAligned(originalBlocks, blocks) ? blocks : [];
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
  const report = await getLatestReport({ limit: 200 });
  // getEventDetailResult is the only path that resolves full article content and
  // per-source coverage (report.items is a lightweight list-view payload) -
  // it must win whenever it resolves; the list match is just a fallback for
  // when there's no database repository configured at all.
  const detail = adminEvent ? null : await getEventDetailResult(id);
  if (detail?.status === "upstream_error" && !findEventById(report.items, id)) {
    throw new Error(`Event detail temporarily unavailable: ${detail.error}`);
  }
  const event =
    adminEvent ??
    (detail?.status === "ok" ? detail.event : null) ??
    (detail?.status === "upstream_error" ? findEventById(report.items, id) : null);

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
  const translatedBlocks = translatedBlocksFor(event, originalBlocks);

  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-[minmax(0,1fr)] content-start lg:grid-cols-[248px_minmax(0,1fr)]">
        <Sidebar activeNavId="latest" />
        <MobileNav activeNavId="latest" />

        <section className="min-w-0 px-4 pb-16 pt-5 md:px-8 md:py-14 xl:px-16">
          <div className="mx-auto max-w-[1120px]">
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
            <header className="relative mx-auto max-w-[760px] overflow-hidden pb-2 md:pb-3">
              <GridBackground className="opacity-35" />
              <div className="relative flex items-start justify-between gap-4 md:items-center">
                <div className="min-w-0 flex-1">
                  <div className="flex h-5 min-w-0 items-center gap-x-3 text-sm text-ink-mid md:h-6">
                    <span className="min-w-0 truncate font-semibold text-ink">
                      {event.main_source?.name ?? "未知来源"}
                    </span>
                    <span className="readout hidden text-xs uppercase tracking-[0.08em] md:inline">
                      {formatDateTime(event.published_at, event.content_origin, event.time_basis)}
                    </span>
                    <span className="readout hidden text-xs uppercase tracking-[0.08em] md:inline">
                      {event.category_label ?? event.category ?? "未分类"}
                    </span>
                  </div>
                  <div className="readout mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] uppercase tracking-[0.08em] text-ink-mid md:hidden">
                    <span>{formatDateTime(event.published_at, event.content_origin, event.time_basis)}</span>
                    <span>{event.category_label ?? event.category ?? "未分类"}</span>
                  </div>
                </div>

                <div className="flex shrink-0 items-center gap-1.5 md:gap-2">
                  {event.selected ? (
                    <span
                      aria-label="精选"
                      className="readout inline-flex h-5 items-center gap-1 border border-signal/45 bg-signal/10 px-1.5 text-[9px] font-semibold tracking-[0.12em] text-signal"
                      title="精选"
                    >
                      <Sparkles aria-hidden className="h-3 w-3 shrink-0" strokeWidth={1.8} />
                      精选
                    </span>
                  ) : null}
                  <span className="readout text-[10px] font-semibold uppercase tracking-[0.12em] text-signal md:text-xs">
                    Score {formatScore(event.final_score)}
                  </span>
                  <BookmarkButton eventId={event.event_id} labelOnDesktop />
                </div>
              </div>

              <h1 className="editorial-rule-title relative mt-6 text-[clamp(1.9rem,2.6vw,2.8rem)] font-medium leading-[1.12] tracking-[-0.03em] text-ink">
                {event.title}
              </h1>
              {originalUrl ? (
                <a
                  className="relative mt-4 flex w-fit items-center gap-2 text-sm font-medium text-signal hover:text-signal-bright"
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

            <section className="mx-auto mt-7 max-w-[760px] space-y-7 md:mt-9">
              <aside className="border-l-2 border-signal pl-4">
                <h2 className="readout text-[10px] font-semibold tracking-[0.14em] text-signal">
                  推荐理由
                </h2>
                <p className="mt-2.5 text-sm leading-6 text-ink-mid">
                  {event.reason ?? "暂无推荐理由。"}
                </p>
              </aside>
              <div>
                <h2 className="readout text-[10px] font-semibold tracking-[0.14em] text-signal">
                  AI 摘要
                </h2>
                <p className="mt-2.5 text-[15px] leading-7 text-ink-mid md:text-base md:leading-8">
                  {event.summary ?? event.one_line_summary ?? "暂无摘要。"}
                </p>
              </div>
            </section>

            {event.content_origin === "aihot_item_page_link_only" ? null : translatedBlocks.length ||
              event.original_markdown ? (
              <ArticleReadingToggle
                originalBlocks={originalBlocks}
                originalMarkdown={event.original_markdown}
                translatedBlocks={translatedBlocks}
              />
            ) : (
              <article className="mx-auto mt-6 max-w-[760px] border-t border-line-strong pt-5 md:mt-7">
                <h2 className="text-xs font-semibold tracking-[0.08em] text-ink-mid">
                  原文正文
                </h2>
                <div className="mt-5 space-y-4">{originalBlocks.map(renderOriginalBlock)}</div>
              </article>
            )}

            {event.tags?.length ? (
              <section className="mx-auto mt-8 flex max-w-[760px] flex-wrap gap-x-5 gap-y-2" aria-label="标签">
                {event.tags.map((tag) => (
                  <a
                    key={tag}
                    href={tagHref(tag)}
                    className="text-xs text-ink-dim underline decoration-line-strong underline-offset-4 transition hover:text-signal"
                  >
                    #{tag}
                  </a>
                ))}
              </section>
            ) : null}

            {originalUrl ? (
              <a
                className="mx-auto mt-7 flex w-fit max-w-[760px] items-center gap-2 border border-line-strong px-4 py-2.5 text-sm font-semibold text-signal transition hover:border-signal/50 hover:bg-signal/10 hover:text-signal-bright"
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
              <section className="editorial-surface mx-auto mt-12 max-w-[960px] border-y border-line-strong bg-panel/45 px-5 py-5">
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
