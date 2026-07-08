import type { DailyReport, LatestEvent, LatestReport } from "@/lib/api";
import { getDailySections } from "@/lib/markdown";

export type ReportHighlight = {
  label: string;
  title: string;
  count: number;
  items: LatestEvent[];
};

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
