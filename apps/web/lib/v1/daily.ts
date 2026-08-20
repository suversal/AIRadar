// /api/v1/dailies/latest 与 /api/v1/dailies/{date} 的共同取数逻辑。

import type { DailyReport } from "@/lib/api";
import { CACHE, notFound, ok, type V1Success } from "./http";
import { shapeDaily } from "./shape";
import { fetchUpstream } from "./upstream";

/** 上海时区的今天。日报期次按这个日历日划分。 */
export function todayInShanghai(): string {
  // en-CA 的短日期格式就是 YYYY-MM-DD
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/**
 * 一期日报该用哪个缓存档位。
 *
 * 当天那一期还在随抓取滚动更新，套用"封版后不再变"的一小时档，会让
 * /api/v1/dailies/{今天} 和 /api/v1/dailies/latest 在长达一小时里对同一期
 * 给出不同版本。三个入口（REST 指定日期、MCP、RSS）都得按同一条规则选档，
 * 所以规则放在这里，不在各自文件里各写一遍。
 */
export function dailyCacheTier(date: string): number {
  return date === todayInShanghai() ? CACHE.dailyLatest : CACHE.dailyArchived;
}

/**
 * 取一期日报。
 *
 * 上游对没有日报的日期返回的是"空日报"而不是 404（页面需要拿它渲染
 * 骨架），API 这边必须自己判空翻成 404——否则客户端会把空壳当成
 * "那天没有 AI 新闻"存下来。
 */
export async function loadDaily(date: string, sMaxAge: number): Promise<V1Success> {
  const report = await fetchUpstream<DailyReport>(
    `/api/public/daily/${encodeURIComponent(date)}`,
    { revalidate: sMaxAge },
  );

  if (!report || (report.article_count ?? 0) === 0) {
    throw notFound(`${date} 没有日报。可用期次见 /api/v1/dailies。`);
  }

  return ok(
    {
      schemaVersion: 1,
      report: shapeDaily(report),
    },
    sMaxAge,
  );
}

/** 最新一期的日期。索引按日期倒序，取第一个。 */
export async function latestDailyDate(): Promise<string> {
  const payload = await fetchUpstream<{ dates?: string[] }>(
    "/api/public/reports/daily/archive",
    { revalidate: CACHE.dailyIndex },
  );
  const latest = (payload.dates ?? [])[0];
  if (!latest) {
    throw notFound("还没有任何一期日报。");
  }
  return latest;
}
