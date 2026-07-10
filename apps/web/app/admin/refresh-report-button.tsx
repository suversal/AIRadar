"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type RefreshState = "idle" | "running" | "done" | "failed";
type RefreshJob = {
  job_id?: string;
  status?: string;
  detail?: string;
  error?: string;
  result?: {
    report_date?: string;
    article_count?: number;
    selected_count?: number;
  };
};

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 240;

function sleep(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function readJson(response: Response) {
  const text = await response.text();
  if (!text) {
    throw new Error("刷新接口返回空响应，已避免 Unexpected end of JSON input。");
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("刷新接口返回了非 JSON 响应。");
  }
}

export function RefreshReportButton() {
  const router = useRouter();
  const [refreshState, setRefreshState] = useState<RefreshState>("idle");
  const [message, setMessage] = useState("");

  async function refreshReport() {
    const url = "/api/refresh-latest?limit=100&top_n=30";
    setRefreshState("running");
    setMessage("正在启动数据同步...");
    try {
      const response = await fetch(url, { method: "POST" });
      const payload: RefreshJob = await readJson(response);
      if (!response.ok) {
        throw new Error(payload.detail ?? "刷新失败");
      }
      if (!payload.job_id) {
        throw new Error("刷新任务没有返回 job_id。");
      }
      setMessage("刷新任务已启动，正在等待结果...");
      const result = await pollRefreshJob(payload.job_id);
      setRefreshState("done");
      setMessage(
        `已刷新 ${result.report_date}，展示 ${result.article_count ?? 0} 条，入选 ${
          result.selected_count ?? 0
        } 条。`,
      );
      router.refresh();
    } catch (error) {
      setRefreshState("failed");
      setMessage(error instanceof Error ? error.message : "刷新失败");
    }
  }

  async function pollRefreshJob(jobId: string) {
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      await sleep(POLL_INTERVAL_MS);
      const response = await fetch(`/api/refresh-latest?job_id=${encodeURIComponent(jobId)}`);
      const payload: RefreshJob = await readJson(response);
      if (!response.ok) {
        throw new Error(payload.detail ?? "刷新状态查询失败");
      }
      if (payload.status === "failed") {
        throw new Error(payload.error ?? "刷新任务失败");
      }
      if (payload.status === "succeeded" && payload.result) {
        return payload.result;
      }
      setMessage(`刷新任务运行中，已等待 ${(attempt + 1) * 3} 秒...`);
    }
    throw new Error("刷新任务超时，请稍后查看页面或重新刷新。");
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={() => refreshReport()}
        disabled={refreshState === "running"}
        className="rounded-md border border-signal bg-signal px-4 py-2 text-sm font-semibold text-canvas hover:bg-signal-bright disabled:cursor-not-allowed disabled:opacity-60"
      >
        {refreshState === "running" ? "同步中..." : "刷新数据"}
      </button>
      <p className="min-h-5 text-sm text-ink-mid" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
