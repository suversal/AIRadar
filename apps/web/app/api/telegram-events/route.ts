import { getTelegramEvents } from "@/lib/api";
import { clampInt, DAYS_BOUNDS, LIMIT_BOUNDS, OFFSET_BOUNDS } from "@/lib/query-params";

/** Server-side proxy used by the Telegram feed's infinite-scroll client. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const days = clampInt(url.searchParams.get("days"), DAYS_BOUNDS);
  const limit = clampInt(url.searchParams.get("limit"), LIMIT_BOUNDS);
  const offset = clampInt(url.searchParams.get("offset"), OFFSET_BOUNDS);
  const channel = url.searchParams.get("channel") ?? undefined;
  const q = url.searchParams.get("q") ?? undefined;

  const payload = await getTelegramEvents({ days, limit, offset, channel, q });
  return Response.json(payload);
}
