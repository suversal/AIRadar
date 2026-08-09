import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ScrollToTopButton } from "@/components/scroll-to-top-button";
import { ThemeInitScript } from "@/components/theme-init-script";
import { ThemeToggle } from "@/components/theme-toggle";

export const metadata: Metadata = {
  title: {
    default: "AI·RADAR — 为创作者和开发者准备的 AI 情报雷达",
    template: "%s · AI·RADAR",
  },
  description:
    "持续监听数十个高信噪比 AI 信源，用 AI 评分、聚类、去重，每天沉淀一期精选日报。为创作者和开发者准备的 AI 情报雷达。",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="scroll-smooth" suppressHydrationWarning>
      <body>
        <ThemeInitScript />
        {children}
        <ScrollToTopButton />
        <ThemeToggle />
      </body>
    </html>
  );
}
