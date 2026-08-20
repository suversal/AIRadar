import { latestDailyDate, loadDaily } from "@/lib/v1/daily";
import { CACHE, handleV1, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams } from "@/lib/v1/params";

export { OPTIONS };

/** 最新一期日报。按上海时区日历日分期，当天那一期会随抓取滚动更新。 */
export const GET = handleV1(async (request) => {
  assertKnownParams(new URL(request.url), []);
  const date = await latestDailyDate();
  return loadDaily(date, CACHE.dailyLatest);
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
