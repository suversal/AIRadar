// 条目列表的取数。REST 的 /api/v1/items 和 MCP 的 radar_get_latest /
// radar_search 共用这一份，两条路径的窗口口径必须永远一致——同一个问题
// 从 API 问和从 Agent 问得到不同答案，是最难解释的那种"bug"。

import type { LatestEvent } from "@/lib/api";
import { CACHE } from "./http";
import { shapeItem, type V1Item } from "./shape";
import { collectWithinWindow, fetchUpstream } from "./upstream";

export const ITEM_MODES = ["selected", "all"] as const;
export const ITEM_WINDOWS = ["24h", "7d"] as const;
export const ITEM_CATEGORIES = ["model", "product", "industry", "research", "tutorial"] as const;
export const ITEM_FOCUSES = ["model", "product", "technology", "industry", "tutorial"] as const;

export type ItemMode = (typeof ITEM_MODES)[number];
export type ItemWindow = (typeof ITEM_WINDOWS)[number];

export type LoadItemsOptions = {
  mode: ItemMode;
  window: ItemWindow;
  limit: number;
  offset?: number;
  category?: string;
  focus?: string;
  q?: string;
};

type UpstreamPage = { items?: LatestEvent[]; total?: number };

/** 24h 窗口要多拉一个日历日：上游只能按天切，"过去 24 小时"横跨昨天和今天。 */
const DAYS_FOR: Record<ItemWindow, number> = { "24h": 2, "7d": 7 };

function upstreamPath(options: LoadItemsOptions, limit: number, offset: number): string {
  const search = new URLSearchParams();
  search.set("limit", String(limit));
  search.set("offset", String(offset));
  if (options.category) search.set("category", options.category);
  if (options.focus) search.set("focus", options.focus);
  if (options.q) search.set("q", options.q);
  if (options.mode === "selected") {
    // /api/public/latest 的窗口固定是"今天往前 7 天"，且已按事件去重
    // （一个事件只出代表条），正是精选流的口径。
    return `/api/public/latest?${search.toString()}`;
  }
  search.set("days", String(DAYS_FOR[options.window]));
  return `/api/public/events?${search.toString()}`;
}

export async function loadItems(
  options: LoadItemsOptions,
): Promise<{ items: V1Item[]; total: number }> {
  const offset = options.offset ?? 0;

  if (options.window === "7d") {
    // 上游窗口本来就是 7 天，分页直接下推，不必把整窗拉进内存。
    const page = await fetchUpstream<UpstreamPage>(
      upstreamPath(options, options.limit, offset),
      { revalidate: CACHE.items },
    );
    const raw = page.items ?? [];
    return { items: raw.map(shapeItem), total: page.total ?? raw.length };
  }

  // 24h 要在天粒度的上游结果上按小时收窄，只能先把窗内前缀取全再分页。
  const cutoffMs = Date.now() - 24 * 60 * 60 * 1000;
  const withinWindow = await collectWithinWindow<LatestEvent>(
    async (pageOffset, pageLimit) => {
      const page = await fetchUpstream<UpstreamPage>(
        upstreamPath(options, pageLimit, pageOffset),
        { revalidate: CACHE.items },
      );
      const pageItems = page.items ?? [];
      return { items: pageItems, total: page.total ?? pageItems.length };
    },
    (item) => item.published_at ?? null,
    cutoffMs,
  );

  return {
    items: withinWindow.slice(offset, offset + options.limit).map(shapeItem),
    total: withinWindow.length,
  };
}
