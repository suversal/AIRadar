import { CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import {
  ITEM_CATEGORIES,
  ITEM_FOCUSES,
  ITEM_MODES,
  ITEM_WINDOWS,
  loadItems,
} from "@/lib/v1/items";
import { assertKnownParams, enumParam, intParam, textParam } from "@/lib/v1/params";

export { OPTIONS };

const ALLOWED = ["mode", "window", "limit", "offset", "category", "focus", "q"] as const;

export const GET = handleV1(async (request) => {
  const url = new URL(request.url);
  assertKnownParams(url, ALLOWED);

  const mode = enumParam(url, "mode", ITEM_MODES, "selected");
  const window = enumParam(url, "window", ITEM_WINDOWS, "7d");
  const limit = intParam(url, "limit", { min: 1, max: 100, fallback: 50 });
  const offset = intParam(url, "offset", { min: 0, max: 10_000, fallback: 0 });
  const category = enumParam(url, "category", ITEM_CATEGORIES, undefined);
  const focus = enumParam(url, "focus", ITEM_FOCUSES, undefined);
  const q = textParam(url, "q", { minLength: 2, maxLength: 200 });

  const { items, total } = await loadItems({
    mode,
    window,
    limit,
    offset,
    category,
    focus,
    q,
  });

  return ok(
    {
      schemaVersion: 1,
      mode,
      window,
      // 排序恒定为 publishedAt 倒序。慢推信源的 publishedAt 是收录时间
      // （见每条的 timeBasis），要按原文发布时间收窄请在客户端自己做。
      sort: "publishedAt:desc",
      page: {
        count: items.length,
        limit,
        offset,
        total,
        hasMore: offset + items.length < total,
      },
      items,
    },
    CACHE.items,
  );
});

// 缓存由响应头的 s-maxage 交给共享缓存做，不用 Next 的整页缓存：
// 条件请求要拿到真实的 If-None-Match，静态化会把 304 逻辑绕过去。
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
