"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Menu, X } from "lucide-react";
import { BrandLogo } from "./brand-logo";
import { ContactLinks } from "./contact-links";
import { MOBILE_NAV_OPEN_EVENT } from "./mobile-nav-events";
import { navGroupItems } from "./nav";
import { MobileThemeSettings } from "./theme-toggle";
import { syncThemeChrome, type ResolvedTheme } from "./theme-chrome";

const DRAWER_TRANSITION_MS = 300;

export function MobileNav({ activeNavId }: { activeNavId: string }) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const closeTimerRef = useRef<number | null>(null);

  const openDrawer = useCallback(() => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setMounted(true);
    window.requestAnimationFrame(() => setOpen(true));
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    closeTimerRef.current = window.setTimeout(() => {
      setMounted(false);
      closeTimerRef.current = null;
      window.requestAnimationFrame(() => {
        const resolved: ResolvedTheme =
          document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
        syncThemeChrome(resolved);
        menuButtonRef.current?.focus();
      });
    }, reduceMotion ? 0 : DRAWER_TRANSITION_MS);
  }, []);

  useEffect(() => {
    function openMobileNav() {
      openDrawer();
    }

    window.addEventListener(MOBILE_NAV_OPEN_EVENT, openMobileNav);
    return () => window.removeEventListener(MOBILE_NAV_OPEN_EVENT, openMobileNav);
  }, [openDrawer]);

  useEffect(() => () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
  }, []);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        close();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) {
        return;
      }
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        drawerRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [close, open]);

  return (
    <>
      <div className="mobile-app-chrome relative z-30 flex h-14 items-center justify-between border-b-2 border-ink bg-canvas px-4 lg:hidden">
        <a aria-label="AI·RADAR 首页" className="inline-flex" href="/latest">
          <BrandLogo className="h-9 w-auto" />
        </a>
        <button
          ref={menuButtonRef}
          type="button"
          aria-expanded={open}
          aria-controls="mobile-nav-drawer"
          aria-label="打开导航菜单"
          onClick={openDrawer}
          className="flex h-10 w-10 items-center justify-center border-l border-line text-ink-mid transition-colors hover:bg-panel hover:text-signal"
        >
          <Menu aria-hidden className="h-5 w-5" strokeWidth={1.75} />
        </button>
      </div>

      {mounted ? (
        <>
          <div
            aria-hidden="true"
            onClick={close}
            className={`fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 ease-out motion-reduce:transition-none lg:hidden ${
              open ? "opacity-100" : "pointer-events-none opacity-0"
            }`}
          />
          <aside
            id="mobile-nav-drawer"
            ref={drawerRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-hidden={!open}
            inert={!open}
            aria-label="站内导航"
            className={`fixed inset-y-0 right-0 z-50 flex w-[min(76vw,248px)] flex-col overflow-hidden border-l border-line bg-canvas px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-4 outline-none will-change-transform transition-transform duration-300 motion-reduce:transition-none lg:hidden ${
              open
                ? "translate-x-0 ease-[cubic-bezier(0.22,1,0.36,1)]"
                : "pointer-events-none translate-x-full ease-in"
            }`}
          >
            <div className="mb-4 flex shrink-0 items-center justify-between border-b-2 border-ink pb-3">
              <div>
                <span className="readout block text-[9px] uppercase tracking-[0.2em] text-signal">AI·RADAR</span>
                <span className="mt-1 block text-sm font-semibold text-ink">站内索引</span>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                aria-label="关闭导航菜单"
                onClick={close}
                className="flex h-10 w-10 items-center justify-center border border-line text-ink-mid hover:bg-panel hover:text-signal"
              >
                <X aria-hidden className="h-5 w-5" strokeWidth={1.75} />
              </button>
            </div>
            <nav aria-label="主导航" className="min-h-0 flex-1 overflow-y-auto">
          {(["内容", "接入", "更多"] as const).map((group) => (
            <section key={group} className="mb-4">
              <div className="readout px-1 text-[9px] font-semibold uppercase tracking-[0.16em] text-ink-dim">{group}</div>
              <div className="mt-1 space-y-0.5">
                {navGroupItems(group).map((item) => {
                  const active = item.id === activeNavId;
                  const Icon = item.icon;
                  const className = `flex min-h-10 items-center gap-2.5 border-l-2 px-3 py-2 text-sm font-medium ${
                    active
                      ? "border-signal bg-panel text-signal"
                      : "border-transparent text-ink-mid hover:border-line-strong hover:bg-panel hover:text-ink"
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
                      onClick={close}
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
            <div className="shrink-0 border-t border-line pt-3 text-center">
              <MobileThemeSettings />
              <p className="mt-3 whitespace-nowrap text-[10px] leading-5 text-ink-dim">
                不追逐每一条消息，只标记真正的信号。
              </p>
              <div className="mt-2">
                <ContactLinks />
              </div>
            </div>
          </aside>
        </>
      ) : null}
    </>
  );
}
