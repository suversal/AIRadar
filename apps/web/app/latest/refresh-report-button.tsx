"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type RefreshState = "idle" | "running" | "done" | "failed";
type RefreshMode = "digest" | "complete";

export function RefreshReportButton() {
  const router = useRouter();
  const [refreshState, setRefreshState] = useState<RefreshState>("idle");
  const [activeMode, setActiveMode] = useState<RefreshMode | null>(null);
  const [message, setMessage] = useState("");

  async function refreshReport(mode: RefreshMode) {
    const url =
      mode === "complete"
        ? "/api/refresh-latest?limit=100&top_n=30"
        : "/api/refresh-latest?limit=100&top_n=12";
    setRefreshState("running");
    setActiveMode(mode);
    setMessage(mode === "complete" ? "正在生成较完整成果..." : "正在抓取并生成日报...");
    try {
      const response = await fetch(url, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? "刷新失败");
      }
      setRefreshState("done");
      setMessage(
        `已刷新 ${payload.report_date}，展示 ${payload.article_count ?? 0} 条，入选 ${
          payload.selected_count ?? 0
        } 条。`,
      );
      router.refresh();
    } catch (error) {
      setRefreshState("failed");
      setMessage(error instanceof Error ? error.message : "刷新失败");
    } finally {
      setActiveMode(null);
    }
  }

  return (
    <div>
      <div className="grid gap-2">
        <button
          type="button"
          onClick={() => refreshReport("digest")}
          disabled={refreshState === "running"}
          className="w-full rounded-md border border-[var(--accent)] bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {refreshState === "running" && activeMode === "digest" ? "刷新中..." : "刷新最新日报"}
        </button>
        <button
          type="button"
          onClick={() => refreshReport("complete")}
          disabled={refreshState === "running"}
          className="w-full rounded-md border border-[var(--line)] px-3 py-2 text-sm font-semibold text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {refreshState === "running" && activeMode === "complete" ? "生成中..." : "刷新完整成果"}
        </button>
      </div>
      <p className="mt-2 min-h-5 text-sm text-[var(--muted)]" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
