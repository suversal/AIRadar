import { getAllEvents } from "@/lib/api";
import { clampInt, DAYS_BOUNDS, LIMIT_BOUNDS, OFFSET_BOUNDS } from "@/lib/query-params";

/** Thin proxy so the client-side "load more" feed on /all can page through
 * the day-scoped event window without talking to the backend's
 * internal-only base URL directly (see /api/events/[id] for the same
 * pattern). */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const days = clampInt(url.searchParams.get("days"), DAYS_BOUNDS);
  const limit = clampInt(url.searchParams.get("limit"), LIMIT_BOUNDS);
  const offset = clampInt(url.searchParams.get("offset"), OFFSET_BOUNDS);
  const category = url.searchParams.get("category") ?? undefined;
  const focus = url.searchParams.get("focus") ?? undefined;
  const source = url.searchParams.get("source") ?? undefined;
  const tag = url.searchParams.get("tag") ?? undefined;
  const topic = url.searchParams.get("topic") ?? undefined;
  const q = url.searchParams.get("q") ?? undefined;

  const payload = await getAllEvents({
    days,
    limit,
    offset,
    category,
    focus,
    source,
    tag,
    topic,
    q,
  });
  return Response.json(payload);
}
