import { notFound } from "next/navigation";
import type { LatestEvent, OriginalBlock } from "@/lib/api";
import { getLatestReport } from "@/lib/api";
import { findEventById } from "@/lib/events";
import { ArticleReadingToggle } from "./article-reading-toggle";

type SidebarItem = {
  id: string;
  label: string;
  group: "内容" | "接入" | "更多";
  href?: string;
  active?: boolean;
};

type EventParams = Promise<{
  id: string;
}>;

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

function menuGroupItems(group: SidebarItem["group"]) {
  return sidebarItems.filter((item) => item.group === group);
}

function sidebarMarker(label: string) {
  return label.slice(0, 1);
}

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return Math.round(score).toString();
}

function formatDateTime(value?: string) {
  if (!value) {
    return "暂无时间";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
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

function originalBlocksFor(event: LatestEvent): OriginalBlock[] {
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

function renderOriginalBlock(block: OriginalBlock, index: number) {
  if (block.type === "image") {
    return (
      <figure key={`${block.url}-${index}`} className="my-8">
        <img
          src={block.url}
          alt={block.alt ?? ""}
          className="max-h-[520px] w-full rounded-md border border-slate-800 object-contain"
        />
        {block.caption ? (
          <figcaption className="mt-2 text-center text-sm text-slate-500">{block.caption}</figcaption>
        ) : null}
      </figure>
    );
  }
  return (
    <p key={`${block.text.slice(0, 24)}-${index}`} className="text-[17px] leading-8 text-slate-200">
      {block.text}
    </p>
  );
}

export default async function EventDetailPage({ params }: { params: EventParams }) {
  const { id } = await params;
  const report = await getLatestReport();
  const event = findEventById(report.items, id);

  if (!event) {
    notFound();
  }

  const originalUrl = event.original_url ?? event.main_source?.url;
  const originalHost = hostFromUrl(originalUrl);
  const originalBlocks = originalBlocksFor(event);
  const translatedBlocks = translatedBlocksFor(event);

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
                        <span className="min-w-0 truncate">{item.label}</span>
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

        <section className="px-5 py-8 md:py-12">
          <div className="mx-auto max-w-4xl">
            <header>
              <div className="flex flex-wrap items-center justify-end gap-3">
                <span className="rounded-full border border-amber-500/40 px-3 py-1 text-sm font-semibold text-amber-300">
                  精选
                </span>
                <span className="rounded-full border border-cyan-400/40 px-3 py-1 text-sm font-semibold text-cyan-300">
                  {formatScore(event.final_score)}
                </span>
              </div>

              <div className="mt-10 flex items-start gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-sm font-semibold text-cyan-200">
                  {(event.main_source?.name ?? "AI").slice(0, 2)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
                    <span className="font-semibold text-slate-200">{event.main_source?.name ?? "未知来源"}</span>
                    <span>{formatDateTime(event.published_at)}</span>
                    <span>{event.category_label ?? event.category ?? "未分类"}</span>
                  </div>
                  <h1 className="mt-4 text-3xl font-semibold leading-tight tracking-normal text-slate-50 md:text-4xl">
                    {event.title}
                  </h1>
                  {originalUrl ? (
                    <a
                      className="mt-6 inline-flex items-center gap-2 text-base font-medium text-cyan-300 hover:text-cyan-200"
                      href={originalUrl}
                      rel="noreferrer"
                      target="_blank"
                    >
                      阅读原文{originalHost ? ` · ${originalHost}` : ""}
                    </a>
                  ) : null}
                </div>
              </div>
            </header>

            <section className="mt-8 rounded-md border border-amber-500/30 bg-amber-500/5 p-5">
              <h2 className="text-sm font-semibold text-amber-300">推荐理由</h2>
              <p className="mt-3 text-base leading-7 text-slate-300">{event.reason ?? "暂无推荐理由。"}</p>
            </section>

            <section className="mt-6 rounded-md border border-slate-700 bg-slate-900/60 p-5">
              <h2 className="text-sm font-semibold text-cyan-300">AI 摘要</h2>
              <p className="mt-3 text-base leading-7 text-slate-300">
                {event.summary ?? event.one_line_summary ?? "暂无摘要。"}
              </p>
            </section>

            {translatedBlocks.length ? (
              <ArticleReadingToggle originalBlocks={originalBlocks} translatedBlocks={translatedBlocks} />
            ) : (
              <article className="mt-10 border-t border-slate-800 pt-8">
                <h2 className="text-sm font-semibold text-slate-500">原文</h2>
                <div className="mt-6 space-y-6">{originalBlocks.map(renderOriginalBlock)}</div>
              </article>
            )}

            {event.tags?.length ? (
              <section className="mt-10 flex flex-wrap gap-3" aria-label="标签">
                {event.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-400"
                  >
                    {tag}
                  </span>
                ))}
              </section>
            ) : null}

            {originalUrl ? (
              <a
                className="mt-10 inline-flex rounded-md border border-slate-700 bg-slate-900 px-5 py-3 text-base font-semibold text-slate-300 hover:border-cyan-400/50 hover:text-cyan-200"
                href={originalUrl}
                rel="noreferrer"
                target="_blank"
              >
                阅读原文{originalHost ? ` · ${originalHost}` : ""}
              </a>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
