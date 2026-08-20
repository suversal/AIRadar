// 内部 payload → v1 对外对象。
//
// 这是"对外合同"与"内部结构"之间唯一的翻译层。内部 LatestEvent 有 30 多个
// 字段，其中 model_used、ai_focus、selection_reason、hidden 这些是流水线自
// 己的账，外露就等于承诺它们不变。v1 只挑读者真正要用的，且一律改成驼峰、
// 把散落的 original_url / event_id 收进 links 结构里。
//
// 增字段安全，删字段和改类型是破坏性变更——v1 承诺不做后者。

import type { DailyReport, LatestEvent, TopicsPayload } from "@/lib/api";
import { siteUrl } from "@/lib/site";
import { categoryLabel, displayCategory, focusCategory, focusCategoryLabel } from "@/lib/taxonomy";

/** 站内阅读页。Agent 引用时应该给用户这个地址而不是直接甩第三方原文。 */
function radarLink(eventId: string): string {
  return new URL(`/event/${encodeURIComponent(eventId)}`, siteUrl).toString();
}

/** 时间戳统一成 Z 结尾的 UTC ISO 串。
 *  后端混着给 "+00:00" 和 "Z" 两种写法，字符串比较会踩坑。 */
function isoOrNull(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

export type V1Source = {
  name: string;
  /** 信源分级：T1 最高。用于判断可信度权重，不是封闭枚举，勿做穷举分支。 */
  tier: string | null;
  /** official = 官方渠道，media = 媒体报道，community = 社区讨论，
   *  research = 论文与机构。同样不是封闭枚举，未知值按 media 处理即可。 */
  category: string | null;
};

export type V1Item = {
  id: string;
  title: string;
  oneLineSummary: string | null;
  summary: string | null;
  reason: string | null;
  action: string | null;
  score: number | null;
  selected: boolean;
  category: string;
  categoryLabel: string;
  focus: string | null;
  focusLabel: string | null;
  tags: string[];
  topics: string[];
  sourceCount: number;
  language: string | null;
  author: string | null;
  source: V1Source;
  publishedAt: string | null;
  lastSeenAt: string | null;
  /**
   * publishedAt 到底是什么时间，三态：
   *
   * - `"published"` — 抓到了原文发布时间，可以写"发布于"
   * - `"discovered"` — 只有收录时间，必须写"收录于"，不得伪称发布时间
   * - `null` — 没有逐条标注，站内绝大多数条目是这种。
   *
   * null 不代表时间不可信：抽样 200 条，98% 的 publishedAt 明显早于 crawled_at，
   * 确实是信源给的发布时间。但也不能直接当成 published——抓取层拿不到原文时间时
   * 会退回 now()（crawlers/base.py 的 `published_at or datetime.now()`），
   * GitHub Trending 更是直接用抓取时刻，两者都不会标 time_basis。
   * 所以对 null 的正确做法是报时间而不下断言，两个方向的兜底都会说谎。
   */
  timeBasis: "published" | "discovered" | null;
  links: { original: string | null; radar: string };
};

export function shapeItem(event: LatestEvent): V1Item {
  const category = displayCategory(event.category);
  const focus = focusCategory(event.focus_category, event.scoring_category);
  return {
    id: event.event_id,
    title: event.title,
    oneLineSummary: event.one_line_summary ?? null,
    summary: event.summary ?? null,
    reason: event.reason ?? null,
    action: event.action ?? null,
    score: typeof event.final_score === "number" ? event.final_score : null,
    // selected 来自打分服务的分类阈值判定，不要从 score 反推——阈值按分类不同。
    selected: event.selected === true,
    category,
    categoryLabel: categoryLabel(event.category),
    focus: focus || null,
    focusLabel: focus ? focusCategoryLabel(focus) : null,
    tags: event.tags ?? [],
    // AI 打标的主题归属，可与 /api/v1/topics 的 topic id 对上
    topics: (event as { topic_ids?: string[] }).topic_ids ?? [],
    sourceCount: event.source_count ?? 1,
    language: event.source_language ?? null,
    author: event.author ?? null,
    source: {
      name: event.main_source?.name ?? "未知来源",
      tier: event.main_source?.tier ?? null,
      category: event.main_source?.category ?? null,
    },
    publishedAt: isoOrNull(event.published_at),
    lastSeenAt: isoOrNull(event.last_seen_at),
    // 只认后端明确标注的两个值，其余（含缺失）一律 null——见字段注释，
    // 缺省到 "published" 会让每一条都声称时间可信。
    timeBasis:
      event.time_basis === "discovered" || event.time_basis === "published"
        ? event.time_basis
        : null,
    links: {
      original: event.original_url ?? null,
      radar: radarLink(event.event_id),
    },
  };
}

export type V1CoverageEntry = {
  title: string;
  sourceName: string;
  publishedAt: string | null;
  isMain: boolean;
  links: { original: string | null; radar: string };
};

export type V1Story = V1Item & {
  /** 同一事件的多信源报道时间线，按发布时间升序。 */
  coverage: V1CoverageEntry[];
};

/**
 * 事件详情。
 *
 * 刻意不内联 original_paragraphs / translated_* ——站内阅读页可以展示，
 * 但通过 API 批量取走第三方正文是再分发，和"匿名只读"的授权边界不是
 * 一回事。要正文请走 links.original 或 links.radar。
 */
export function shapeStory(event: LatestEvent): V1Story {
  const coverage = (event.coverage ?? [])
    .map((entry) => ({
      title: entry.title,
      sourceName: entry.source_name,
      publishedAt: isoOrNull(entry.published_at),
      isMain: entry.is_main === true,
      links: {
        original: entry.source_url ?? null,
        radar: radarLink(entry.event_id),
      },
    }))
    .sort((a, b) => {
      // 时间线要按报道先后读；缺时间戳的沉到末尾，不要插在中间制造假顺序。
      if (a.publishedAt === b.publishedAt) return 0;
      if (a.publishedAt === null) return 1;
      if (b.publishedAt === null) return -1;
      return a.publishedAt < b.publishedAt ? -1 : 1;
    });
  return { ...shapeItem(event), coverage };
}

export type V1Daily = {
  date: string;
  title: string;
  summary: string;
  mainlineTitle: string | null;
  mainlineBody: string | null;
  /** generated 才是 AI 真写出来的；其余取值下 mainline* 为空，不要渲染。 */
  summaryStatus: string | null;
  categoryNotes: { category: string; label: string; note: string }[];
  itemCount: number;
  sections: { focus: string; label: string; items: V1Item[] }[];
  items: V1Item[];
  updatedAt: string | null;
  links: { radar: string };
};

export function shapeDaily(report: DailyReport): V1Daily {
  const sections = Object.entries(report.sections ?? {}).map(([focus, items]) => ({
    focus,
    label: focusCategoryLabel(focus),
    items: (items ?? []).map(shapeItem),
  }));
  return {
    date: report.report_date,
    title: report.title,
    summary: report.summary,
    mainlineTitle: report.mainline_title || null,
    mainlineBody: report.mainline_body || null,
    summaryStatus: report.summary_status ?? null,
    categoryNotes: (report.category_notes ?? []).map((note) => ({
      category: note.category,
      label: note.label,
      note: note.note,
    })),
    itemCount: report.article_count ?? 0,
    sections,
    items: (report.items ?? []).map(shapeItem),
    updatedAt: isoOrNull(report.updated_at),
    links: { radar: new URL(`/daily?date=${report.report_date}`, siteUrl).toString() },
  };
}

export type V1Topic = {
  id: string;
  name: string;
  description: string;
  /** 窗口内收录条数（见响应的 windowDays） */
  count: number;
  weekCount: number;
  prevWeekCount: number;
  latestPublishedAt: string | null;
  links: { radar: string };
};

export type V1TopicGroup = {
  id: string;
  name: string;
  description: string;
  topics: V1Topic[];
};

export type V1Storyline = {
  id: string;
  title: string;
  sourceCount: number;
  /** 报道跨越的自然日数（上海时区），≥2 才算故事线 */
  days: number;
  lastSeenAt: string | null;
  links: { radar: string };
};

export function shapeTopics(payload: TopicsPayload): {
  groups: V1TopicGroup[];
  storylines: V1Storyline[];
  itemCount: number;
  windowDays: number;
  storylineWindowDays: number;
} {
  return {
    groups: (payload.groups ?? []).map((group) => ({
      id: group.id,
      name: group.name,
      description: group.description ?? "",
      topics: (group.topics ?? []).map((topic) => ({
        id: topic.id,
        name: topic.name,
        description: topic.description ?? "",
        count: topic.count ?? 0,
        weekCount: topic.week_count ?? 0,
        prevWeekCount: topic.prev_week_count ?? 0,
        latestPublishedAt: topic.latest_published_at ?? null,
        links: {
          radar: new URL(`/topics/${encodeURIComponent(topic.id)}`, siteUrl).toString(),
        },
      })),
    })),
    storylines: (payload.storylines ?? []).map((line) => ({
      id: line.event_id,
      title: line.title,
      sourceCount: line.source_count,
      days: line.days,
      lastSeenAt: line.last_seen_at ?? null,
      links: { radar: radarLink(line.event_id) },
    })),
    itemCount: payload.article_count ?? 0,
    windowDays: payload.window_days ?? 90,
    storylineWindowDays: payload.storyline_window_days ?? 14,
  };
}
