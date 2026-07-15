import type { OriginalBlock } from "@/lib/api";
import { proxiedImageUrl } from "@/lib/images";
import { RichParagraph } from "@/components/rich-paragraph";
import { ArticleImage } from "@/components/article-image";
import { AuthorAvatar } from "@/components/author-avatar";

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
  return "mx-auto my-8 block h-auto w-auto max-w-full rounded-md border border-line object-contain";
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
    const imageClassName = readmeImageClassName({ src: block.url, width: block.width, height: block.height });
    const imageStyle = block.width
      ? { width: `min(100%, ${block.width}px)`, maxWidth: "100%" }
      : undefined;
    if (isReadmeInlineImage({ src: block.url, width: block.width, height: block.height })) {
      return (
        <ArticleImage
          key={`${block.url}-${index}`}
          src={proxiedImageUrl(block.url)}
          alt={block.alt ?? ""}
          className={imageClassName}
          fallbackUrl={block.fallback_url}
          width={block.width}
          height={block.height}
          style={imageStyle}
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
          width={block.width}
          height={block.height}
          style={imageStyle}
        />
        {block.caption ? (
          <figcaption className="mt-2 text-center text-sm text-ink-mid">{block.caption}</figcaption>
        ) : null}
      </figure>
    );
  }
  if (block.type === "byline") {
    const authorName = block.author.name;
    const authorContent = <span className="font-semibold text-ink">{authorName}</span>;
    return (
      <section key={`byline-${index}`} className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 border-y border-line py-4 text-sm text-ink-mid">
        <AuthorAvatar name={authorName} src={block.author.avatar_url} />
        <div className="min-w-0 flex-1">
          <div>{block.author.url ? <a href={block.author.url} target="_blank" rel="noopener noreferrer" className="hover:text-signal">{authorContent}</a> : authorContent}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-dim">
            {block.published_at ? <time>{block.published_at}</time> : null}
            {block.source ? (
              <span>来源：{block.source.url ? <a className="text-signal hover:text-signal-bright" href={block.source.url} target="_blank" rel="noopener noreferrer">{block.source.name}</a> : block.source.name}</span>
            ) : null}
          </div>
        </div>
      </section>
    );
  }
  if (block.type === "callout") {
    return (
      <aside key={`callout-${index}`} className={`rounded-md border px-5 py-4 ${block.kind === "lead" ? "border-signal/30 bg-signal/5" : "border-line-strong bg-panel-soft"}`}>
        <div className="space-y-3">{block.children.map(renderOriginalBlock)}</div>
      </aside>
    );
  }
  if (block.type === "list") {
    const Tag = block.ordered ? "ol" : "ul";
    return (
      <Tag key={`list-${index}`} className={`ml-6 space-y-2 text-[17px] leading-8 text-ink ${block.ordered ? "list-decimal" : "list-disc"}`}>
        {block.items.map((item, itemIndex) => <li key={`${item.text}-${itemIndex}`} className="pl-1"><RichParagraph text={item.text} html={item.html} /></li>)}
      </Tag>
    );
  }
  if (block.type === "code") {
    return <pre key={`code-${index}`} className="max-w-full overflow-x-auto rounded-md border border-line-strong bg-panel-soft p-4 text-sm leading-6 text-ink"><code>{block.text}</code></pre>;
  }
  if (block.type === "table") {
    return (
      <div key={`table-${index}`} className="max-w-full overflow-x-auto rounded-md border border-line-strong">
        <table className="min-w-full border-collapse text-left text-sm text-ink">
          {block.headers.length ? <thead className="bg-panel-soft"><tr>{block.headers.map((cell, cellIndex) => <th key={cellIndex} className="border-b border-line-strong px-4 py-3 font-semibold"><RichParagraph text={cell.text} html={cell.html} /></th>)}</tr></thead> : null}
          <tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-b border-line last:border-b-0">{row.map((cell, cellIndex) => <td key={cellIndex} className="min-w-36 px-4 py-3 align-top"><RichParagraph text={cell.text} html={cell.html} /></td>)}</tr>)}</tbody>
        </table>
      </div>
    );
  }
  if (block.type === "divider") {
    return <hr key={`divider-${index}`} className="border-0 border-t border-line-strong" />;
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
    const label = block.kind === "reply" ? "回复上文" : block.kind === "update" ? "更新记录" : null;
    const tone =
      block.kind === "reply"
        ? "border-signal/45 bg-signal/5"
        : block.kind === "update"
          ? "border-signal bg-panel"
          : "border-line-strong bg-panel-soft";
    return (
      <aside key={`${block.kind}-${index}`} className={`border-l-2 p-4 ${tone}`}>
        {(block.label || label || block.source_url || block.author) ? <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          {block.label || label ? <span className="font-semibold text-signal-bright">{block.label ?? label}</span> : <span />}
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
        </div> : null}
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
