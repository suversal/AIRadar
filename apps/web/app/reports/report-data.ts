import type { DailyReport, LatestEvent, LatestReport, PeriodReport } from "@/lib/api";
import { getDailySections } from "@/lib/markdown";
import { FOCUS_CATEGORIES, focusCategory, focusCategoryLabel } from "@/lib/taxonomy";

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
// 分组按 FOCUS_CATEGORIES 固定顺序输出，和日报的板块顺序一致。
function groupItemsByFocus(items: LatestEvent[]) {
  const grouped = new Map<string, LatestEvent[]>();
  for (const item of items) {
    const key = focusCategory(item.focus_category, item.scoring_category);
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }
  const ordered: Array<{ key: string; label: string; items: LatestEvent[] }> = [];
  for (const [key] of FOCUS_CATEGORIES) {
    const groupItems = grouped.get(key);
    if (groupItems?.length) {
      ordered.push({ key, label: categoryDisplayName(key, groupItems[0]), items: groupItems });
      grouped.delete(key);
    }
  }
  // 不在 FOCUS_CATEGORIES 里的残余分类（历史数据）排在最后，不丢内容
  for (const [key, groupItems] of grouped) {
    ordered.push({ key, label: categoryDisplayName(key, groupItems[0]), items: groupItems });
  }
  return ordered;
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

function mainlineFor(period: PeriodReport, mode: PeriodMode) {
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
  const top = period.items[0];
  if (!top) {
    return {
      title: `${prefix} AI 动态等待生成`,
      body: "本期收录的动态还不够多，完整的 AI 综述会在内容积累后自动生成。",
      ai: false,
    };
  }
  return {
    title: `${prefix} AI 动态一览`,
    body: `${prefix}代表内容包括“${top.title}”等。完整的 AI 综述稍后自动生成。`,
    ai: false,
  };
}

/** 封版状态：进行中的期次页面要明示「X 日封版」，读者才知道自己看的
 *  文字还会变。封版日 = range_end 的次日（跨期后第一批运行收尾）。 */
function sealStateFor(period: PeriodReport) {
  const sealed = Boolean(period.finalized_at);
  let sealDate: string | null = null;
  if (!sealed && period.range_end) {
    const end = new Date(`${period.range_end}T00:00:00`);
    if (!Number.isNaN(end.getTime())) {
      end.setDate(end.getDate() + 1);
      // 不用 toISOString()：它折回 UTC，在 UTC+8 会把 08-24 打回 08-23
      const month = String(end.getMonth() + 1).padStart(2, "0");
      const day = String(end.getDate()).padStart(2, "0");
      sealDate = `${end.getFullYear()}-${month}-${day}`;
    }
  }
  return { sealed, sealDate };
}

export type WeeklyCategory = {
  key: string;
  label: string;
  /** 该分类本周的 AI 概述；没生成过就是 null，行内退回头条标题 */
  note: string | null;
  count: number;
  /** 后端定序：多信源在前，组内按持续度再分位 */
  items: LatestEvent[];
  multiSourceCount: number;
};

/** 周报 = 日报的放大版：主线 + 分类概述 + 分类列表全露出。 */
export function buildWeeklyDigest(period: PeriodReport) {
  const noteByCategory = new Map(
    (period.theme_notes ?? [])
      .filter((note) => note.category)
      .map((note) => [note.category as string, note.note] as const),
  );
  const categories: WeeklyCategory[] = groupItemsByFocus(period.items).map((group) => ({
    key: group.key,
    label: group.label,
    // 旧格式期次没有分类概述，退回该类头条标题——和日报的历史期次同一取舍
    note: noteByCategory.get(group.key) ?? group.items[0]?.title ?? null,
    count: group.items.length,
    items: group.items,
    multiSourceCount: group.items.filter((item) => (item.source_count ?? 1) > 1).length,
  }));

  const coverageCount = period.stats?.coverage_count ?? period.items.length;
  const coveredDays = Math.max(period.report_dates.length, 1);
  const sourceCoverage =
    period.stats?.source_coverage_count ??
    new Set(period.items.map((item) => item.main_source?.id).filter(Boolean)).size;

  return {
    title: "AI·RADAR 周报",
    label: "WEEKLY",
    issueMeta: `VOL.${period.period_key ?? resolveRange(period).slice(0, 7)} · ${period.items.length} STORIES · AI RADAR WEEKLY`,
    periodKey: period.period_key ?? "",
    range: resolveRange(period),
    mainline: mainlineFor(period, "weekly"),
    categories,
    seal: sealStateFor(period),
    stats: [
      { label: "本周入选", value: period.items.length.toString() },
      { label: "期间收录", value: coverageCount.toString() },
      { label: "覆盖天数", value: coveredDays.toString() },
      { label: "信源覆盖", value: sourceCoverage.toString() },
    ],
  };
}

export type MonthlyTrend = {
  label: string;
  note: string;
  /** 证据事件：event_ids 在后端已按入选名单校验，这里只解析不补位——
   *  空列表就只显示论述，不拿别的事件冒充证据 */
  items: LatestEvent[];
};

/** 月报 = 趋势结构：定调总述 + 2-3 条趋势线（挂证据事件卡）+ 完整榜单。 */
export function buildMonthlyDigest(period: PeriodReport) {
  const byEventId = new Map(period.items.map((item) => [item.event_id, item] as const));
  const trends: MonthlyTrend[] = (period.theme_notes ?? [])
    .filter((note) => note.label && note.note)
    .map((note) => ({
      label: note.label,
      note: note.note,
      items: (note.event_ids ?? [])
        .map((eventId) => byEventId.get(eventId))
        .filter((item): item is LatestEvent => Boolean(item)),
    }));

  const coverageCount = period.stats?.coverage_count ?? period.items.length;
  const coveredDays = Math.max(period.report_dates.length, 1);
  const multiSourceRatio = period.stats?.multi_source_ratio;
  const categoryDistribution = Object.entries(period.stats?.category_distribution ?? {}).sort(
    (left, right) => right[1] - left[1],
  );

  return {
    title: "AI·RADAR 月报",
    label: "MONTHLY",
    issueMeta: `VOL.${period.period_key ?? resolveRange(period).slice(0, 7)} · ${period.items.length} STORIES · AI RADAR MONTHLY`,
    periodKey: period.period_key ?? "",
    range: resolveRange(period),
    mainline: mainlineFor(period, "monthly"),
    trends,
    /** 完整榜单：后端名单序（多信源 → 持续度 → 分位） */
    ranked: period.items,
    seal: sealStateFor(period),
    categoryDistribution,
    stats: [
      { label: "本月入选", value: period.items.length.toString() },
      { label: "期间收录", value: coverageCount.toString() },
      { label: "覆盖天数", value: coveredDays.toString() },
      {
        label: "多信源比例",
        value:
          multiSourceRatio !== undefined ? `${Math.round(multiSourceRatio * 100)}%` : "—",
      },
    ],
  };
}
