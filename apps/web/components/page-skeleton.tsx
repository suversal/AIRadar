import { Sidebar } from "./sidebar";

function SkeletonCard() {
  return (
    <div className="rounded-md border border-line bg-panel p-5">
      <div className="skeleton h-3 w-32" />
      <div className="skeleton mt-4 h-5 w-3/4" />
      <div className="skeleton mt-4 h-3 w-full" />
      <div className="skeleton mt-2 h-3 w-5/6" />
    </div>
  );
}

export function PageSkeleton({ activeNavId }: { activeNavId: string }) {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId={activeNavId} />

        <section className="px-5 py-6 md:px-9">
          <div className="rounded-md border border-line bg-panel p-6">
            <div className="readout flex items-center gap-3 text-xs uppercase tracking-[0.14em] text-ink-dim">
              <span aria-hidden className="signal-pulse h-1.5 w-1.5 rounded-full bg-signal" />
              <span className="text-signal">SIGNAL</span>
              <span>SCANNING…</span>
            </div>
            <div className="skeleton mt-5 h-8 w-40" />
            <div className="skeleton mt-3 h-3 w-64" />
          </div>
          <div className="mt-6 grid gap-4">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        </section>
      </div>
    </main>
  );
}
