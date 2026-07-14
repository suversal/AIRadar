"use client";

import { useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { OriginalBlock } from "@/lib/api";
import { articleSanitizeSchema } from "@/lib/sanitize-schema";
import { proxiedImageUrl } from "@/lib/images";
import { HEADING_CLASSNAMES, readmeImageClassName, renderOriginalBlock } from "@/components/original-block";

type ArticleReadingToggleProps = {
  originalBlocks: OriginalBlock[];
  originalMarkdown?: string;
  translatedBlocks: OriginalBlock[];
};

function cleanTableElementProps<Props extends object>(props: Props) {
  const { vAlign: _vAlign, valign: _valign, ...cleanProps } = props as Props & {
    vAlign?: unknown;
    valign?: unknown;
  };
  return cleanProps;
}

const markdownComponents: Components = {
  h1({ node: _node, ...props }) {
    return <h1 className={HEADING_CLASSNAMES[1]} {...props} />;
  },
  h2({ node: _node, ...props }) {
    return <h2 className={HEADING_CLASSNAMES[2]} {...props} />;
  },
  h3({ node: _node, ...props }) {
    return <h3 className={HEADING_CLASSNAMES[3]} {...props} />;
  },
  h4({ node: _node, ...props }) {
    return <h4 className={HEADING_CLASSNAMES[4]} {...props} />;
  },
  h5({ node: _node, ...props }) {
    return <h5 className={HEADING_CLASSNAMES[5]} {...props} />;
  },
  h6({ node: _node, ...props }) {
    return <h6 className={HEADING_CLASSNAMES[6]} {...props} />;
  },
  p({ node: _node, ...props }) {
    return <p className="text-base leading-7 text-ink" {...props} />;
  },
  a({ node: _node, ...props }) {
    return <a className="text-signal hover:text-signal-bright" rel="noreferrer" target="_blank" {...props} />;
  },
  ul({ node: _node, ...props }) {
    return <ul className="ml-6 list-disc space-y-2 text-base leading-7 text-ink" {...props} />;
  },
  ol({ node: _node, ...props }) {
    return <ol className="ml-6 list-decimal space-y-2 text-base leading-7 text-ink" {...props} />;
  },
  li({ node: _node, ...props }) {
    return <li className="pl-1" {...props} />;
  },
  blockquote({ node: _node, ...props }) {
    return <blockquote className="border-l-2 border-signal/50 pl-4 text-ink-mid" {...props} />;
  },
  code({ node: _node, className, children, ...props }) {
    const isBlock = className?.startsWith("language-") || String(children).includes("\n");
    if (isBlock) {
      return (
        <code className={`block overflow-x-auto p-4 text-sm leading-6 text-ink ${className ?? ""}`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="rounded border border-line-strong bg-panel px-1.5 py-0.5 text-sm text-signal-bright" {...props}>
        {children}
      </code>
    );
  },
  pre({ node: _node, ...props }) {
    return <pre className="overflow-x-auto rounded-md border border-line bg-canvas" {...props} />;
  },
  table({ node: _node, ...props }) {
    return (
      <div className="overflow-x-auto rounded-md border border-line">
        <table
          className="w-full border-collapse text-left text-sm text-ink-mid"
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
        className="border-b border-line bg-panel px-3 py-2 font-semibold text-ink"
        {...cleanTableElementProps(props)}
      />
    );
  },
  td({ node: _node, ...props }) {
    return <td className="border-b border-line px-3 py-2 align-top" {...cleanTableElementProps(props)} />;
  },
  img({ node: _node, alt, src, ...props }) {
    return (
      <img
        alt={alt ?? ""}
        className={readmeImageClassName({
          src: typeof src === "string" ? src : undefined,
          width: props.width,
          height: props.height,
        })}
        loading="lazy"
        referrerPolicy="no-referrer"
        src={proxiedImageUrl(typeof src === "string" ? src : undefined)}
        {...props}
      />
    );
  },
  hr({ node: _node, ...props }) {
    return <hr className="border-line" {...props} />;
  },
  span({ node: _node, ...props }) {
    return <span {...props} />;
  },
};

function MarkdownArticle({ markdown }: { markdown: string }) {
  return (
    <div className="space-y-5">
      <ReactMarkdown
        components={markdownComponents}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, articleSanitizeSchema]]}
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
  const markdown = originalMarkdown?.trim();
  const hasOriginalMarkdown = Boolean(markdown);
  const hasTranslation = translatedBlocks.length > 0 && !hasOriginalMarkdown;
  const defaultMode = hasOriginalMarkdown ? "original" : "translated";
  const [mode, setMode] = useState<"translated" | "original">(
    hasTranslation ? defaultMode : "original",
  );
  const isOriginal = mode === "original";
  const blocks = isOriginal ? originalBlocks : translatedBlocks;

  return (
    <article className="mt-10 border-t border-line pt-8">
      <div className="flex items-center justify-between gap-4 border-b border-line pb-4">
        <div className="text-sm font-semibold text-ink-mid">
          {isOriginal ? "原文" : "AI 翻译 · 中文"}
        </div>
        {hasTranslation ? (
          <button
            type="button"
            className="rounded-none border border-transparent px-4 py-2 text-sm font-semibold text-signal transition hover:border-signal/40 hover:text-signal-bright"
            onClick={() => setMode(isOriginal ? "translated" : "original")}
          >
            {isOriginal ? "显示译文" : "显示原文"}
          </button>
        ) : null}
      </div>
      <div className="mt-6 space-y-6">
        {isOriginal && markdown ? <MarkdownArticle markdown={markdown} /> : blocks.map(renderOriginalBlock)}
      </div>
    </article>
  );
}
