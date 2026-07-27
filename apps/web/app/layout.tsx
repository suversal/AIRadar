import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ScrollToTopButton } from "@/components/scroll-to-top-button";
import { ThemeInitScript } from "@/components/theme-init-script";
import { ThemeToggle } from "@/components/theme-toggle";

export const metadata: Metadata = {
  title: "Suversal AI Radar",
  description: "Concise AI intelligence reports for builders and creators.",
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
