import { navGroupItems, navMarker } from "./nav";

export function Sidebar({ activeNavId }: { activeNavId: string }) {
  return (
    <aside className="border-b border-line bg-panel px-4 py-5 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
      <a className="block rounded-md border border-line bg-panel px-5 py-6" href="/latest">
        <div aria-label="AI·RADAR" className="text-2xl font-semibold tracking-[0.2em] text-ink">
          AI<span className="text-signal">·RADAR</span>
        </div>
      </a>

      <nav className="mt-6 space-y-6" aria-label="主导航">
        {(["内容", "接入", "更多"] as const).map((group) => (
          <section key={group}>
            <div className="px-3 text-xs font-semibold text-ink-dim">{group}</div>
            <div className="mt-2 space-y-1">
              {navGroupItems(group).map((item) => {
                const active = item.id === activeNavId;
                const className = `flex items-center gap-3 rounded-md px-4 py-3 text-sm font-semibold ${
                  active
                    ? "border border-signal/40 bg-signal/10 text-signal"
                    : "text-ink-mid hover:text-ink"
                }`;
                const content = (
                  <>
                    <span className="flex h-6 w-6 items-center justify-center rounded-md border border-line-strong text-xs">
                      {navMarker(item.label)}
                    </span>
                    {item.label}
                  </>
                );
                return item.href ? (
                  <a
                    key={item.id}
                    aria-current={active ? "page" : undefined}
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
  );
}
