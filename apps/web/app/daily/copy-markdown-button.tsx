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
    <div>
      <button
        type="button"
        onClick={copyMarkdown}
        className="w-full rounded-md border border-signal bg-signal px-3 py-2 text-sm font-semibold text-canvas"
      >
        {copyState === "copied" ? "已复制" : "复制 Markdown"}
      </button>
      <p className="mt-2 min-h-5 text-sm text-ink-mid" aria-live="polite">
        {copyState === "failed" ? "复制失败，请手动选择页面内容。" : ""}
      </p>
    </div>
  );
}
