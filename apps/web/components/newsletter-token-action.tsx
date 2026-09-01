"use client";

import { useState } from "react";

type Action = "confirm" | "unsubscribe";
type Status = "idle" | "working" | "done" | "error";

const COPY = {
  confirm: {
    button: "确认订阅周报",
    working: "确认中…",
    done: "订阅已确认",
    detail: "从下一期封版周报开始，你会收到邮件。",
  },
  unsubscribe: {
    button: "确认取消订阅",
    working: "处理中…",
    done: "已取消订阅",
    detail: "之后不会再向这个邮箱发送周报。",
  },
} as const;

export function NewsletterTokenAction({ action, token }: { action: Action; token: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const copy = COPY[action];

  async function run() {
    if (!token) {
      setStatus("error");
      setError("链接缺少必要参数，请重新打开邮件中的完整链接。");
      return;
    }
    setStatus("working");
    setError("");
    try {
      const response = await fetch(`/api/newsletter/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "操作失败，请稍后再试。");
      setStatus("done");
    } catch (caught) {
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "操作失败，请稍后再试。");
    }
  }

  if (status === "done") {
    return (
      <div className="border-l-2 border-signal bg-signal/5 px-5 py-4" role="status">
        <p className="font-semibold text-signal-bright">{copy.done}</p>
        <p className="mt-1 text-sm leading-6 text-ink-mid">{copy.detail}</p>
        <a className="mt-4 inline-block text-sm font-semibold text-signal hover:text-signal-bright" href="/weekly">
          返回周报 →
        </a>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={run}
        disabled={status === "working"}
        className="min-h-11 bg-signal px-6 text-sm font-semibold text-canvas hover:bg-signal-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal disabled:cursor-not-allowed disabled:opacity-60"
      >
        {status === "working" ? copy.working : copy.button}
      </button>
      {status === "error" ? (
        <p role="alert" className="mt-4 border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
