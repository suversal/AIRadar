import { siteUrl } from "@/lib/site";
import { CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams, intParam } from "@/lib/v1/params";
import { loadPeriodArchive, PERIOD_META } from "@/lib/v1/period";

export { OPTIONS };

export const GET = handleV1(async (request) => {
  const url = new URL(request.url);
  assertKnownParams(url, ["limit", "offset"]);
  const limit = intParam(url, "limit", { min: 1, max: 100, fallback: 30 });
  const offset = intParam(url, "offset", { min: 0, max: 10_000, fallback: 0 });
  const entries = await loadPeriodArchive("weekly");
  const page = entries.slice(offset, offset + limit);

  return ok({
    schemaVersion: 1,
    page: { count: page.length, limit, offset, total: entries.length, hasMore: offset + page.length < entries.length },
    items: page.map((entry) => ({
      key: entry.period_key,
      rangeStart: entry.range_start,
      rangeEnd: entry.range_end,
      title: entry.mainline_title,
      itemCount: entry.article_count,
      links: {
        radar: new URL(`/${PERIOD_META.weekly.page}/${entry.period_key}`, siteUrl).toString(),
        api: new URL(`/api/v1/${PERIOD_META.weekly.collection}/${entry.period_key}`, siteUrl).toString(),
      },
    })),
  }, CACHE.periodIndex);
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
