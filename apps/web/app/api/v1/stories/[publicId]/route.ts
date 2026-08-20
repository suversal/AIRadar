import type { LatestEvent } from "@/lib/api";
import { badRequest, CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams } from "@/lib/v1/params";
import { shapeStory } from "@/lib/v1/shape";
import { fetchUpstream } from "@/lib/v1/upstream";

export { OPTIONS };

type Context = { params: Promise<{ publicId: string }> };

/**
 * 单个事件：摘要、推荐理由，以及多信源报道时间线。
 *
 * publicId 只应来自其它端点返回的 items[].id 或 links.radar，不要猜——
 * 事件 ID 是聚类产物，同一条新闻在不同轮次可能归到不同事件。
 *
 * 不返回正文：站内阅读页可以展示第三方原文与译文，但通过 API 批量取走
 * 是再分发。正文走 links.original（原文）或 links.radar（站内阅读页）。
 */
export const GET = handleV1<Context>(async (request, context) => {
  const url = new URL(request.url);
  assertKnownParams(url, []);

  const { publicId } = await context.params;
  if (!publicId.trim()) {
    // 必须抛 V1Error：普通 Error 会掉进 handleV1 的兜底，被报成
    // "503 数据源暂时不可用"，客户端于是去退避重试一个永远不会好的请求。
    throw badRequest("invalid_parameter", "事件 ID 不能为空。");
  }

  const event = await fetchUpstream<LatestEvent>(
    `/api/public/events/${encodeURIComponent(publicId)}`,
    {
      revalidate: CACHE.story,
      notFoundDetail: `没有这个事件：${publicId}。ID 请从 /api/v1/items 或 /api/v1/hot-topics 的返回里取，不要自行构造。`,
    },
  );

  return ok(
    {
      schemaVersion: 1,
      story: shapeStory(event),
    },
    CACHE.story,
  );
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
