import type { HotspotsPayload } from "@/lib/api";
import { CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams, enumParam, intParam, textParam } from "@/lib/v1/params";
import { shapeItem } from "@/lib/v1/shape";
import { fetchUpstream } from "@/lib/v1/upstream";

export { OPTIONS };

const CATEGORIES = ["model", "product", "industry", "research", "tutorial"] as const;
const FOCUSES = ["model", "product", "technology", "industry", "tutorial"] as const;
const ALLOWED = ["hours", "limit", "category", "focus", "q"] as const;

/**
 * 当前热点榜。
 *
 * 和 items 的区别是排序口径：items 按时间倒序回答"最近发生了什么"，
 * 这里按多信源热度排序回答"现在什么最热"。同一件事被几家同时报道才会
 * 冒头，所以榜很短——limit 上限 20 是刻意的，不是分页没做完。
 */
export const GET = handleV1(async (request) => {
  const url = new URL(request.url);
  assertKnownParams(url, ALLOWED);

  const hours = intParam(url, "hours", { min: 1, max: 168, fallback: 48 });
  const limit = intParam(url, "limit", { min: 1, max: 20, fallback: 10 });
  const category = enumParam(url, "category", CATEGORIES, undefined);
  const focus = enumParam(url, "focus", FOCUSES, undefined);
  const q = textParam(url, "q", { minLength: 2, maxLength: 200 });

  const search = new URLSearchParams();
  search.set("hours", String(hours));
  search.set("limit", String(limit));
  if (category) search.set("category", category);
  if (focus) search.set("focus", focus);
  if (q) search.set("q", q);

  const payload = await fetchUpstream<HotspotsPayload>(
    `/api/public/hotspots?${search.toString()}`,
    { revalidate: CACHE.hotTopics },
  );

  const items = (payload.items ?? []).map(shapeItem);
  return ok(
    {
      schemaVersion: 1,
      windowHours: payload.window_hours ?? hours,
      sort: "heat:desc",
      count: items.length,
      // 事件详情要用 items[].id 调 /api/v1/stories/{id}，不要自己拼 ID。
      items,
    },
    CACHE.hotTopics,
  );
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
