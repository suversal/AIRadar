import { notFound } from "next/navigation";
import type { LatestEvent, OriginalBlock } from "@/lib/api";
import { getEventDetail, getLatestReport } from "@/lib/api";
import { findEventById } from "@/lib/events";
import { ArticleReadingToggle } from "./article-reading-toggle";
import { RichParagraph } from "@/components/rich-paragraph";
import { Sidebar } from "@/components/sidebar";

type EventParams = Promise<{
  id: string;
}>;


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
          className="max-h-[520px] w-full rounded-md border border-line object-contain"
          referrerPolicy="no-referrer"
        />
        {block.caption ? (
          <figcaption className="mt-2 text-center text-sm text-ink-mid">{block.caption}</figcaption>
        ) : null}
      </figure>
    );
  }
  return (
    <RichParagraph key={`${block.text.slice(0, 24)}-${index}`} text={block.text} html={block.html} />
  );
}

export default async function EventDetailPage({ params }: { params: EventParams }) {
  const { id } = await params;
  const report = await getLatestReport();
  const event = findEventById(report.items, id) ?? (await getEventDetail(id));

  if (!event) {
    notFound();
  }

  const originalUrl = event.original_url ?? event.main_source?.url;
  const originalHost = hostFromUrl(originalUrl);
  const originalBlocks = originalBlocksFor(event);
  const translatedBlocks = translatedBlocksFor(event);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="latest" />

        <section className="px-5 py-8 md:py-12">
          <div className="mx-auto max-w-4xl">
            <header>
              <div className="flex flex-wrap items-center justify-end gap-3">
                <span className="rounded-full border border-signal/60 bg-signal/15 px-3 py-1 text-sm font-semibold text-signal-bright">
                  精选
                </span>
                <span className="readout rounded-full border border-signal/40 px-3 py-1 text-sm font-semibold text-signal">
                  {formatScore(event.final_score)}
                </span>
              </div>

              <div className="mt-10 flex items-start gap-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line-strong bg-panel text-sm font-semibold text-signal-bright">
                  {(event.main_source?.name ?? "AI").slice(0, 2)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-mid">
                    <span className="font-semibold text-ink">{event.main_source?.name ?? "未知来源"}</span>
                    <span>{formatDateTime(event.published_at)}</span>
                    <span>{event.category_label ?? event.category ?? "未分类"}</span>
                  </div>
                  <h1 className="mt-4 text-3xl font-semibold leading-tight tracking-normal text-ink md:text-4xl">
                    {event.title}
                  </h1>
                  {originalUrl ? (
                    <a
                      className="mt-6 inline-flex items-center gap-2 text-base font-medium text-signal hover:text-signal-bright"
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

            <section className="mt-8 rounded-md border border-signal/30 bg-signal/5 p-5">
              <h2 className="text-sm font-semibold text-signal-bright">推荐理由</h2>
              <p className="mt-3 text-base leading-7 text-ink-mid">{event.reason ?? "暂无推荐理由。"}</p>
            </section>

            <section className="mt-6 rounded-md border border-line-strong bg-panel p-5">
              <h2 className="text-sm font-semibold text-signal">AI 摘要</h2>
              <p className="mt-3 text-base leading-7 text-ink-mid">
                {event.summary ?? event.one_line_summary ?? "暂无摘要。"}
              </p>
            </section>

            {translatedBlocks.length || event.original_markdown ? (
              <ArticleReadingToggle
                originalBlocks={originalBlocks}
                originalMarkdown={event.original_markdown}
                translatedBlocks={translatedBlocks}
              />
            ) : (
              <article className="mt-10 border-t border-line pt-8">
                <h2 className="text-sm font-semibold text-ink-mid">原文</h2>
                <div className="mt-6 space-y-6">{originalBlocks.map(renderOriginalBlock)}</div>
              </article>
            )}

            {event.tags?.length ? (
              <section className="mt-10 flex flex-wrap gap-3" aria-label="标签">
                {event.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-md border border-line-strong bg-panel px-3 py-2 text-sm text-ink-mid"
                  >
                    {tag}
                  </span>
                ))}
              </section>
            ) : null}

            {originalUrl ? (
              <a
                className="mt-10 inline-flex rounded-md border border-line-strong bg-panel px-5 py-3 text-base font-semibold text-ink-mid hover:border-signal/50 hover:text-signal-bright"
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
