import type { TopicsPayload } from "@/lib/api";
import { CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams, intParam } from "@/lib/v1/params";
import { shapeTopics } from "@/lib/v1/shape";
import { fetchUpstream } from "@/lib/v1/upstream";

export { OPTIONS };

const ALLOWED = ["days"] as const;

/**
 * 两组主题档案（公司与模型 / 技术方向）+ 本周雷达。
 *
 * days 下限是 14 而不是 1：weekCount / prevWeekCount 的周环比固定比较
 * 「今天-6」和「今天-13」两段，窗口比 14 天短的话 prevWeekCount 会结构性
 * 为 0，每个主题都被算成暴涨。越界直接 400，不悄悄放宽。
 */
export const GET = handleV1(async (request) => {
  const url = new URL(request.url);
  assertKnownParams(url, ALLOWED);
  const days = intParam(url, "days", { min: 14, max: 90, fallback: 90 });

  const payload = await fetchUpstream<TopicsPayload>(
    `/api/public/topics?days=${days}`,
    { revalidate: CACHE.topics },
  );
  const shaped = shapeTopics(payload);

  return ok(
    {
      schemaVersion: 1,
      windowDays: shaped.windowDays,
      storylineWindowDays: shaped.storylineWindowDays,
      itemCount: shaped.itemCount,
      groups: shaped.groups,
      // 本周雷达：近 14 天仍在更新的多日多源事件，回答"什么正在变热"。
      storylines: shaped.storylines,
    },
    CACHE.topics,
  );
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
