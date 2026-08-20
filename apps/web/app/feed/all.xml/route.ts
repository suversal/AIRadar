import { FEED_LIMIT, respondWithItemsFeed } from "@/lib/feed/load";

/**
 * 公开池：最近 7 天全部收录，不只是精选。
 *
 * 量比 /feed.xml 大一个量级，且没有经过精选阈值——要的是覆盖面而不是
 * 信噪比。想省事的订阅者应该用 /feed.xml。
 */
export async function GET(request: Request) {
  return respondWithItemsFeed(
    request,
    {
      title: "AI·RADAR 全部动态",
      description:
        "最近 7 天收录的全部 AI 动态，按发布时间倒序，未经精选阈值过滤。要信噪比请订阅 /feed.xml。",
      selfPath: "/feed/all.xml",
      sitePath: "/all",
    },
    `/api/public/events?days=7&limit=${FEED_LIMIT}`,
  );
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
