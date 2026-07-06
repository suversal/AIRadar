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

function searchableText(event: LatestEvent) {
  return [
    event.title,
    event.category,
    event.category_label,
    event.one_line_summary,
    event.summary,
    event.reason,
    event.action,
    event.main_source?.name,
    ...(event.tags ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function searchEvents(items: LatestEvent[], query: string) {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (terms.length === 0) {
    return items;
  }
  return items.filter((item) => {
    const text = searchableText(item);
    return terms.every((term) => text.includes(term));
  });
}
