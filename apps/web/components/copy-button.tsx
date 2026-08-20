"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * 复制按钮。
 *
 * /agent 页上大半内容是「照抄进终端或配置文件」的东西，让人手选一段多行
 * JSON 是最容易出错的一步——漏一个花括号、多带一个行号，接入就失败。
 */
export function CopyButton({ text, label = "复制" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

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
        document.execCommand("copy");
        document.body.removeChild(area);
      }
      setCopied(true);
    } catch {
      // 复制失败不做提示：内容本来就在屏幕上，手选即可
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? "已复制" : label}
      className="inline-flex shrink-0 items-center gap-1 rounded border border-line bg-canvas px-2 py-1 text-xs text-ink-mid transition-colors hover:border-signal/50 hover:text-signal"
    >
      {copied ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
      {copied ? "已复制" : label}
    </button>
  );
}
