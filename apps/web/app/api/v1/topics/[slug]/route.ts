import type { TopicDetailPayload } from "@/lib/api";
import { siteUrl } from "@/lib/site";
import { CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams, intParam } from "@/lib/v1/params";
import { shapeItem } from "@/lib/v1/shape";
import { fetchUpstream } from "@/lib/v1/upstream";

export { OPTIONS };

type Context = { params: Promise<{ slug: string }> };

const ALLOWED = ["limit", "offset"] as const;

/**
 * 一个主题的档案：窗口内全部条目 + 近期焦点。
 *
 * focus 是近 14 天的重点条目，items 是整个窗口（默认 90 天）的收录流水。
 * 两者会重叠，按 id 去重后再用。
 */
export const GET = handleV1<Context>(async (request, context) => {
  const url = new URL(request.url);
  assertKnownParams(url, ALLOWED);

  const limit = intParam(url, "limit", { min: 1, max: 100, fallback: 60 });
  const offset = intParam(url, "offset", { min: 0, max: 10_000, fallback: 0 });
  const { slug } = await context.params;

  const payload = await fetchUpstream<TopicDetailPayload>(
    `/api/public/topics/${encodeURIComponent(slug)}?limit=${limit}&offset=${offset}`,
    {
      revalidate: CACHE.topics,
      notFoundDetail: `没有这个主题：${slug}。可用主题见 /api/v1/topics。`,
    },
  );

  const items = (payload.items ?? []).map(shapeItem);
  return ok(
    {
      schemaVersion: 1,
      topic: {
        id: payload.topic.id,
        name: payload.topic.name,
        description: payload.topic.description ?? "",
        groupId: payload.topic.group_id,
        groupName: payload.topic.group_name,
        links: {
          radar: new URL(`/topics/${encodeURIComponent(payload.topic.id)}`, siteUrl).toString(),
        },
      },
      windowDays: payload.window_days ?? 90,
      focusWindowDays: payload.focus_window_days ?? 14,
      // totalCount 含未精选条目，selectedCount 只算精选——两个口径都给，
      // 免得客户端拿 items.length 去反推。
      totalCount: payload.total_count ?? 0,
      selectedCount: payload.selected_count ?? 0,
      latestPublishedAt: payload.latest_published_at ?? null,
      focus: (payload.focus ?? []).map(shapeItem),
      page: {
        count: items.length,
        limit,
        offset,
        total: payload.total_count ?? items.length,
        hasMore: offset + items.length < (payload.total_count ?? items.length),
      },
      items,
    },
    CACHE.topics,
  );
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
