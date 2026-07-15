import type { OriginalBlock } from "@/lib/api";
import { proxiedImageUrl } from "@/lib/images";
import { RichParagraph } from "@/components/rich-paragraph";
import { ArticleImage } from "@/components/article-image";

// shared with markdownComponents' h1/h2/h3 in article-reading-toggle.tsx so
// a heading looks the same whether it arrived as a structured block (this
// file) or as real Markdown (GitHub README path) - h4~h6 have no dedicated
// design yet, so they fall back to the h3 treatment.
export const HEADING_CLASSNAMES: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
  1: "mt-8 text-2xl font-semibold leading-tight text-ink",
  2: "mt-7 border-b border-line pb-2 text-xl font-semibold text-ink",
  3: "mt-6 text-lg font-semibold text-ink",
  4: "mt-6 text-lg font-semibold text-ink",
  5: "mt-6 text-lg font-semibold text-ink",
  6: "mt-6 text-lg font-semibold text-ink",
};

function numericDimension(value: unknown) {
  if (typeof value === "number") {
    return value;
  }
  if (typeof value !== "string") {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function isReadmeInlineImage({
  src,
  width,
  height,
}: {
  src?: string;
  width?: unknown;
  height?: unknown;
}) {
  const imageUrl = src ?? "";
  const imageWidth = numericDimension(width);
  const imageHeight = numericDimension(height);
  return (
    imageUrl.includes("img.shields.io") ||
    imageUrl.includes("badgen.net") ||
    imageUrl.includes("badge.fury.io") ||
    imageUrl.includes("/badge/") ||
    (imageWidth !== null && imageWidth <= 360 && imageHeight !== null && imageHeight <= 120)
  );
}

export function readmeImageClassName(options: { src?: string; width?: unknown; height?: unknown }) {
  if (isReadmeInlineImage(options)) {
    return "inline-block h-auto w-auto max-w-full align-middle";
  }
  return "my-8 block h-auto max-w-full rounded-md border border-line object-contain";
}

function renderHeading(block: Extract<OriginalBlock, { type: "heading" }>, index: number) {
  const Tag = `h${block.level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
  return (
    <Tag key={`${block.text.slice(0, 24)}-${index}`} className={HEADING_CLASSNAMES[block.level]}>
      {block.text}
    </Tag>
  );
}

/** Renders one original/translated content block, shared by the event
 *  detail page's no-translation path and ArticleReadingToggle, so heading/
 *  paragraph/image rendering only needs to be fixed in one place. */
export function renderOriginalBlock(block: OriginalBlock, index: number) {
  // Older cached Telegram payloads may still contain the retired signature block.
  if ((block as { type: string }).type === "signature") {
    return null;
  }
  if (block.type === "heading") {
    return renderHeading(block, index);
  }
  if (block.type === "image") {
    const imageClassName = readmeImageClassName({ src: block.url });
    if (isReadmeInlineImage({ src: block.url })) {
      return (
        <ArticleImage
          key={`${block.url}-${index}`}
          src={proxiedImageUrl(block.url)}
          alt={block.alt ?? ""}
          className={imageClassName}
          fallbackUrl={block.fallback_url}
        />
      );
    }
    return (
      <figure key={`${block.url}-${index}`} className="my-8">
        <ArticleImage
          src={proxiedImageUrl(block.url)}
          alt={block.alt ?? ""}
          className={imageClassName}
          fallbackUrl={block.fallback_url}
        />
        {block.caption ? (
          <figcaption className="mt-2 text-center text-sm text-ink-mid">{block.caption}</figcaption>
        ) : null}
      </figure>
    );
  }
  if (block.type === "source_list") {
    return (
      <section
        key={`sources-${index}`}
        className="rounded-md border border-line-strong bg-panel p-4"
        aria-label="文章来源"
      >
        <div className="readout text-xs font-semibold uppercase tracking-wide text-ink-dim">文章来源</div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-3">
          {block.links.map((link) => (
            <a
              key={link.url}
              className="min-w-0 break-all text-sm font-semibold text-signal underline decoration-signal/35 underline-offset-4 hover:text-signal-bright"
              href={link.url}
              rel="noopener noreferrer"
              target="_blank"
            >
              {link.label || link.host} ↗
            </a>
          ))}
        </div>
      </section>
    );
  }
  if (block.type === "quote") {
    const label =
      block.kind === "reply" ? "回复上文" : block.kind === "update" ? "更新记录" : "引用";
    const tone =
      block.kind === "reply"
        ? "border-signal/45 bg-signal/5"
        : block.kind === "update"
          ? "border-signal bg-panel"
          : "border-line-strong bg-panel-soft";
    return (
      <aside key={`${block.kind}-${index}`} className={`border-l-2 p-4 ${tone}`}>
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <span className="font-semibold text-signal-bright">{block.label ?? label}</span>
          {block.source_url ? (
            <a
              className="text-signal hover:text-signal-bright"
              href={block.source_url}
              rel="noopener noreferrer"
              target="_blank"
            >
              {block.author ? `${block.author} · ` : ""}查看原帖 ↗
            </a>
          ) : block.author ? (
            <span className="text-ink-dim">{block.author}</span>
          ) : null}
        </div>
        {block.children.length ? (
          <div className="mt-4 space-y-4">{block.children.map(renderOriginalBlock)}</div>
        ) : null}
      </aside>
    );
  }
  return (
    <RichParagraph key={`${block.text.slice(0, 24)}-${index}`} text={block.text} html={block.html} />
  );
}
