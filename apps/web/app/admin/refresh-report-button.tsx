"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

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

function formatElapsed(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
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
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [resultCount, setResultCount] = useState<number | null>(null);
  const [errorDetail, setErrorDetail] = useState("");
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    if (refreshState !== "running" || startedAt.current === null) return;
    const update = () => {
      setElapsedSeconds(Math.floor((Date.now() - (startedAt.current ?? Date.now())) / 1000));
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [refreshState]);

  async function refreshReport() {
    const url = "/api/refresh-latest";
    startedAt.current = Date.now();
    setElapsedSeconds(0);
    setResultCount(null);
    setErrorDetail("");
    setRefreshState("running");
    try {
      const response = await fetch(url, { method: "POST" });
      const payload: RefreshJob = await readJson(response);
      if (!response.ok) {
        throw new Error(payload.detail ?? "刷新失败");
      }
      if (!payload.job_id) {
        throw new Error("刷新任务没有返回 job_id。");
      }
      const result = await pollRefreshJob(payload.job_id);
      setElapsedSeconds(Math.floor((Date.now() - (startedAt.current ?? Date.now())) / 1000));
      setResultCount(result.article_count ?? result.selected_count ?? 0);
      setRefreshState("done");
      router.refresh();
    } catch (error) {
      setElapsedSeconds(Math.floor((Date.now() - (startedAt.current ?? Date.now())) / 1000));
      setErrorDetail(error instanceof Error ? error.message : "刷新失败");
      setRefreshState("failed");
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
    }
    throw new Error("刷新任务超时，请稍后查看页面或重新刷新。");
  }

  const label =
    refreshState === "running"
      ? `同步中 ${formatElapsed(elapsedSeconds)}`
      : refreshState === "done"
        ? `完成 · ${resultCount ?? 0} 条 · ${formatElapsed(elapsedSeconds)}`
        : refreshState === "failed"
          ? `失败 · ${formatElapsed(elapsedSeconds)}`
          : "手动同步";

  return (
    <button
      type="button"
      title={errorDetail || undefined}
      aria-live="polite"
      onClick={() => refreshReport()}
      disabled={refreshState === "running"}
      className="min-w-40 rounded-md border border-signal bg-signal px-4 py-2 text-sm font-semibold text-canvas hover:bg-signal-bright disabled:cursor-not-allowed disabled:opacity-60"
    >
      {label}
    </button>
  );
}
