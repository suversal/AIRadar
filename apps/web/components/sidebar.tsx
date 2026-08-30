import { BrandLogo } from "./brand-logo";
import { ContactLinks } from "./contact-links";
import { navGroupItems } from "./nav";

export function Sidebar({ activeNavId }: { activeNavId: string }) {
  return (
    <aside className="hidden min-w-0 bg-canvas px-5 pb-24 pt-5 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:overflow-y-auto lg:border-r lg:border-line">
      <div className="border-b-2 border-ink pb-5">
        <p className="readout text-[9px] uppercase tracking-[0.22em] text-ink-dim">Independent AI Intelligence</p>
        <a
          aria-label="AI·RADAR 首页"
          className="mt-3 flex items-center"
          href="/latest"
        >
          <BrandLogo className="h-auto w-[190px]" />
        </a>
      </div>

      <nav className="mt-6 space-y-6" aria-label="主导航">
        {(["内容", "接入", "更多"] as const).map((group, groupIndex) => (
          <section key={group}>
            <div className="readout flex items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-ink-dim">
              <span className="text-signal">0{groupIndex + 1}</span>
              {group}
            </div>
            <div className="mt-2 space-y-1">
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

      <div className="mt-auto border-t border-line pt-4">
        <p className="text-[11px] leading-5 text-ink-dim">
          不追逐每一条消息。<br />只标记真正的信号。
        </p>
        <div className="mt-4">
          <ContactLinks />
        </div>
      </div>
    </aside>
  );
}
