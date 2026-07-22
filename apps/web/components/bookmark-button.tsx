"use client";

import { useEffect, useState } from "react";
import { Bookmark } from "lucide-react";
import { isBookmarked, toggleBookmark } from "@/lib/bookmarks";

export function BookmarkButton({
  eventId,
  labeled = false,
  className = "",
  onChange,
}: {
  eventId: string;
  labeled?: boolean;
  className?: string;
  onChange?: (bookmarked: boolean) => void;
}) {
  const [bookmarked, setBookmarked] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setBookmarked(isBookmarked(eventId));
    setReady(true);
  }, [eventId]);

  return (
    <button
      type="button"
      aria-pressed={bookmarked}
      aria-label={bookmarked ? "取消收藏" : "收藏"}
      title={bookmarked ? "取消收藏" : "收藏"}
      // cards sometimes wrap the title in a link; stop the click from also
      // navigating or bubbling into another handler
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        const next = toggleBookmark(eventId);
        setBookmarked(next);
        onChange?.(next);
      }}
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border text-xs font-semibold transition ${
        labeled ? "min-h-10 px-3 py-2" : "h-10 w-10"
      } ${
        bookmarked
          ? "border-signal/60 bg-signal/15 text-signal-bright"
          : "border-line-strong text-ink-mid hover:border-signal/40 hover:text-signal"
      } ${ready ? "" : "opacity-0"} ${className}`}
    >
      <Bookmark aria-hidden className="h-4 w-4" strokeWidth={1.75} fill={bookmarked ? "currentColor" : "none"} />
      {labeled ? (bookmarked ? "已收藏" : "收藏") : null}
    </button>
  );
}
