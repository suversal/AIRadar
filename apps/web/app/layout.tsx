import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Suversal AI Radar",
  description: "Concise AI intelligence reports for builders and creators.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
