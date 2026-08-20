import { siteUrl } from "@/lib/site";
import { CACHE, handleV1, ok, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams, intParam } from "@/lib/v1/params";
import { fetchUpstream } from "@/lib/v1/upstream";

export { OPTIONS };

const ALLOWED = ["limit", "offset"] as const;

/** 日报期次索引，最新的在前。要正文用 /api/v1/dailies/{date}。 */
export const GET = handleV1(async (request) => {
  const url = new URL(request.url);
  assertKnownParams(url, ALLOWED);

  const limit = intParam(url, "limit", { min: 1, max: 100, fallback: 30 });
  const offset = intParam(url, "offset", { min: 0, max: 10_000, fallback: 0 });

  const payload = await fetchUpstream<{ dates?: string[] }>(
    "/api/public/reports/daily/archive",
    { revalidate: CACHE.dailyIndex },
  );
  const dates = payload.dates ?? [];
  const page = dates.slice(offset, offset + limit);

  return ok(
    {
      schemaVersion: 1,
      page: {
        count: page.length,
        limit,
        offset,
        total: dates.length,
        hasMore: offset + page.length < dates.length,
      },
      items: page.map((date) => ({
        date,
        links: {
          radar: new URL(`/daily?date=${date}`, siteUrl).toString(),
          api: new URL(`/api/v1/dailies/${date}`, siteUrl).toString(),
        },
      })),
    },
    CACHE.dailyIndex,
  );
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
