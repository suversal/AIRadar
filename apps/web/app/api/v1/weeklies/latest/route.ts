import { handleV1, OPTIONS } from "@/lib/v1/http";
import { assertKnownParams } from "@/lib/v1/params";
import { loadPeriod } from "@/lib/v1/period";

export { OPTIONS };

export const GET = handleV1(async (request) => {
  assertKnownParams(new URL(request.url), []);
  return loadPeriod("weekly");
});

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
