import { BrandLogo } from "./brand-logo";
import { navGroupItems } from "./nav";

export function Sidebar({ activeNavId }: { activeNavId: string }) {
  return (
    <aside className="hidden min-w-0 bg-panel px-3 py-2 lg:sticky lg:top-0 lg:block lg:h-screen lg:border-r lg:border-line">
      <a
        aria-label="AI·RADAR 首页"
        className="-mx-3 flex items-center justify-center py-2"
        href="/latest"
      >
        <BrandLogo className="h-auto w-[200px]" />
      </a>

      <nav className="mt-2 space-y-5" aria-label="主导航">
        {(["内容", "接入", "更多"] as const).map((group) => (
          <section key={group}>
            <div className="px-3 text-[11px] font-semibold text-ink-dim">{group}</div>
            <div className="mt-1.5 space-y-0.5">
              {navGroupItems(group).map((item) => {
                const active = item.id === activeNavId;
                const Icon = item.icon;
                const className = `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium ${
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
