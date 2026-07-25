import { getLatestReport } from "@/lib/api";

/** Thin proxy so the client-side "load more" feed on /latest can page
 * through the 7-day selected window without talking to the backend's
 * internal-only base URL directly (see /api/events/[id] for the same
 * pattern). */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const limit = Number(url.searchParams.get("limit") ?? "50") || 50;
  const offset = Number(url.searchParams.get("offset") ?? "0") || 0;
  const category = url.searchParams.get("category") ?? undefined;
  const focus = url.searchParams.get("focus") ?? undefined;
  const tag = url.searchParams.get("tag") ?? undefined;
  const q = url.searchParams.get("q") ?? undefined;

  const payload = await getLatestReport({ limit, offset, category, focus, tag, q });
  return Response.json(payload);
}
