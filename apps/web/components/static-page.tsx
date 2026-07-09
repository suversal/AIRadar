import type { ReactNode } from "react";
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
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId={activeNavId} />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-6">
            <h1 className="text-3xl font-semibold text-ink">{title}</h1>
            <p className="mt-2 text-sm text-ink-mid">{subtitle}</p>
          </header>
          <div className="mt-6 max-w-3xl space-y-6">{children}</div>
        </section>
      </div>
    </main>
  );
}
