"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type RefreshState = "idle" | "running" | "done" | "failed";

export function RefreshReportButton() {
  const router = useRouter();
  const [refreshState, setRefreshState] = useState<RefreshState>("idle");
  const [message, setMessage] = useState("");

  async function refreshReport() {
    setRefreshState("running");
    setMessage("正在抓取并生成日报...");
    try {
      const response = await fetch("/api/refresh-latest", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? "刷新失败");
      }
      setRefreshState("done");
      setMessage(`已刷新 ${payload.report_date}，精选 ${payload.article_count ?? 0} 条。`);
      router.refresh();
    } catch (error) {
      setRefreshState("failed");
      setMessage(error instanceof Error ? error.message : "刷新失败");
    }
  }

  return (
    <div>
      <button
        type="button"
        onClick={refreshReport}
        disabled={refreshState === "running"}
        className="w-full rounded-md border border-[var(--accent)] bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {refreshState === "running" ? "刷新中..." : "刷新最新日报"}
      </button>
      <p className="mt-2 min-h-5 text-sm text-[var(--muted)]" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
