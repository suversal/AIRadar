import { dailyCacheTier, loadDaily } from "@/lib/v1/daily";
import { handleV1, OPTIONS } from "@/lib/v1/http";
import { assertIsoDate, assertKnownParams } from "@/lib/v1/params";

export { OPTIONS };

type Context = { params: Promise<{ date: string }> };

/** 指定日期的日报。date 是上海时区的日历日，与站内 /daily 的期次一致。 */
export const GET = handleV1<Context>(async (request, context) => {
  assertKnownParams(new URL(request.url), []);
  const { date } = await context.params;
  // 档位按日期选：历史期次封版后不再变，可以放长缓存；今天那一期仍在
  // 滚动更新，必须和 /latest 同档，否则两个入口会对同一期各说各话。
  const iso = assertIsoDate(date);
  return loadDaily(iso, dailyCacheTier(iso));
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
