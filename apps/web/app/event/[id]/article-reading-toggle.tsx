"use client";

import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { OriginalBlock } from "@/lib/api";

type ArticleReadingToggleProps = {
  originalBlocks: OriginalBlock[];
  originalMarkdown?: string;
  translatedBlocks: OriginalBlock[];
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

function isReadmeInlineImage({
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

function readmeImageClassName(options: { src?: string; width?: unknown; height?: unknown }) {
  if (isReadmeInlineImage(options)) {
    return "inline-block h-auto w-auto max-w-full align-middle";
  }
  return "my-8 block h-auto max-w-full rounded-md border border-slate-800 object-contain";
}

function cleanTableElementProps<Props extends object>(props: Props) {
  const { vAlign: _vAlign, valign: _valign, ...cleanProps } = props as Props & {
    vAlign?: unknown;
    valign?: unknown;
  };
  return cleanProps;
}

const markdownComponents: Components = {
  h1({ node: _node, ...props }) {
    return <h1 className="mt-10 text-3xl font-semibold leading-tight text-slate-50" {...props} />;
  },
  h2({ node: _node, ...props }) {
    return <h2 className="mt-9 border-b border-slate-800 pb-2 text-2xl font-semibold text-slate-100" {...props} />;
  },
  h3({ node: _node, ...props }) {
    return <h3 className="mt-8 text-xl font-semibold text-slate-100" {...props} />;
  },
  p({ node: _node, ...props }) {
    return <p className="text-[17px] leading-8 text-slate-200" {...props} />;
  },
  a({ node: _node, ...props }) {
    return <a className="text-cyan-300 hover:text-cyan-200" rel="noreferrer" target="_blank" {...props} />;
  },
  ul({ node: _node, ...props }) {
    return <ul className="ml-6 list-disc space-y-2 text-[17px] leading-8 text-slate-200" {...props} />;
  },
  ol({ node: _node, ...props }) {
    return <ol className="ml-6 list-decimal space-y-2 text-[17px] leading-8 text-slate-200" {...props} />;
  },
  li({ node: _node, ...props }) {
    return <li className="pl-1" {...props} />;
  },
  blockquote({ node: _node, ...props }) {
    return <blockquote className="border-l-2 border-amber-400/50 pl-4 text-slate-300" {...props} />;
  },
  code({ node: _node, className, children, ...props }) {
    const isBlock = className?.startsWith("language-") || String(children).includes("\n");
    if (isBlock) {
      return (
        <code className={`block overflow-x-auto p-4 text-sm leading-6 text-slate-200 ${className ?? ""}`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-sm text-cyan-100" {...props}>
        {children}
      </code>
    );
  },
  pre({ node: _node, ...props }) {
    return <pre className="overflow-x-auto rounded-md border border-slate-800 bg-[#050a14]" {...props} />;
  },
  table({ node: _node, ...props }) {
    return (
      <div className="overflow-x-auto rounded-md border border-slate-800">
        <table
          className="w-full border-collapse text-left text-sm text-slate-300"
          {...cleanTableElementProps(props)}
        />
      </div>
    );
  },
  tr({ node: _node, ...props }) {
    return <tr {...cleanTableElementProps(props)} />;
  },
  th({ node: _node, ...props }) {
    return (
      <th
        className="border-b border-slate-800 bg-slate-900 px-3 py-2 font-semibold text-slate-100"
        {...cleanTableElementProps(props)}
      />
    );
  },
  td({ node: _node, ...props }) {
    return <td className="border-b border-slate-800 px-3 py-2 align-top" {...cleanTableElementProps(props)} />;
  },
  img({ node: _node, alt, ...props }) {
    return (
      <img
        alt={alt ?? ""}
        className={readmeImageClassName({
          src: typeof props.src === "string" ? props.src : undefined,
          width: props.width,
          height: props.height,
        })}
        loading="lazy"
        {...props}
      />
    );
  },
  hr({ node: _node, ...props }) {
    return <hr className="border-slate-800" {...props} />;
  },
};

function renderBlock(block: OriginalBlock, index: number) {
  if (block.type === "image") {
    const imageClassName = readmeImageClassName({ src: block.url });
    if (isReadmeInlineImage({ src: block.url })) {
      return (
        <img
          key={`${block.url}-${index}`}
          src={block.url}
          alt={block.alt ?? ""}
          className={imageClassName}
          loading="lazy"
        />
      );
    }
    return (
      <figure key={`${block.url}-${index}`} className="my-8">
        <img
          src={block.url}
          alt={block.alt ?? ""}
          className={imageClassName}
          loading="lazy"
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

function MarkdownArticle({ markdown }: { markdown: string }) {
  return (
    <div className="space-y-5">
      <ReactMarkdown
        components={markdownComponents}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        remarkPlugins={[remarkGfm]}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

export function ArticleReadingToggle({
  originalBlocks,
  originalMarkdown,
  translatedBlocks,
}: ArticleReadingToggleProps) {
  const hasTranslation = translatedBlocks.length > 0;
  const [mode, setMode] = useState<"translated" | "original">(
    hasTranslation ? "translated" : "original",
  );
  const isOriginal = mode === "original";
  const blocks = isOriginal ? originalBlocks : translatedBlocks;
  const markdown = originalMarkdown?.trim();

  return (
    <article className="mt-10 border-t border-slate-800 pt-8">
      <div className="flex items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="text-sm font-semibold text-slate-500">
          {isOriginal ? "原文" : "AI 翻译 · 中文"}
        </div>
        {hasTranslation ? (
          <button
            type="button"
            className="rounded-none border border-transparent px-4 py-2 text-sm font-semibold text-cyan-300 transition hover:border-cyan-400/40 hover:text-cyan-200"
            onClick={() => setMode(isOriginal ? "translated" : "original")}
          >
            {isOriginal ? "显示译文" : "显示原文"}
          </button>
        ) : null}
      </div>
      <div className="mt-6 space-y-6">
        {isOriginal && markdown ? <MarkdownArticle markdown={markdown} /> : blocks.map(renderBlock)}
      </div>
    </article>
  );
}
