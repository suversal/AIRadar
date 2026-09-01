import { handleV1, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams, assertPeriodKey } from "@/lib/v1/params";
import { loadPeriod } from "@/lib/v1/period";

export { OPTIONS };
type Context = { params: Promise<{ key: string }> };

export const GET = handleV1<Context>(async (request, context) => {
  assertKnownParams(new URL(request.url), []);
  const { key } = await context.params;
  return loadPeriod("weekly", assertPeriodKey(key, "weekly"));
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
