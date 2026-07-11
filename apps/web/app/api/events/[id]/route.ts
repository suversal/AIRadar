import { getEventDetail } from "@/lib/api";

/** Thin proxy so client components (the bookmarks page reads localStorage,
 * which only exists in the browser) can resolve an event's current content
 * without talking to the backend's internal-only base URL directly. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const event = await getEventDetail(id);
  if (!event) {
    return Response.json({ error: "event_not_found" }, { status: 404 });
  }
  return Response.json(event);
}
