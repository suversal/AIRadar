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

/** 评分的统一展示口径：四舍五入到整数。
 *
 * 分数带一位小数是打分链路的内部精度（tier 系数乘出来的），展示层一律取整
 * ——同一条内容在精选页显示 77、在日报显示 77.0 会让人以为是两个数。
 * 注意 components/all-events-feed.tsx 与 latest-events-feed.tsx 里还各有一份
 * 同样实现的私有拷贝，早于这个函数存在，可以择机指过来。
 */
export function formatScore(score?: number | null) {
  if (typeof score !== "number") {
    return "--";
  }
  return Math.round(score).toString();
}
