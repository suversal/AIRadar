"use client";

import { useEffect, useRef, useState } from "react";
import { Menu, X } from "lucide-react";
import { navGroupItems } from "./nav";

export function MobileNav({ activeNavId }: { activeNavId: string }) {
  const [open, setOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawerRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <>
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-panel px-4 py-3 lg:hidden">
        <a className="text-base font-semibold tracking-[0.12em] text-ink" href="/latest">
          AI<span className="text-signal">·RADAR</span>
        </a>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="mobile-nav-drawer"
          aria-label={open ? "关闭导航菜单" : "打开导航菜单"}
          onClick={() => setOpen((value) => !value)}
          className="flex h-10 w-10 items-center justify-center rounded-md border border-line text-ink-mid transition hover:border-signal/40 hover:text-ink"
        >
          {open ? (
            <X aria-hidden className="h-5 w-5" strokeWidth={1.75} />
          ) : (
            <Menu aria-hidden className="h-5 w-5" strokeWidth={1.75} />
          )}
        </button>
      </div>

      {open ? (
        <div
          aria-hidden="true"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
        />
      ) : null}

      <aside
        id="mobile-nav-drawer"
        ref={drawerRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="站内导航"
        className={`fixed inset-y-0 right-0 z-50 w-[240px] overflow-y-auto border-l border-line bg-panel px-4 py-5 outline-none transition-transform duration-300 ease-out lg:hidden ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <nav aria-label="主导航">
          {(["内容", "接入", "更多"] as const).map((group) => (
            <section key={group} className="mb-4">
              <div className="px-1 text-[11px] font-semibold text-ink-dim">{group}</div>
              <div className="mt-1 space-y-0.5">
                {navGroupItems(group).map((item) => {
                  const active = item.id === activeNavId;
                  const Icon = item.icon;
                  const className = `flex min-h-10 items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium ${
                    active
                      ? "border border-signal/40 bg-signal/10 text-signal"
                      : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                  }`;
                  const content = (
                    <>
                      <Icon aria-hidden className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                      {item.label}
                    </>
                  );
                  return item.href ? (
                    <a
                      key={item.id}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setOpen(false)}
                      className={className}
                      href={item.href}
                    >
                      {content}
                    </a>
                  ) : (
                    <div key={item.id} aria-disabled="true" className={className}>
                      {content}
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </nav>
      </aside>
    </>
  );
}
