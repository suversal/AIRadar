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
        className={`sticky top-0 z-20 flex min-h-11 min-w-0 items-center gap-2 border-b bg-canvas/95 text-sm font-semibold text-ink-mid backdrop-blur-sm transition-shadow md:min-h-12 md:gap-3 ${
          stuck ? "border-line shadow-[0_7px_12px_-12px_rgba(0,0,0,0.55)]" : "border-transparent"
        }`}
      >
        <span className="editorial-display shrink-0 text-lg tracking-[-0.03em] text-ink md:text-xl">{dateLabel}</span>
        <span className="readout min-w-0 truncate text-[10px] uppercase tracking-[0.12em] text-ink-dim md:text-[11px]">
          {weekday} / {count} entries
        </span>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="ml-auto flex shrink-0 items-center gap-1 border-b border-transparent px-1.5 py-1 text-xs text-ink-dim transition hover:border-line-strong hover:text-ink lg:ml-0"
        >
          {open ? "折叠" : "展开"}
          <ChevronDown
            aria-hidden
            className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`}
            strokeWidth={2}
          />
        </button>
        <button
          type="button"
          aria-hidden={!stuck}
          aria-label="打开导航菜单"
          tabIndex={stuck ? 0 : -1}
          onClick={() => window.dispatchEvent(new Event(MOBILE_NAV_OPEN_EVENT))}
          className={`flex h-10 w-10 shrink-0 items-center justify-center transition-opacity duration-150 lg:ml-auto lg:hidden ${
            stuck ? "opacity-100" : "pointer-events-none opacity-0"
          }`}
        >
          <Menu aria-hidden className="h-5 w-5" strokeWidth={1.75} />
        </button>
      </div>
      {open ? (
        <div className="relative mt-1.5 grid gap-2 md:mt-2 md:border-l md:border-line/70 md:pl-6">{children}</div>
      ) : null}
    </div>
  );
}
