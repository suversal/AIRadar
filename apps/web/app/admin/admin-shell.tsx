import type { ReactNode } from "react";

const adminNav = [
  { id: "dashboard", label: "仪表盘", href: "/admin" },
  { id: "sources", label: "信源管理", href: "/admin/sources" },
  { id: "events", label: "内容修正", href: "/admin/events" },
];

export function AdminShell({
  active,
  title,
  subtitle,
  children,
}: {
  active: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <main className="min-h-screen bg-canvas px-5 py-8 text-ink md:px-10">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <a
              aria-label="AI·RADAR 管理后台"
              className="text-xl font-semibold tracking-[0.15em]"
              href="/admin"
            >
              AI<span className="text-signal">·RADAR</span>
              <span className="ml-3 text-sm font-normal text-ink-mid">管理后台</span>
            </a>
            <nav className="flex gap-1 rounded-md border border-line bg-panel p-1 text-sm font-semibold">
              {adminNav.map((item) => (
                <a
                  key={item.id}
                  aria-current={item.id === active ? "page" : undefined}
                  className={`rounded px-4 py-2 ${
                    item.id === active
                      ? "bg-signal/15 text-signal"
                      : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                  }`}
                  href={item.href}
                >
                  {item.label}
                </a>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <a className="text-ink-mid hover:text-signal" href="/latest">
              查看站点
            </a>
            <form action="/admin/logout" method="post">
              <button className="text-ink-mid hover:text-signal" type="submit">
                退出登录
              </button>
            </form>
          </div>
        </header>

        <div className="mt-8">
          <h1 className="text-2xl font-semibold text-ink">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-ink-mid">{subtitle}</p> : null}
        </div>

        <div className="mt-6">{children}</div>
      </div>
    </main>
  );
}
