import type { MetadataRoute } from "next";
import { siteUrl } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      // /api/v1 与 /api/mcp 是对外公开的 Agent 接入面，要放行——llms.txt 把
      // 它们当作正式入口列了出来，被 disallow 挡住会让遵守 robots 的 AI 爬虫
      // 读得到目录却打不开门。allow 比 disallow 更长更具体，按最长匹配优先。
      allow: ["/", "/api/v1", "/api/mcp"],
      // /admin 是后台，其余 /api 是内部接口，/bookmarks 是本地收藏（每人不同）
      disallow: ["/admin", "/api", "/bookmarks"],
    },
    sitemap: new URL("/sitemap.xml", siteUrl).toString(),
    host: siteUrl,
  };
}
