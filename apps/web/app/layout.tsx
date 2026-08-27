import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AnalyticsScript } from "@/components/analytics-script";
import { ScrollToTopButton } from "@/components/scroll-to-top-button";
import {
  EDITORIAL_DARK_CHROME_COLOR,
  EDITORIAL_LIGHT_CHROME_COLOR,
  THEME_COLOR_META_ID,
} from "@/components/theme-chrome";
import { ThemeInitScript } from "@/components/theme-init-script";
import { ThemeToggle } from "@/components/theme-toggle";
import { siteDescription, siteTitle, siteUrl } from "@/lib/site";

const websiteStructuredData = JSON.stringify({
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "AI·RADAR",
  alternateName: ["AI RADAR", "AIRADAR"],
  url: `${siteUrl.replace(/\/$/, "")}/`,
}).replace(/</g, "\\u003c");

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
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: websiteStructuredData }}
          type="application/ld+json"
        />
        <meta
          id={THEME_COLOR_META_ID}
          name="theme-color"
          content={EDITORIAL_LIGHT_CHROME_COLOR}
          media="(prefers-color-scheme: light)"
        />
        <meta
          name="theme-color"
          content={EDITORIAL_DARK_CHROME_COLOR}
          media="(prefers-color-scheme: dark)"
        />
      </head>
      <body>
        <ThemeInitScript />
        {children}
        <ScrollToTopButton />
        <ThemeToggle />
        {/* 埋点放在最后：它不影响首屏，注入的 tracker 也是 defer 的。
            自己会跳过 /admin，未配置 website id 时整体不渲染。 */}
        <AnalyticsScript />
      </body>
    </html>
  );
}
