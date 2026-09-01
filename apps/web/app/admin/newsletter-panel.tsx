"use client";

import { useState } from "react";

export type NewsletterOverview = {
  subscribers: Record<string, number>;
  deliveries: Record<string, number>;
  latest_finalized_period: string | null;
};

export function NewsletterPanel({ initial }: { initial: NewsletterOverview | null }) {
  const [overview, setOverview] = useState(initial);
  const [working, setWorking] = useState<"scheduled" | "latest_all_active" | null>(null);
  const [notice, setNotice] = useState("");
  const [noticeIsError, setNoticeIsError] = useState(false);

  async function dispatch(mode: "scheduled" | "latest_all_active") {
    if (
      mode === "latest_all_active" &&
      !window.confirm(
        `确认向尚未收到 ${overview?.latest_finalized_period ?? "最新一期"} 的有效订阅者主动投递？已发送过的地址会自动跳过。`,
      )
    ) {
      return;
    }
    setWorking(mode);
    setNotice("");
    setNoticeIsError(false);
    try {
      const response = await fetch("/api/admin-proxy/newsletter/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "投递失败");
      setNotice(
        `${payload.period_key ?? "暂无封版周报"}：发送 ${payload.sent}，失败 ${payload.failed}，跳过 ${payload.skipped}`,
      );
      const latest = await fetch("/api/admin-proxy/newsletter", { cache: "no-store" });
      if (latest.ok) setOverview(await latest.json());
    } catch (caught) {
      setNoticeIsError(true);
      setNotice(caught instanceof Error ? caught.message : "投递失败");
    } finally {
      setWorking(null);
    }
  }

  const active = overview?.subscribers.active ?? 0;
  const pending = overview?.subscribers.pending ?? 0;
  const sent = overview?.deliveries.sent ?? 0;
  const failed = overview?.deliveries.failed ?? 0;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-ink">周报邮件</h2>
          <p className="mt-1 text-xs leading-5 text-ink-dim">
            调度器只发送已封版、且尚未投递过的期次；手动触发同样不会重复发送。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={working !== null || !overview}
            onClick={() => dispatch("scheduled")}
            className="rounded-md border border-line-strong bg-canvas/40 px-4 py-2 text-sm font-semibold text-ink-mid hover:border-signal hover:text-signal disabled:cursor-not-allowed disabled:opacity-60"
          >
            {working === "scheduled" ? "检查中…" : "检查待投递"}
          </button>
          <button
            type="button"
            disabled={working !== null || !overview || active === 0 || !overview.latest_finalized_period}
            onClick={() => dispatch("latest_all_active")}
            className="rounded-md border border-signal bg-signal px-4 py-2 text-sm font-semibold text-canvas hover:bg-signal-bright disabled:cursor-not-allowed disabled:opacity-60"
          >
            {working === "latest_all_active" ? "投递中…" : "主动投递最新周报"}
          </button>
        </div>
      </div>
      {overview ? (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            ["有效订阅", active],
            ["待确认", pending],
            ["已发送", sent],
            ["失败", failed],
            ["最新封版", overview.latest_finalized_period ?? "--"],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-line bg-canvas/35 px-3 py-3">
              <div className="readout text-lg font-semibold text-ink">{value}</div>
              <div className="mt-1 text-xs text-ink-dim">{label}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm text-danger">订阅概览不可用，请先检查数据库迁移。</p>
      )}
      {notice ? (
        <p
          role={noticeIsError ? "alert" : "status"}
          className={`mt-3 text-xs leading-5 ${noticeIsError ? "text-danger" : "text-ink-mid"}`}
        >
          {notice}
        </p>
      ) : null}
    </div>
  );
}
