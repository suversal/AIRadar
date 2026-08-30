import type { ReactNode } from "react";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";

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

function ReportModeTabsNav({ activeMode }: { activeMode: ReportMode }) {
  return (
    <div className="grid grid-cols-3 border-b border-line text-sm font-semibold text-ink-mid">
      {reportModeTabs.map((tab) => (
        <a
          key={tab.id}
          aria-current={activeMode === tab.id ? "page" : undefined}
          className={`whitespace-nowrap px-2 py-2 text-center md:py-2.5 ${
            activeMode === tab.id
              ? "border-b-2 border-signal text-signal"
              : "border-b-2 border-transparent hover:text-ink"
          }`}
          href={tab.href}
        >
          {tab.label}
        </a>
      ))}
    </div>
  );
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
  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen min-w-0 grid-cols-1 content-start lg:grid-cols-[248px_216px_minmax(0,1fr)]">
        {/* 周报/月报没有独立侧栏入口，统一从「AI 日报」进入并保持其高亮 */}
        <Sidebar activeNavId="daily" />
        <MobileNav activeNavId="daily" />

        {/* 移动端专属：日报/周报/月报切换条常驻紧跟顶部导航条之后，不藏进抽屉——
            这是比通用站内导航更高频的操作，之前塞进抽屉后用户反馈找不到入口 */}
        <div className="px-4 pt-2 lg:hidden">
          <ReportModeTabsNav activeMode={activeMode} />
        </div>

        {/* 移动端把归档栏推到正文之后，避免用户先滑过导航+归档才看到报告本身；
            桌面端 order-none 还原成中间列 */}
        <aside className="relative z-10 order-last bg-canvas px-4 py-6 lg:sticky lg:top-0 lg:order-none lg:h-screen lg:overflow-y-auto lg:border-r lg:border-line lg:px-5 lg:pb-8 lg:pt-4">
          <div className="hidden lg:block">
            <ReportModeTabsNav activeMode={activeMode} />
          </div>
          {secondary}
        </aside>

        <section className="min-w-0 px-4 pb-6 pt-4 md:px-8 md:py-8 xl:px-12">
          <div className="mx-auto max-w-5xl">{children}</div>
        </section>
      </div>
    </main>
  );
}
