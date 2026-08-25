import type { ReactNode } from "react";
import { MobileNav } from "./mobile-nav";
import { Sidebar } from "./sidebar";

export function StaticPage({
  activeNavId,
  title,
  subtitle,
  children,
}: {
  activeNavId: string;
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId={activeNavId} />
        <MobileNav activeNavId={activeNavId} />

        <section className="min-w-0 px-4 pb-10 pt-4 md:px-8 md:py-10 xl:px-12">
          <header className="mx-auto max-w-5xl border-b border-line-strong pb-7">
            <p className="readout text-[11px] uppercase tracking-[0.16em] text-signal">
              AI·RADAR / PUBLIC RECORD
            </p>
            <h1 className="editorial-rule-title mt-4 text-4xl font-medium leading-none text-ink md:text-6xl">
              {title}
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-ink-mid">{subtitle}</p>
          </header>
          <div className="editorial-static mx-auto mt-9 max-w-5xl space-y-10">{children}</div>
        </section>
      </div>
    </main>
  );
}
