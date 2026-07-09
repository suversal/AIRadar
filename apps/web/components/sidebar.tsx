import { navGroupItems, navMarker } from "./nav";

export function Sidebar({ activeNavId }: { activeNavId: string }) {
  return (
    <aside className="border-b border-slate-800 bg-[#080d19] px-4 py-5 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
      <a className="block rounded-md border border-slate-800 bg-slate-900/80 px-5 py-6" href="/latest">
        <div aria-label="AIHOT" className="text-2xl font-semibold tracking-[0.2em] text-slate-100">
          AI<span className="text-cyan-300">HOT</span>
        </div>
      </a>

      <nav className="mt-6 space-y-6" aria-label="主导航">
        {(["内容", "接入", "更多"] as const).map((group) => (
          <section key={group}>
            <div className="px-3 text-xs font-semibold text-slate-600">{group}</div>
            <div className="mt-2 space-y-1">
              {navGroupItems(group).map((item) => {
                const active = item.id === activeNavId;
                const className = `flex items-center gap-3 rounded-md px-4 py-3 text-sm font-semibold ${
                  active
                    ? "border border-cyan-400/40 bg-cyan-400/10 text-cyan-300"
                    : "text-slate-500 hover:text-slate-300"
                }`;
                const content = (
                  <>
                    <span className="flex h-6 w-6 items-center justify-center rounded-md border border-slate-700 text-xs">
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
