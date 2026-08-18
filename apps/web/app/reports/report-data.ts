import type { DailyReport, LatestEvent, LatestReport, PeriodReport } from "@/lib/api";
import { getDailySections } from "@/lib/markdown";
import { focusCategory, focusCategoryLabel } from "@/lib/taxonomy";

export type ReportHighlight = {
  label: string;
  title: string;
  count: number;
  items: LatestEvent[];
};

export type PeriodMode = "weekly" | "monthly";

// AI mainline copy separates its 2-3 threads with blank lines; render each
// as its own paragraph instead of one dense block of text.
export function splitParagraphs(body: string): string[] {
  return body
    .split(/\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

export function categoryDisplayName(key: string, item?: LatestEvent) {
  return item?.focus_category_label ?? focusCategoryLabel(key);
}

// 排名由后端给定，这里只分组，不重排。final_score 只在同一个打分模型内部
// 可比：2026-08-13 换模型后高分变稀，前端再按原始分排一次，就会把后端按
// 模型分组归一化的结果原样抵消掉（见 api/public.py 的 sort_period_items）。
// 日报同理——一天只有一个模型，接口给的就是名次序。
export function summarizeCategoryHighlights(items: LatestEvent[], limit = 5): ReportHighlight[] {
  const grouped = new Map<string, LatestEvent[]>();
  for (const item of items) {
    const key = focusCategory(item.focus_category, item.scoring_category);
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }
  return Array.from(grouped.entries())
    .map(([key, groupItems]) => {
      return {
        label: categoryDisplayName(key, groupItems[0]),
        title: groupItems[0]?.title ?? "暂无标题",
        count: groupItems.length,
        items: groupItems,
      };
    })
    .sort((left, right) => right.count - left.count)
    .slice(0, limit);
}

export type DailyCategory = {
  key: string;
  label: string;
  /** 该分类当天的 AI 简述；没生成过就是 null，行内只显示条数 */
  note: string | null;
  count: number;
  /** 多信源的一组在前、单信源的一组在后，各自组内按分数降序（后端定序） */
  items: LatestEvent[];
  multiSourceCount: number;
};

export function buildDailyDigest(report: DailyReport) {
  // 分区顺序、组内顺序、以及"当天没有条目的分类不出现"都由后端定
  // （repositories/radar_repository.py 的 _resolve_daily_report_payload），
  // 这里不重排也不补空分类。
  const noteByCategory = new Map(
    (report.category_notes ?? []).map((note) => [note.category, note.note] as const),
  );
  const categories: DailyCategory[] = getDailySections(report).map((section) => ({
    key: section.key,
    label: section.label,
    // 没有 AI 简述时退回该类头条的标题——2026-08-17 之前的日报都没有生成过
    // 简述，直接显示「N 条动态」会让这些历史页面比改版前更没信息量。
    note: noteByCategory.get(section.key) ?? section.items[0]?.title ?? null,
    count: section.items.length,
    items: section.items,
    multiSourceCount: section.items.filter((item) => (item.source_count ?? 1) > 1).length,
  }));

  // 主线只在真写出来时显示。summary_status 不是 generated 时 mainline_* 是
  // 空串——当天没有任何多信源事件就属于这种情况，按约定整块不渲染，而不是
  // 编一段出来。这和周月报保留兜底文案的取舍不同：日报的头条就在下面的
  // 列表里，再复述一遍只是噪声。
  const mainline =
    report.summary_status === "generated" && report.mainline_title && report.mainline_body
      ? { title: report.mainline_title, body: report.mainline_body }
      : null;

  const uniqueTags = new Set(report.items.flatMap((item) => item.tags ?? []));

  return {
    title: "AI·RADAR 日报",
    reportDate: report.report_date,
    issueMeta: `VOL.${report.report_date.replaceAll("-", ".")} · ${report.article_count} STORIES · AI RADAR DAILY`,
    summary: report.summary,
    mainline,
    categories,
    sections: categories,
    stats: [
      { label: "今日精选", value: report.article_count.toString() },
      { label: "重点栏目", value: categories.length.toString() },
      { label: "涉及标签", value: uniqueTags.size.toString() },
      { label: "阅读时间", value: `≈${Math.max(3, Math.ceil(report.items.length * 0.7))} min` },
    ],
  };
}

export function latestToDailyReport(latest: LatestReport): DailyReport {
  const reportDate = latest.report_date ?? new Date().toISOString().slice(0, 10);
  const items = latest.items;
  return {
    report_date: reportDate,
    title: "AI·RADAR 日报",
    summary: items.length > 0 ? `精选 ${items.length} 条 AI 情报。` : "暂无可展示的日报内容。",
    updated_at: latest.updated_at,
    sections: {},
    items,
    article_count: items.length,
  };
}

function resolveRange(period: PeriodReport) {
  if (period.range_start && period.range_end) {
    return `${period.range_start} ~ ${period.range_end}`;
  }
  const today = new Date().toISOString().slice(0, 10);
  return `${today} ~ ${today}`;
}

function mainlineFor(
  period: PeriodReport,
  highlights: ReportHighlight[],
  mode: PeriodMode,
) {
  // the AI-written interval summary is the whole point of a period report;
  // fall back to a template only when it has not been generated yet.
  //
  // `generated` only means a snapshot row exists (see main.py period_report) -
  // it is true even when the AI call failed and the row holds the deterministic
  // fallback text. Without the status check the 2026-08 monthly report rendered
  // 「本期 AI 综述生成失败」under an "AI 综述" badge.
  if (
    period.generated &&
    period.summary_status !== "fallback" &&
    period.mainline_title &&
    period.mainline_body
  ) {
    return { title: period.mainline_title, body: period.mainline_body, ai: true };
  }
  if (period.mainline_title && period.mainline_body) {
    // a fallback row still carries the better copy of the two (it names the
    // period's top event); show it, just never as AI-written
    return { title: period.mainline_title, body: period.mainline_body, ai: false };
  }
  const prefix = mode === "weekly" ? "本周" : "本月";
  const top = highlights[0];
  if (!top) {
    return {
      title: `${prefix} AI 动态等待生成`,
      body: "本期收录的动态还不够多，完整的 AI 综述会在内容积累后自动生成。",
      ai: false,
    };
  }
  return {
    title: `${top.label}成为${prefix}主线`,
    body: `${prefix} AI 动态围绕“${top.label}”集中展开，代表内容包括“${top.title}”。完整的 AI 综述稍后自动生成。`,
    ai: false,
  };
}

export function buildPeriodDigest(period: PeriodReport, mode: PeriodMode) {
  const items = period.items;
  const highlights = summarizeCategoryHighlights(items, mode === "monthly" ? 5 : 6);
  const uniqueTags = new Set(items.flatMap((item) => item.tags ?? []));
  const range = resolveRange(period);
  const mainline = mainlineFor(period, highlights, mode);
  const selectedCount = items.filter((item) => item.selected).length;
  const coveredDays = Math.max(period.report_dates.length, 1);

  return {
    mode,
    title: mode === "weekly" ? "AI·RADAR 周报" : "AI·RADAR 月报",
    label: mode === "weekly" ? "WEEKLY" : "MONTHLY",
    issueMeta: `VOL.${period.period_key ?? range.slice(0, 7)} · ${items.length} STORIES · AI RADAR ${
      mode === "weekly" ? "WEEKLY" : "MONTHLY"
    }`,
    periodKey: period.period_key ?? "",
    themeNotes: period.theme_notes ?? [],
    range,
    mainline,
    highlights,
    sections: highlights,
    stats: [
      { label: "收录动态", value: items.length.toString() },
      { label: "入选精选", value: selectedCount.toString() },
      { label: "覆盖天数", value: coveredDays.toString() },
      { label: "阅读时间", value: `≈${mode === "weekly" ? 5 : 4} min` },
    ],
  };
}
