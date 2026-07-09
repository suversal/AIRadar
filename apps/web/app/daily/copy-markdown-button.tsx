"use client";

import { useState } from "react";

type CopyState = "idle" | "copied" | "failed";

export function CopyMarkdownButton({ markdown }: { markdown: string }) {
  const [copyState, setCopyState] = useState<CopyState>("idle");

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={copyMarkdown}
        className="rounded-md border border-signal bg-signal px-4 py-2 text-sm font-semibold text-canvas hover:border-signal-bright hover:bg-signal-bright"
      >
        {copyState === "copied" ? "已复制 ✓" : "复制 Markdown"}
      </button>
      <span className="text-xs text-ink-dim" aria-live="polite">
        {copyState === "failed" ? "复制失败，请手动选择页面内容" : ""}
      </span>
    </div>
  );
}
