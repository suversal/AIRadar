"use client";

import { useEffect, useRef, useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";

export type MobileSourceFilterOption = {
  href: string;
  label: string;
  selected: boolean;
  value: string;
};

export function MobileSourceFilter({
  options,
}: {
  options: MobileSourceFilterOption[];
}) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const activeOption = options.find((option) => option.selected && option.value);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.body.classList.add("mobile-source-filter-open");
    dialogRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.classList.remove("mobile-source-filter-open");
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <>
      <button
        aria-controls="mobile-source-filter"
        aria-expanded={open}
        className={`flex min-h-11 shrink-0 items-center gap-1.5 rounded-md border px-3 text-sm font-medium ${
          activeOption
            ? "border-signal/55 bg-signal/15 text-signal"
            : "border-signal/45 bg-signal/5 text-signal hover:bg-signal/10"
        }`}
        onClick={() => setOpen(true)}
        type="button"
      >
        <SlidersHorizontal aria-hidden className="h-4 w-4" strokeWidth={1.75} />
        筛选
        {activeOption ? (
          <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-signal text-[10px] font-semibold text-canvas">
            1
          </span>
        ) : null}
      </button>

      {open ? (
        <button
          aria-label="关闭来源筛选"
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setOpen(false)}
          type="button"
        />
      ) : null}

      {open ? (
        <section
          aria-label="来源筛选"
          aria-modal="true"
          id="mobile-source-filter"
          ref={dialogRef}
          role="dialog"
          tabIndex={-1}
          className="fixed inset-x-0 bottom-0 z-50 rounded-t-xl border border-line bg-panel px-4 pt-4 pb-[calc(1rem+env(safe-area-inset-bottom))] outline-none md:hidden"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-ink">来源筛选</h2>
              <p className="mt-1 text-xs text-ink-dim">选择内容的主要信源类型</p>
            </div>
            <button
              aria-label="关闭"
              className="flex h-9 w-9 items-center justify-center rounded-md border border-line text-ink-mid hover:text-ink"
              onClick={() => setOpen(false)}
              type="button"
            >
              <X aria-hidden className="h-4.5 w-4.5" strokeWidth={1.75} />
            </button>
          </div>

          <nav aria-label="选择来源" className="mt-4 grid grid-cols-2 gap-2">
            {options.map((option) => (
              <a
                key={option.value || "all-source"}
                aria-current={option.selected ? "true" : undefined}
                className={`flex min-h-12 items-center justify-center rounded-md border px-3 py-2 text-sm font-medium ${
                  option.selected
                    ? "border-signal/55 bg-signal/15 text-signal"
                    : "border-line bg-canvas text-ink-mid hover:border-line-strong hover:text-ink"
                }`}
                href={option.href}
                onClick={() => setOpen(false)}
              >
                {option.label}
              </a>
            ))}
          </nav>
        </section>
      ) : null}
    </>
  );
}
