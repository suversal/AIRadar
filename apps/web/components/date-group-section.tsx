"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Menu } from "lucide-react";
import { MOBILE_NAV_OPEN_EVENT } from "./mobile-nav-events";

/** Date-grouped feed section: sticky "7/23 折叠 15条" header + its rows.
 *  Shared by /latest and /all so the sticky-shadow behavior below can't
 *  drift between the two feeds the way the header markup itself already
 *  did once. Uses a plain header + controlled `open` state (not
 *  <details>/<summary>) so only the fold button is clickable - a native
 *  <summary> makes the whole row a toggle target, which read as an
 *  accidental hit-zone over the date/count text. */
export function DateGroupSection({
  dateLabel,
  weekday,
  count,
  children,
}: {
  dateLabel: string;
  weekday: string;
  count: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const [stuck, setStuck] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    // The brand header now scrolls away on mobile, so every breakpoint pins
    // the date summary directly to the viewport edge.
    const observer = new IntersectionObserver(
      ([entry]) => {
        setStuck(!entry.isIntersecting && entry.boundingClientRect.top <= 0);
      },
      {
        rootMargin: "-1px 0px 0px 0px",
        threshold: 0,
      },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);

  return (
    <div>
      <div ref={sentinelRef} aria-hidden className="h-px" />
      <div
        className={`sticky top-0 z-20 -mx-5 flex h-10 min-w-0 items-center gap-2 border-b bg-canvas pl-5 pr-5 text-sm font-semibold text-ink-mid transition-shadow md:-mx-9 md:h-12 md:gap-3 md:px-9 lg:h-auto lg:py-3 ${
          stuck ? "border-line shadow-[0_4px_8px_-6px_rgba(0,0,0,0.35)]" : "border-transparent"
        }`}
      >
        <span className="shrink-0">{dateLabel}</span>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-ink-dim transition hover:bg-panel-soft hover:text-ink"
        >
          折叠
          <ChevronDown
            aria-hidden
            className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`}
            strokeWidth={2}
          />
        </button>
        <span className="min-w-0 truncate text-ink-dim">
          {weekday} · {count} 条
        </span>
        <button
          type="button"
          aria-hidden={!stuck}
          aria-label="打开导航菜单"
          tabIndex={stuck ? 0 : -1}
          onClick={() => window.dispatchEvent(new Event(MOBILE_NAV_OPEN_EVENT))}
          className={`ml-auto flex h-10 w-10 shrink-0 items-center justify-center transition-opacity duration-150 lg:hidden ${
            stuck ? "opacity-100" : "pointer-events-none opacity-0"
          }`}
        >
          <Menu aria-hidden className="h-5 w-5" strokeWidth={1.75} />
        </button>
      </div>
      {open ? (
        <div className="relative mt-2 grid gap-2 md:mt-3 md:gap-3 md:border-l md:border-line/60 md:pl-6">{children}</div>
      ) : null}
    </div>
  );
}
