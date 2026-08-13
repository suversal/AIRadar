import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ScrollToTopButton } from "@/components/scroll-to-top-button";
import { ThemeInitScript } from "@/components/theme-init-script";
import { ThemeToggle } from "@/components/theme-toggle";
import { siteDescription, siteTitle, siteUrl } from "@/lib/site";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: siteTitle,
    template: "%s · AI·RADAR",
  },
  description: siteDescription,
  applicationName: "AI·RADAR",
  // og:image 由同目录的 opengraph-image.tsx 自动注入，这里不用手写
  openGraph: {
    type: "website",
    siteName: "AI·RADAR",
    locale: "zh_CN",
    url: "/",
    title: siteTitle,
    description: siteDescription,
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
  },
  robots: {
    index: true,
    follow: true,
  },
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
