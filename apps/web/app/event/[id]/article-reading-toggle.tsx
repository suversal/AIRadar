"use client";

import { useState } from "react";
import type { OriginalBlock } from "@/lib/api";

type ArticleReadingToggleProps = {
  originalBlocks: OriginalBlock[];
  translatedBlocks: OriginalBlock[];
};

function renderBlock(block: OriginalBlock, index: number) {
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

export function ArticleReadingToggle({
  originalBlocks,
  translatedBlocks,
}: ArticleReadingToggleProps) {
  const [mode, setMode] = useState<"translated" | "original">("translated");
  const isOriginal = mode === "original";
  const blocks = isOriginal ? originalBlocks : translatedBlocks;

  return (
    <article className="mt-10 border-t border-slate-800 pt-8">
      <div className="flex items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="text-sm font-semibold text-slate-500">
          {isOriginal ? "原文" : "AI 翻译 · 中文"}
        </div>
        <button
          type="button"
          className="rounded-none border border-transparent px-4 py-2 text-sm font-semibold text-cyan-300 transition hover:border-cyan-400/40 hover:text-cyan-200"
          onClick={() => setMode(isOriginal ? "translated" : "original")}
        >
          {isOriginal ? "显示译文" : "显示原文"}
        </button>
      </div>
      <div className="mt-6 space-y-6">{blocks.map(renderBlock)}</div>
    </article>
  );
}
