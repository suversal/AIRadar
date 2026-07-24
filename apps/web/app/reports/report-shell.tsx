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
    <div className="grid grid-cols-3 overflow-hidden rounded-md border border-line text-sm font-semibold text-ink-mid">
      {reportModeTabs.map((tab) => (
        <a
          key={tab.id}
          aria-current={activeMode === tab.id ? "page" : undefined}
          className={`whitespace-nowrap px-2 py-2.5 text-center ${
            activeMode === tab.id
              ? "bg-signal/15 text-signal"
              : "hover:bg-panel hover:text-ink"
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
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_200px_1fr]">
        <Sidebar activeNavId="daily" />
        <MobileNav activeNavId="daily" />

        {/* 移动端专属：日报/周报/月报切换条常驻紧跟顶部导航条之后，不藏进抽屉——
            这是比通用站内导航更高频的操作，之前塞进抽屉后用户反馈找不到入口 */}
        <div className="px-4 pt-4 lg:hidden">
          <ReportModeTabsNav activeMode={activeMode} />
        </div>

        {/* 移动端把归档栏推到正文之后，避免用户先滑过导航+归档才看到报告本身；
            桌面端 order-none 还原成中间列 */}
        <aside className="relative z-10 order-last bg-canvas px-4 py-6 lg:sticky lg:top-0 lg:order-none lg:h-screen lg:overflow-y-auto lg:border-r lg:border-line">
          <div className="hidden lg:block">
            <ReportModeTabsNav activeMode={activeMode} />
          </div>
          {secondary}
        </aside>

        <section className="px-5 py-8 md:px-10 xl:px-16">{children}</section>
      </div>
    </main>
  );
}
