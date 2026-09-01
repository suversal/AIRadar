"use client";

import { useState } from "react";

type Status = "idle" | "submitting" | "sent" | "error";

export function WeeklySubscribeForm({ source = "weekly_page" }: { source?: string }) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  function validate() {
    const input = email.trim();
    if (!input || !input.includes("@")) {
      setStatus("error");
      setError("请输入有效的邮箱地址。");
      return false;
    }
    return true;
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validate()) return;
    setStatus("submitting");
    setError("");
    try {
      const response = await fetch("/api/newsletter/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), source }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "订阅失败，请稍后再试。");
      setEmail("");
      setStatus("sent");
    } catch (caught) {
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "订阅失败，请稍后再试。");
    }
  }

  return (
    <section
      aria-labelledby="weekly-subscribe-title"
      className="mt-8 border border-line-strong bg-panel/55 px-5 py-5 md:flex md:items-center md:justify-between md:gap-8 md:px-6"
    >
      <div className="max-w-md">
        <p className="readout text-[10px] font-semibold uppercase tracking-[0.16em] text-signal">
          Weekly by email
        </p>
        <h2 id="weekly-subscribe-title" className="mt-2 text-lg font-semibold text-ink">
          每周一封，把信号送到邮箱
        </h2>
        <p className="mt-1 text-sm leading-6 text-ink-mid">
          只发送已经封版的 AI 周报。提交后需要在邮件中确认，随时可以一键退订。
        </p>
      </div>

      {status === "sent" ? (
        <div className="mt-5 min-w-0 border-l-2 border-signal pl-4 text-sm leading-6 text-ink-mid md:mt-0 md:w-[330px]">
          <p className="font-semibold text-signal-bright">请查收确认邮件</p>
          <p>确认后才会开始收到周报；没有看到时也请检查垃圾邮件目录。</p>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-5 md:mt-0 md:w-[360px]" noValidate>
          <label htmlFor="weekly-subscribe-email" className="text-xs font-semibold text-ink">
            邮箱地址
          </label>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input
              id="weekly-subscribe-email"
              type="email"
              autoComplete="email"
              inputMode="email"
              required
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                if (status === "error") setStatus("idle");
              }}
              onBlur={validate}
              aria-invalid={status === "error"}
              aria-describedby={status === "error" ? "weekly-subscribe-error" : undefined}
              placeholder="you@example.com"
              className="min-h-11 min-w-0 flex-1 border border-line bg-canvas px-3 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal focus-visible:ring-2 focus-visible:ring-signal/25"
            />
            <button
              type="submit"
              disabled={status === "submitting"}
              className="min-h-11 shrink-0 bg-signal px-5 text-sm font-semibold text-canvas transition-colors hover:bg-signal-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal disabled:cursor-not-allowed disabled:opacity-60"
            >
              {status === "submitting" ? "提交中…" : "订阅周报"}
            </button>
          </div>
          {status === "error" ? (
            <p id="weekly-subscribe-error" role="alert" className="mt-2 text-xs text-danger">
              {error}
            </p>
          ) : (
            <p className="mt-2 text-[11px] leading-5 text-ink-dim">不会订阅日报或月报，也不会分享邮箱。</p>
          )}
        </form>
      )}
    </section>
  );
}
