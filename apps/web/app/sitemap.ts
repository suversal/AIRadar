import type { MetadataRoute } from "next";
import { siteUrl } from "@/lib/site";

// 只收录公开的列表/内容入口。/admin 与 /api 由 robots.ts 拦掉，
// /bookmarks 是浏览器本地收藏、每人不同，收录没有意义。
//
// 事件详情页（/event/[id]）暂未纳入：那需要在构建期把全量 id 拉出来，
// 会让 web 构建依赖 API 可用。列表页已经能把爬虫带到详情页。
const routes: Array<{
  path: string;
  changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"];
  priority: number;
}> = [
  // 不收录 "/"：它是一个到 /latest 的 307 跳转，没有自己的内容，
  // 放进 sitemap 会和 /latest 的 canonical 打架。
  { path: "/latest", changeFrequency: "hourly", priority: 1 },
  { path: "/all", changeFrequency: "hourly", priority: 0.9 },
  { path: "/daily", changeFrequency: "daily", priority: 0.9 },
  { path: "/x", changeFrequency: "hourly", priority: 0.8 },
  { path: "/telegram", changeFrequency: "daily", priority: 0.7 },
  { path: "/topics", changeFrequency: "daily", priority: 0.7 },
  { path: "/weekly", changeFrequency: "weekly", priority: 0.6 },
  { path: "/monthly", changeFrequency: "monthly", priority: 0.6 },
  { path: "/search", changeFrequency: "monthly", priority: 0.4 },
  { path: "/about", changeFrequency: "monthly", priority: 0.4 },
  { path: "/agent", changeFrequency: "monthly", priority: 0.4 },
  { path: "/changelog", changeFrequency: "weekly", priority: 0.3 },
  { path: "/feedback", changeFrequency: "monthly", priority: 0.2 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return routes.map(({ path, changeFrequency, priority }) => ({
    url: new URL(path, siteUrl).toString(),
    lastModified,
    changeFrequency,
    priority,
  }));
}
