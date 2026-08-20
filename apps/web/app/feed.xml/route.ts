import { FEED_LIMIT, respondWithItemsFeed } from "@/lib/feed/load";

/** 主订阅：最新 50 条精选。第一次接入选这个。 */
export async function GET(request: Request) {
  return respondWithItemsFeed(
    request,
    {
      title: "AI·RADAR 精选",
      description:
        "持续监听数十个高信噪比 AI 信源，经 AI 评分、聚类、去重后的精选条目。含中文摘要与推荐理由。",
      selfPath: "/feed.xml",
      sitePath: "/latest",
    },
    `/api/public/latest?limit=${FEED_LIMIT}`,
  );
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
