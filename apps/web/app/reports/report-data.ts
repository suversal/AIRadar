import type { DailyReport, LatestEvent, LatestReport } from "@/lib/api";
import { getDailySections } from "@/lib/markdown";

export type ReportHighlight = {
  label: string;
  title: string;
  count: number;
  items: LatestEvent[];
};

export type PeriodMode = "weekly" | "monthly";

const fallbackCategoryLabels: Record<string, string> = {
  model_release: "模型发布/更新",
  product_release: "产品发布/更新",
  industry: "行业动态",
  research: "论文研究",
  tutorial: "技巧与观点",
  uncategorized: "其他动态",
};

export function categoryDisplayName(key: string, item?: LatestEvent) {
  return item?.category_label ?? fallbackCategoryLabels[key] ?? key;
}

export function summarizeCategoryHighlights(items: LatestEvent[], limit = 5): ReportHighlight[] {
  const grouped = new Map<string, LatestEvent[]>();
  for (const item of items) {
    const key = item.category ?? "uncategorized";
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }
  return Array.from(grouped.entries())
    .map(([key, groupItems]) => {
      const sorted = [...groupItems].sort((left, right) => (right.final_score ?? 0) - (left.final_score ?? 0));
      return {
        label: categoryDisplayName(key, sorted[0]),
        title: sorted[0]?.title ?? "暂无标题",
        count: groupItems.length,
        items: sorted,
      };
    })
    .sort((left, right) => right.count - left.count)
    .slice(0, limit);
}

export function buildDailyDigest(report: DailyReport) {
  const sections = getDailySections(report);
  const highlights = summarizeCategoryHighlights(report.items);
  const uniqueTags = new Set(report.items.flatMap((item) => item.tags ?? []));

  return {
    title: "AIHOT 日报",
    reportDate: report.report_date,
    issueMeta: `VOL.${report.report_date.replaceAll("-", ".")} · ${report.article_count} STORIES · AI HOT DAILY`,
    summary: report.summary,
    sections,
    highlights,
    stats: [
      { label: "精选事件", value: report.article_count.toString() },
      { label: "重点栏目", value: sections.length.toString() },
      { label: "标签信号", value: uniqueTags.size.toString() },
      { label: "阅读时间", value: `≈${Math.max(3, Math.ceil(report.items.length * 0.7))} min` },
    ],
  };
}

export function latestToDailyReport(latest: LatestReport): DailyReport {
  const reportDate = latest.report_date ?? new Date().toISOString().slice(0, 10);
  const items = latest.items;
  return {
    report_date: reportDate,
    title: "AIHOT 日报",
    summary: items.length > 0 ? `精选 ${items.length} 条 AI 情报。` : "暂无可展示的日报内容。",
    updated_at: latest.updated_at,
    sections: {},
    items,
    article_count: items.length,
  };
}

function sortByScore(items: LatestEvent[]) {
  return [...items].sort((left, right) => (right.final_score ?? 0) - (left.final_score ?? 0));
}

function addDays(date: Date, days: number) {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function formatDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function resolveRange(reportDate: string | null | undefined, mode: PeriodMode) {
  const anchor = reportDate ? new Date(`${reportDate}T00:00:00`) : new Date();
  const safeAnchor = Number.isNaN(anchor.getTime()) ? new Date() : anchor;
  if (mode === "monthly") {
    const start = new Date(safeAnchor.getFullYear(), safeAnchor.getMonth(), 1);
    const end = new Date(safeAnchor.getFullYear(), safeAnchor.getMonth() + 1, 0);
    return `${formatDate(start)} ~ ${formatDate(end)}`;
  }
  return `${formatDate(addDays(safeAnchor, -6))} ~ ${formatDate(safeAnchor)}`;
}

function mainlineFor(highlights: ReportHighlight[], mode: PeriodMode) {
  const top = highlights[0];
  if (!top) {
    return {
      title: mode === "weekly" ? "本周 AI 动态等待生成" : "本月 AI 动态等待生成",
      body: "当前还没有足够事件形成主线。刷新日报后，这里会自动聚合本期主线。",
    };
  }
  const prefix = mode === "weekly" ? "本周" : "本月";
  return {
    title: `${top.label}成为${prefix}主线`,
    body: `${prefix} AI 动态围绕“${top.label}”集中展开，代表事件包括“${top.title}”。系统从当前可读事件中抽取主题、评分、标签和来源信号，形成这份周期综述。`,
  };
}

export function buildPeriodDigest(latest: LatestReport, mode: PeriodMode) {
  const items = sortByScore(latest.items);
  const highlights = summarizeCategoryHighlights(items, mode === "monthly" ? 5 : 6);
  const uniqueTags = new Set(items.flatMap((item) => item.tags ?? []));
  const range = resolveRange(latest.report_date, mode);
  const mainline = mainlineFor(highlights, mode);
  const selectedCount = items.filter((item) => (item.final_score ?? 0) >= 65).length;

  return {
    mode,
    title: mode === "weekly" ? "AIHOT 周报" : "AIHOT 月报",
    label: mode === "weekly" ? "WEEKLY" : "MONTHLY",
    issueMeta:
      mode === "weekly"
        ? `VOL.${range.slice(0, 4)}-W · ${items.length} STORIES · AI HOT WEEKLY`
        : `VOL.${range.slice(0, 7)} · ${items.length} STORIES · AI HOT MONTHLY`,
    range,
    mainline,
    highlights,
    sections: highlights,
    stats: [
      { label: "独立事件", value: items.length.toString() },
      { label: "条精选", value: selectedCount.toString() },
      { label: mode === "weekly" ? "期日报浓缩" : "天趋势聚合", value: mode === "weekly" ? "7" : "30" },
      { label: "阅读本页", value: `≈${mode === "weekly" ? 5 : 4} min` },
    ],
  };
}
