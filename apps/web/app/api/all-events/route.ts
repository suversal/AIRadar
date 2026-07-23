import { getAllEvents } from "@/lib/api";

/** Thin proxy so the client-side "load more" feed on /all can page through
 * the day-scoped event window without talking to the backend's
 * internal-only base URL directly (see /api/events/[id] for the same
 * pattern). */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const days = Number(url.searchParams.get("days") ?? "30") || 30;
  const limit = Number(url.searchParams.get("limit") ?? "50") || 50;
  const offset = Number(url.searchParams.get("offset") ?? "0") || 0;
  const topic = url.searchParams.get("topic") ?? undefined;

  const payload = await getAllEvents({ days, limit, offset, topic });
  return Response.json(payload);
}
