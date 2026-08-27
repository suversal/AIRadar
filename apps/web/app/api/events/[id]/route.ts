import { getEventDetailResult } from "@/lib/api";

/** Thin proxy so client components (the bookmarks page reads localStorage,
 * which only exists in the browser) can resolve an event's current content
 * without talking to the backend's internal-only base URL directly. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await getEventDetailResult(id);
  if (result.status === "not_found") {
    return Response.json({ error: "event_not_found" }, { status: 404 });
  }
  if (result.status === "upstream_error") {
    return Response.json(
      { error: "event_service_unavailable" },
      { status: 503, headers: { "Retry-After": "60" } },
    );
  }
  return Response.json(result.event);
}
