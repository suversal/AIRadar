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
  // X avatars are already restricted to Twitter's image CDN by the upstream
  // contract. Loading this one host in the browser also avoids local proxy
  // fake-IP DNS (198.18/15), while every other remote avatar stays proxied.
  const imageUrl = /^https:\/\/pbs\.twimg\.com\//i.test(src)
    ? src
    : proxiedImageUrl(src);
  return (
    <img
      src={imageUrl}
      alt={`${name}头像`}
      className={`${sizeClassName} shrink-0 rounded-full border border-line-strong object-cover`}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
