import type { LatestEvent } from "@/lib/api";

function safeDecode(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function eventHref(event: LatestEvent) {
  return `/event/${encodeURIComponent(event.event_id)}`;
}

export function findEventById(items: LatestEvent[], eventId: string) {
  const decodedId = safeDecode(eventId);
  return items.find((item) => item.event_id === eventId || item.event_id === decodedId);
}
