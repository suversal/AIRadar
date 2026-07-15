"use client";

import { useState } from "react";

type ArticleImageProps = {
  src: string;
  alt: string;
  className: string;
  fallbackUrl?: string;
};

export function ArticleImage({ src, alt, className, fallbackUrl }: ArticleImageProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="flex min-h-36 w-full flex-col items-center justify-center gap-3 rounded-md border border-line bg-panel p-6 text-center text-sm text-ink-mid">
        <span>图片加载失败</span>
        {fallbackUrl ? (
          <a
            className="font-semibold text-signal hover:text-signal-bright"
            href={fallbackUrl}
            rel="noopener noreferrer"
            target="_blank"
          >
            查看 Telegram 原帖 ↗
          </a>
        ) : null}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
