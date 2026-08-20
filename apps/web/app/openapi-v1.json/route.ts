import { CACHE, conditionalText } from "@/lib/v1/http";
import { buildOpenApiDocument } from "@/lib/v1/openapi";

/** OpenAPI 3.1 文档。放在 /api 之外是为了不被 robots 的 disallow 挡住。 */
export async function GET(request: Request) {
  return conditionalText(
    request,
    JSON.stringify(buildOpenApiDocument(), null, 2),
    "application/json; charset=utf-8",
    CACHE.feed,
  );
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
