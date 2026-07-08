import type { ReactNode } from "react";

type NavItem = {
  id: string;
  label: string;
  group: "内容" | "接入" | "更多";
  href?: string;
};

export type ReportMode = "daily" | "weekly" | "monthly";

export const reportModeTabs: Array<{
  id: ReportMode;
  label: string;
  href: string;
}> = [
  { id: "daily", label: "日报", href: "/daily" },
  { id: "weekly", label: "周报", href: "/weekly" },
  { id: "monthly", label: "月报", href: "/monthly" },
];

const navItems: NavItem[] = [
  { id: "latest", label: "精选", group: "内容", href: "/latest" },
  { id: "all", label: "全部 AI 动态", group: "内容", href: "/all" },
  { id: "daily", label: "AI 日报", group: "内容", href: "/daily" },
  { id: "topics", label: "主题", group: "内容" },
  { id: "bookmarks", label: "收藏", group: "内容" },
  { id: "agent", label: "Agent 接入", group: "接入" },
  { id: "about", label: "关于", group: "更多" },
  { id: "changelog", label: "更新日志", group: "更多" },
  { id: "feedback", label: "反馈", group: "更多" },
];

function navGroupItems(group: NavItem["group"]) {
  return navItems.filter((item) => item.group === group);
}

function marker(label: string) {
  return label.slice(0, 1);
}

export function ReportShell({
  activeMode,
  secondary,
  children,
}: {
  activeMode: ReportMode;
  secondary: ReactNode;
  children: ReactNode;
}) {
  const activeNavId = "daily";

  return (
    <main className="min-h-screen bg-[#070d1a] text-slate-100">
      <div className="grid min-h-screen lg:grid-cols-[144px_176px_1fr]">
        <aside className="border-b border-slate-800 bg-[#080d19] px-3 py-5 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
          <a className="block rounded-md border border-slate-800 bg-slate-900/80 px-4 py-5" href="/latest">
            <div aria-label="AIHOT" className="text-xl font-semibold tracking-[0.18em] text-slate-100">
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
                    const className = `flex items-center gap-3 rounded-md px-3 py-3 text-sm font-semibold ${
                      active
                        ? "border border-cyan-400/40 bg-cyan-400/10 text-cyan-300"
                        : "text-slate-500 hover:text-slate-300"
                    }`;
                    const content = (
                      <>
                        <span className="flex h-6 w-6 items-center justify-center rounded-md border border-slate-700 text-xs">
                          {marker(item.label)}
                        </span>
                        <span className="min-w-0 truncate">{item.label}</span>
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

          <div className="mt-6 rounded-full border border-slate-800 bg-slate-900/80 p-1 text-xs text-slate-500">
            <div className="grid grid-cols-3 gap-1">
              <button className="rounded-full px-2 py-2" type="button">
                日间
              </button>
              <button className="rounded-full bg-slate-800 px-2 py-2 text-slate-300" type="button">
                跟随系统
              </button>
              <button className="rounded-full px-2 py-2" type="button">
                夜间
              </button>
            </div>
          </div>
        </aside>

        <aside className="border-b border-slate-800 bg-[#0a101d] px-4 py-6 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
          <div className="grid grid-cols-3 rounded-md border border-slate-800 bg-slate-900/70 text-sm font-semibold text-slate-500">
            {reportModeTabs.map((tab) => (
              <a
                key={tab.id}
                className={`px-3 py-3 text-center ${
                  activeMode === tab.id ? "bg-emerald-400/15 text-emerald-300" : "hover:text-slate-300"
                }`}
                href={tab.href}
              >
                {tab.label}
              </a>
            ))}
          </div>
          {secondary}
        </aside>

        <section className="px-5 py-8 md:px-10 xl:px-16">{children}</section>
      </div>
    </main>
  );
}
