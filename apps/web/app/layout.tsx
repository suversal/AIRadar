import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ScrollToTopButton } from "@/components/scroll-to-top-button";
import {
  DARK_THEME_CHROME_COLOR,
  THEME_COLOR_META_ID,
} from "@/components/theme-chrome";
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
      <head>
        <meta
          id={THEME_COLOR_META_ID}
          name="theme-color"
          content={DARK_THEME_CHROME_COLOR}
        />
      </head>
      <body>
        <ThemeInitScript />
        {children}
        <ScrollToTopButton />
        <ThemeToggle />
      </body>
    </html>
  );
}
