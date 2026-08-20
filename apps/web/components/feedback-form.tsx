"use client";

import { useState } from "react";

const MAX_MESSAGE_LENGTH = 2000;

type Status = "idle" | "submitting" | "sent" | "error";

export function FeedbackForm({ initialMessage = "" }: { initialMessage?: string }) {
  const [message, setMessage] = useState(initialMessage);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorText, setErrorText] = useState("");

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed) {
      setStatus("error");
      setErrorText("先写点什么再发送吧。");
      return;
    }

    setStatus("submitting");
    setErrorText("");
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          email: email.trim() || undefined,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "发送失败，请稍后再试。");
      }
      setStatus("sent");
      setMessage("");
      setEmail("");
    } catch (error) {
      setStatus("error");
      setErrorText(error instanceof Error ? error.message : "发送失败，请稍后再试。");
    }
  }

  if (status === "sent") {
    return (
      <div className="rounded-md border border-signal/30 bg-signal/5 p-6 text-center text-sm leading-6 text-ink-mid">
        <p className="text-base font-semibold text-signal-bright">已收到，谢谢！</p>
        <p className="mt-2">我会认真看每一条反馈。</p>
        <button
          type="button"
          className="mt-4 text-sm text-signal underline hover:text-signal-bright"
          onClick={() => setStatus("idle")}
        >
          再写一条
        </button>
      </div>
    );
  }

  return (
    <form id="feedback-form" onSubmit={handleSubmit} className="scroll-mt-4 space-y-4">
      <div>
        <label htmlFor="feedback-message" className="text-sm font-semibold text-ink">
          想说点什么？
        </label>
        <textarea
          id="feedback-message"
          className="mt-2 min-h-40 w-full rounded-md border border-line bg-canvas px-3 py-2.5 text-sm leading-6 text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
          placeholder="比如：某条情报的评分不准确、希望增加的信源或功能、页面显示问题……"
          maxLength={MAX_MESSAGE_LENGTH}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <div className="mt-1 text-right text-xs text-ink-dim">
          {message.length} / {MAX_MESSAGE_LENGTH}
        </div>
      </div>

      <div>
        <label htmlFor="feedback-email" className="text-sm font-semibold text-ink">
          邮箱 <span className="font-normal text-ink-dim">（选填）</span>
        </label>
        <input
          id="feedback-email"
          type="email"
          className="mt-2 min-h-11 w-full rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
          placeholder="留下邮箱，方便我回信联系你"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>

      {status === "error" ? (
        <p className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {errorText}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={status === "submitting"}
        className="min-h-11 rounded-md border border-signal/40 bg-signal/10 px-6 py-2.5 text-sm font-semibold text-signal transition hover:border-signal/60 hover:text-signal-bright disabled:cursor-not-allowed disabled:opacity-60"
      >
        {status === "submitting" ? "发送中…" : "发送反馈"}
      </button>
    </form>
  );
}
