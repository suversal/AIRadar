"use client";

import { useState } from "react";
import { proxiedImageUrl } from "@/lib/images";

export function AuthorAvatar({
  name,
  src,
  sizeClassName = "size-11",
}: {
  name: string;
  src?: string;
  sizeClassName?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <span
        className={`flex ${sizeClassName} shrink-0 items-center justify-center rounded-full border border-line-strong bg-panel-soft text-base font-semibold text-signal-bright`}
      >
        {name.trim().slice(0, 1).toUpperCase() || "?"}
      </span>
    );
  }
  return (
    <img
      src={proxiedImageUrl(src)}
      alt={`${name}头像`}
      className={`${sizeClassName} shrink-0 rounded-full border border-line-strong object-cover`}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
