"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

type CopyStatus = "idle" | "copied" | "error";

/**
 * 复制按钮。
 *
 * /agent 页上大半内容是「照抄进终端或配置文件」的东西，让人手选一段多行
 * JSON 是最容易出错的一步——漏一个花括号、多带一个行号，接入就失败。
 */
export function CopyButton({ text, label = "复制" }: { text: string; label?: string }) {
  const [status, setStatus] = useState<CopyStatus>("idle");

  useEffect(() => {
    if (status === "idle") return;
    const timer = setTimeout(() => setStatus("idle"), status === "copied" ? 2000 : 3500);
    return () => clearTimeout(timer);
  }, [status]);

  async function copy() {
    try {
      // clipboard API 只在安全上下文可用（https 或 localhost）。
      // 走 http 访问时退回 execCommand，别让按钮变成死的。
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        const copied = document.execCommand("copy");
        document.body.removeChild(area);
        if (!copied) {
          throw new Error("copy command failed");
        }
      }
      setStatus("copied");
    } catch {
      setStatus("error");
    }
  }

  const message = status === "copied" ? "已复制" : status === "error" ? "复制失败" : label;

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={status === "error" ? "复制失败，请手动选择文本" : message}
      title={status === "error" ? "复制失败，请手动选择文本" : undefined}
      className={`inline-flex shrink-0 items-center gap-1 rounded border bg-canvas px-2 py-1 text-xs transition-colors ${
        status === "error"
          ? "border-danger/50 text-danger"
          : "border-line text-ink-mid hover:border-signal/50 hover:text-signal"
      }`}
    >
      {status === "copied" ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
      <span aria-live="polite">{message}</span>
    </button>
  );
}
