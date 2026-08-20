// Feed 的取数与渲染入口。四个 feed 路由的差异只在"取哪一批条目"，
// 其余（塑形、渲染、ETag、缓存头）全部共用。

import type { LatestEvent } from "@/lib/api";
import { CACHE, conditionalText } from "@/lib/v1/http";
import { shapeItem } from "@/lib/v1/shape";
import { fetchUpstream } from "@/lib/v1/upstream";
import { renderItemsFeed, type FeedChannel } from "./rss";

/** 阅读器一屏看不完 50 条，再多只是让首次订阅变慢。 */
export const FEED_LIMIT = 50;

export const FEED_CONTENT_TYPE = "application/rss+xml; charset=utf-8";

type UpstreamPage = { items?: LatestEvent[] };

export async function respondWithItemsFeed(
  request: Request,
  channel: FeedChannel,
  upstreamPath: string,
): Promise<Response> {
  try {
    const page = await fetchUpstream<UpstreamPage>(upstreamPath, {
      revalidate: CACHE.feed,
    });
    const items = (page.items ?? []).map(shapeItem);
    return conditionalText(
      request,
      renderItemsFeed(channel, items),
      FEED_CONTENT_TYPE,
      CACHE.feed,
    );
  } catch (error) {
    // 阅读器拿到 500 通常会退避甚至标记订阅失效，比空 feed 更烦人，
    // 但空 feed 会让订阅者以为条目被删了。503 + Retry-After 是正解：
    // 明确说"暂时不可用，等会再来"。
    //
    // 细节只进服务端日志：回显 error.message 会把内网路径和上游状态码
    // 一起吐给任何一个订阅者。
    console.error(`[feed] ${upstreamPath} failed:`, error);
    return new Response("数据源暂时不可用，请稍后重试。", {
      status: 503,
      headers: { "Retry-After": "300", "Cache-Control": "no-store" },
    });
  }
}
