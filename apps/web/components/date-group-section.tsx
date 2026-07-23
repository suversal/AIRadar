"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

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
    // the header's own class is `sticky top-16 ... lg:top-0` - the sentinel
    // must scroll past that same offset before we call it "stuck", or the
    // shadow would pop in ~64px early on mobile/tablet and late on desktop
    const query = window.matchMedia("(min-width: 1024px)");
    let observer: IntersectionObserver | null = null;
    function setup() {
      observer?.disconnect();
      const offset = query.matches ? 0 : 64;
      observer = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting), {
        rootMargin: `-${offset + 1}px 0px 0px 0px`,
        threshold: 0,
      });
      observer.observe(sentinel as HTMLDivElement);
    }
    setup();
    query.addEventListener("change", setup);
    return () => {
      observer?.disconnect();
      query.removeEventListener("change", setup);
    };
  }, []);

  return (
    <div>
      <div ref={sentinelRef} aria-hidden className="h-px" />
      <div
        className={`sticky top-16 z-10 -mx-5 flex items-center gap-3 border-b bg-canvas px-5 py-3 text-sm font-semibold text-ink-mid transition-shadow md:-mx-9 md:px-9 lg:top-0 ${
          stuck ? "border-line shadow-[0_4px_8px_-6px_rgba(0,0,0,0.35)]" : "border-transparent"
        }`}
      >
        <span>{dateLabel}</span>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-ink-dim transition hover:bg-panel-soft hover:text-ink"
        >
          折叠
          <ChevronDown
            aria-hidden
            className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`}
            strokeWidth={2}
          />
        </button>
        <span className="text-ink-dim">
          {weekday} · {count} 条
        </span>
      </div>
      {open ? (
        <div className="relative mt-3 grid gap-3 md:border-l md:border-line/60 md:pl-6">{children}</div>
      ) : null}
    </div>
  );
}
