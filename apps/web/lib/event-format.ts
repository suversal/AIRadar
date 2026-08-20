// 事件流的日期/时间格式与按日分组,/latest、/all、/topics/[slug] 三个
// 时间线共用。此前是三份私有拷贝,修一处漏两处(lib/events.ts 的
// formatScore 注释早就点名要收编)。dateStyle 是唯一的真实差异:
// /latest 与主题详情用 "8/20",/all 用 "8月20日"。
// 分数格式化在 lib/events.ts 的 formatScore,不在这里重复。

import type { LatestEvent } from "@/lib/api";

export type DateKeyStyle = "numeric" | "long";

export function formatDateKey(value?: string, style: DateKeyStyle = "numeric") {
  if (!value) {
    return "日期未知";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 10) || "日期未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: style === "long" ? "long" : "numeric",
    day: "numeric",
  }).format(parsed);
}

export function formatWeekday(value?: string) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", { weekday: "long" }).format(parsed);
}

export function formatTime(value?: string) {
  if (!value) {
    return "--:--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

export function groupEventsByDate(items: LatestEvent[], style: DateKeyStyle = "numeric") {
  const groups = new Map<string, LatestEvent[]>();
  for (const item of items) {
    const key = formatDateKey(item.published_at, style);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return Array.from(groups.entries()).map(([dateLabel, events]) => ({
    dateLabel,
    weekday: formatWeekday(events[0]?.published_at),
    events,
  }));
}
