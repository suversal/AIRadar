import type { MetadataRoute } from "next";
import { siteUrl } from "@/lib/site";
import { TOPIC_SLUGS } from "@/lib/topics";
import {
  getDailyArchive,
  getPeriodArchive,
  getSitemapEvents,
} from "@/lib/api";

// 只收录公开的列表/内容入口。/admin 与 /api 由 robots.ts 拦掉，
// /bookmarks 是浏览器本地收藏、每人不同，收录没有意义。
//
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
  { path: "/about", changeFrequency: "monthly", priority: 0.4 },
  { path: "/agent", changeFrequency: "monthly", priority: 0.4 },
  { path: "/agent/api", changeFrequency: "monthly", priority: 0.3 },
  { path: "/changelog", changeFrequency: "weekly", priority: 0.3 },
  // 这里刻意**不放** /search 和 /feedback：
  //   /search  是工具页，已在 app/search/page.tsx 里设 noindex。
  //            sitemap 的语义是"我希望你收录这些"，把一个 noindex 页面放进来
  //            是自相矛盾的信号，Search Console 会报"已提交的网址标记为 noindex"。
  //   /feedback 是表单功能页，没有可被检索的内容，收录了也不会有人从搜索进来。
  // 两个页面本身照常可访问、照常能从侧栏点到，只是不主动请求收录。
];

export const revalidate = 900;

function validLastModified(value?: string | null): string | undefined {
  if (!value || Number.isNaN(Date.parse(value))) {
    return undefined;
  }
  return value;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [eventPayload, dailyDates, weeklyArchive, monthlyArchive] = await Promise.all([
    getSitemapEvents(),
    getDailyArchive(),
    getPeriodArchive("weekly"),
    getPeriodArchive("monthly"),
  ]);

  const entries: MetadataRoute.Sitemap = [
    ...routes.map(({ path, changeFrequency, priority }) => ({
      url: new URL(path, siteUrl).toString(),
      changeFrequency,
      priority,
    })),
    // 主题详情页是全站的长尾搜索入口("Claude 最新动态"这类查询),
    // slug 来自前端镜像注册表,不依赖构建期 API 可达
    ...TOPIC_SLUGS.map((slug) => ({
      url: new URL(`/topics/${slug}`, siteUrl).toString(),
      changeFrequency: "daily" as const,
      priority: 0.6,
    })),
    ...(eventPayload?.items ?? []).map((item) => ({
      url: new URL(`/event/${item.event_id}`, siteUrl).toString(),
      lastModified: validLastModified(item.last_modified),
      changeFrequency: "weekly" as const,
      priority: 0.7,
    })),
    ...dailyDates.map((date) => ({
      url: new URL(`/daily?date=${encodeURIComponent(date)}`, siteUrl).toString(),
      lastModified: validLastModified(date),
      changeFrequency: "never" as const,
      priority: 0.6,
    })),
    ...weeklyArchive.map((entry) => ({
      url: new URL(`/weekly/${entry.period_key}`, siteUrl).toString(),
      lastModified: validLastModified(entry.range_end),
      changeFrequency: "never" as const,
      priority: 0.6,
    })),
    ...monthlyArchive.map((entry) => ({
      url: new URL(`/monthly/${entry.period_key}`, siteUrl).toString(),
      lastModified: validLastModified(entry.range_end),
      changeFrequency: "never" as const,
      priority: 0.6,
    })),
  ];

  return Array.from(new Map(entries.map((entry) => [entry.url, entry])).values());
}
