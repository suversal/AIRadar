import type { ReactNode } from "react";
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
      <div className="grid min-h-screen lg:grid-cols-[224px_200px_1fr]">
        <Sidebar activeNavId="daily" />

        <aside className="relative z-10 border-b border-line bg-canvas px-4 py-6 lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:border-b-0 lg:border-r">
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
          {secondary}
        </aside>

        <section className="px-5 py-8 md:px-10 xl:px-16">{children}</section>
      </div>
    </main>
  );
}
