// MCP 工具定义与实现。
//
// 六个工具，全部匿名只读。取数直接走 lib/v1 的内部函数而不是 HTTP 自调用：
// 少一跳，且窗口口径与 REST 天然一致。
//
// 边界一律显式报错，不静默放宽：limit=100 返回错误而不是悄悄给 30。
// Agent 拿到 30 条却以为是全部，会直接说"本周只有 30 条动态"。

import type { DailyReport, HotspotsPayload, LatestEvent, TopicsPayload } from "@/lib/api";
import { dailyCacheTier, latestDailyDate } from "@/lib/v1/daily";
import { CACHE } from "@/lib/v1/http";
import { ITEM_CATEGORIES, loadItems, type ItemWindow } from "@/lib/v1/items";
import { shapeItem, shapeStory, shapeTopics } from "@/lib/v1/shape";
import { fetchUpstream, UpstreamNotFound } from "@/lib/v1/upstream";
import { ATTRIBUTION_NOTE, beijingTime, formatItems } from "./format";

export type ToolDefinition = {
  name: string;
  title: string;
  description: string;
  inputSchema: Record<string, unknown>;
};

/** 工具调用失败时抛它：会翻成 isError 的工具结果而不是 JSON-RPC 错误，
 *  这样模型看得见原因，能自己改参数重试。 */
export class ToolError extends Error {}

type Args = Record<string, unknown>;

function intArg(args: Args, name: string, min: number, max: number, fallback: number): number {
  const raw = args[name];
  if (raw === undefined || raw === null) return fallback;
  if (typeof raw !== "number" || !Number.isInteger(raw)) {
    throw new ToolError(`${name} 必须是整数，收到 ${JSON.stringify(raw)}。`);
  }
  if (raw < min || raw > max) {
    throw new ToolError(
      `${name} 必须在 ${min} 到 ${max} 之间，收到 ${raw}。这是硬上限，不会自动改成边界值——需要更多条目请分多次查询或改用 REST API。`,
    );
  }
  return raw;
}

function enumArg<T extends string>(
  args: Args,
  name: string,
  values: readonly T[],
  fallback: T | undefined,
): T | undefined {
  const raw = args[name];
  if (raw === undefined || raw === null || raw === "") return fallback;
  if (typeof raw !== "string" || !(values as readonly string[]).includes(raw)) {
    throw new ToolError(`${name} 只能是 ${values.join(" | ")}，收到 ${JSON.stringify(raw)}。`);
  }
  return raw as T;
}

function stringArg(args: Args, name: string, options: { min: number; max: number }): string {
  const raw = args[name];
  if (typeof raw !== "string" || raw.trim() === "") {
    throw new ToolError(`${name} 是必填的字符串。`);
  }
  const value = raw.trim();
  if (value.length < options.min || value.length > options.max) {
    throw new ToolError(
      `${name} 长度必须在 ${options.min} 到 ${options.max} 字之间，收到 ${value.length} 字。`,
    );
  }
  return value;
}

const WINDOWS = ["24h", "7d"] as const;
const WINDOW_LABEL: Record<ItemWindow, string> = { "24h": "过去 24 小时", "7d": "最近 7 天" };

export const TOOLS: ToolDefinition[] = [
  {
    name: "radar_get_latest",
    title: "最新 AI 动态",
    description:
      "获取 AI·RADAR 在过去 24 小时或最近 7 天收录的动态。默认返回精选（经 AI 评分与多信源聚类后的高信噪比条目）；mode=all 返回同窗口的全部收录。回答「最近有什么 AI 新闻」「过去 24 小时最重要的几件事」用这个。",
    inputSchema: {
      type: "object",
      properties: {
        window: {
          type: "string",
          enum: [...WINDOWS],
          default: "24h",
          description: "时间窗口。只支持这两个值，没有更长的原生窗口。",
        },
        mode: {
          type: "string",
          enum: ["selected", "all"],
          default: "selected",
          description: "selected=精选（推荐），all=同窗口全部收录，量大且未过滤。",
        },
        limit: {
          type: "integer",
          minimum: 1,
          maximum: 30,
          default: 10,
          description: "返回条数，上限 30。",
        },
        category: {
          type: "string",
          enum: [...ITEM_CATEGORIES],
          description: "按分类筛选：model 模型 / product 产品 / industry 行业 / research 论文 / tutorial 技巧。",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "radar_search",
    title: "搜索 AI 动态",
    description:
      "在最近 7 天收录的 AI 动态里按关键词搜索，可用于查某个模型、公司、产品或人物的近期消息。注意窗口上限就是 7 天，更早的历史检索不支持。",
    inputSchema: {
      type: "object",
      properties: {
        q: {
          type: "string",
          minLength: 2,
          maxLength: 200,
          description: "关键词，2 到 200 字。例如「Claude」「英伟达」「开源模型」。",
        },
        window: { type: "string", enum: [...WINDOWS], default: "7d", description: "时间窗口。" },
        mode: {
          type: "string",
          enum: ["selected", "all"],
          default: "all",
          description: "搜索默认查全部收录（覆盖面更广）；只要高信噪比结果用 selected。",
        },
        limit: { type: "integer", minimum: 1, maximum: 30, default: 10, description: "返回条数，上限 30。" },
      },
      required: ["q"],
      additionalProperties: false,
    },
  },
  {
    name: "radar_get_hot_topics",
    title: "当前热点榜",
    description:
      "当前最热的 AI 事件排名。热度按同一事件被多少家信源同时报道计算，回答「现在 AI 圈最热的事是什么」。与 radar_get_latest 的区别：那个按时间倒序，这个按热度排序。",
    inputSchema: {
      type: "object",
      properties: {
        hours: { type: "integer", minimum: 1, maximum: 168, default: 48, description: "统计窗口小时数，上限 168（7 天）。" },
        limit: { type: "integer", minimum: 1, maximum: 10, default: 5, description: "返回条数，上限 10。榜很短是刻意的。" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "radar_get_story",
    title: "事件时间线",
    description:
      "读取一个事件的详情与多信源报道时间线。id 必须来自其它工具返回的「事件 ID」，不要自行构造或猜测——事件 ID 是聚类产物。",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "事件 ID，来自其它工具返回结果里的「事件 ID」字段。" },
      },
      required: ["id"],
      additionalProperties: false,
    },
  },
  {
    name: "radar_get_daily",
    title: "AI 日报",
    description:
      "读取 AI·RADAR 的精编日报，含 AI 撰写的主线综述与各分类简述。省略 date 返回最新一期。日报按上海时区日历日分期，当天那一期会随抓取滚动更新。",
    inputSchema: {
      type: "object",
      properties: {
        date: {
          type: "string",
          pattern: "^\\d{4}-\\d{2}-\\d{2}$",
          description: "期次日期 YYYY-MM-DD（上海时区日历日）。省略则取最新一期。",
        },
        limit: { type: "integer", minimum: 1, maximum: 30, default: 15, description: "正文里列出的条目数，上限 30。" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "radar_get_topics",
    title: "主题档案与本周雷达",
    description:
      "列出 AI·RADAR 的主题档案（公司与模型、技术方向两组）及各主题的周环比计数，并给出「本周雷达」——近 14 天仍在持续更新的多日多源事件。回答「什么正在变热」「最近哪家公司动作多」用这个。",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
];

async function getLatest(args: Args): Promise<string> {
  const window = enumArg(args, "window", WINDOWS, "24h") as ItemWindow;
  const mode = enumArg(args, "mode", ["selected", "all"] as const, "selected")!;
  const limit = intArg(args, "limit", 1, 30, 10);
  const category = enumArg(args, "category", ITEM_CATEGORIES, undefined);

  const { items, total } = await loadItems({ mode, window, limit, category });
  const scope = mode === "selected" ? "精选" : "全部收录";
  const filter = category ? `，分类 ${category}` : "";
  const heading = `AI·RADAR ${WINDOW_LABEL[window]}${scope}${filter}：窗口内共 ${total} 条，列出 ${items.length} 条。`;
  return (
    formatItems(
      heading,
      items,
      // 空结果要说清是"窗口内确实没有"，否则 Agent 容易改口说"服务不可用"
      `窗口内没有${category ? "该分类的" : ""}条目。这是真实情况，不是查询失败；可以换更长的 window 或去掉分类筛选再试。`,
    ) + ATTRIBUTION_NOTE
  );
}

async function search(args: Args): Promise<string> {
  const q = stringArg(args, "q", { min: 2, max: 200 });
  const window = enumArg(args, "window", WINDOWS, "7d") as ItemWindow;
  const mode = enumArg(args, "mode", ["selected", "all"] as const, "all")!;
  const limit = intArg(args, "limit", 1, 30, 10);

  const { items, total } = await loadItems({ mode, window, limit, q });
  const heading = `AI·RADAR 搜索「${q}」（${WINDOW_LABEL[window]}，${mode === "selected" ? "精选" : "全部收录"}）：命中 ${total} 条，列出 ${items.length} 条。`;
  return (
    formatItems(
      heading,
      items,
      `${WINDOW_LABEL[window]}内没有匹配「${q}」的条目。收录窗口最长就是 7 天，更早的内容查不到——如果这个话题更早发生过，这里查不到不代表没发生。`,
    ) + ATTRIBUTION_NOTE
  );
}

async function getHotTopics(args: Args): Promise<string> {
  const hours = intArg(args, "hours", 1, 168, 48);
  const limit = intArg(args, "limit", 1, 10, 5);

  const payload = await fetchUpstream<HotspotsPayload>(
    `/api/public/hotspots?hours=${hours}&limit=${limit}`,
    { revalidate: CACHE.hotTopics },
  );
  const items = (payload.items ?? []).map(shapeItem);
  const heading = `AI·RADAR 当前热点榜（近 ${payload.window_hours ?? hours} 小时，按多信源热度排序）：${items.length} 条。`;
  return (
    formatItems(heading, items, "当前窗口没有形成热点——需要同一件事被多家信源报道才会上榜。") +
    ATTRIBUTION_NOTE
  );
}

async function getStory(args: Args): Promise<string> {
  const id = stringArg(args, "id", { min: 1, max: 200 });
  let event: LatestEvent;
  try {
    event = await fetchUpstream<LatestEvent>(`/api/public/events/${encodeURIComponent(id)}`, {
      revalidate: CACHE.story,
    });
  } catch (error) {
    if (error instanceof UpstreamNotFound) {
      throw new ToolError(
        `没有事件 ${id}。事件 ID 只能来自其它工具返回的「事件 ID」字段，不要自行构造。`,
      );
    }
    throw error;
  }

  const story = shapeStory(event);
  const lines = [
    `# ${story.title}`,
    "",
    story.summary ?? story.oneLineSummary ?? "（暂无摘要）",
  ];
  if (story.reason) lines.push("", `**为什么值得看**：${story.reason}`);
  if (story.action) lines.push("", `**可以做什么**：${story.action}`);
  lines.push(
    "",
    `分类：${story.categoryLabel} · 信源数：${story.sourceCount} · ${
      story.timeBasis === "discovered" ? "收录于" : "时间"
    } ${beijingTime(story.publishedAt)}`,
    `阅读页：${story.links.radar}`,
  );
  if (story.links.original) lines.push(`第三方原文：${story.links.original}`);

  if (story.coverage.length > 0) {
    lines.push("", `## 报道时间线（${story.coverage.length} 篇）`, "");
    for (const entry of story.coverage) {
      lines.push(
        `- ${beijingTime(entry.publishedAt)} · ${entry.sourceName}${entry.isMain ? "（代表报道）" : ""}：${entry.title}`,
      );
      if (entry.links.original) lines.push(`  ${entry.links.original}`);
    }
  }
  // 说清为什么没有正文，否则 Agent 会反复调工具找全文
  lines.push("", "正文不通过 API 提供，请打开阅读页或第三方原文。");
  return lines.join("\n") + ATTRIBUTION_NOTE;
}

async function getDaily(args: Args): Promise<string> {
  const rawDate = args.date;
  const limit = intArg(args, "limit", 1, 30, 15);
  let date: string;
  if (rawDate === undefined || rawDate === null || rawDate === "") {
    date = await latestDailyDate();
  } else {
    if (typeof rawDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(rawDate)) {
      throw new ToolError(`date 必须是 YYYY-MM-DD，收到 ${JSON.stringify(rawDate)}。`);
    }
    date = rawDate;
  }

  // 当天那一期还在滚动更新，用归档档位会让 radar_get_daily 返回一个
  // 小时前的快照，而 /api/v1/dailies/latest 已经给出了新版本——同一份
  // 日报两个入口互相打架，正是本文件开头说要避免的事。
  const report = await fetchUpstream<DailyReport>(`/api/public/daily/${date}`, {
    revalidate: dailyCacheTier(date),
  });
  if ((report.article_count ?? 0) === 0) {
    throw new ToolError(`${date} 没有日报。日报按上海时区日历日分期，可用期次见 radar_get_daily 的最新一期或站内 /daily。`);
  }

  const lines = [`# ${report.title}`, ""];
  if (report.summary_status === "generated" && report.mainline_title) {
    lines.push(`## ${report.mainline_title}`, "", report.mainline_body ?? "");
  } else if (report.summary) {
    lines.push(report.summary);
  }
  for (const note of report.category_notes ?? []) {
    if (note.note) lines.push("", `**${note.label}**：${note.note}`);
  }

  const items = (report.items ?? []).slice(0, limit).map(shapeItem);
  lines.push(
    "",
    formatItems(
      `## 条目（本期共 ${report.article_count} 条，列出 ${items.length} 条）`,
      items,
      "本期没有条目。",
    ),
    "",
    `期次页面：${new URL(`/daily?date=${date}`, "https://radar.suversal.com").toString()}`,
  );
  return lines.join("\n") + ATTRIBUTION_NOTE;
}

async function getTopics(): Promise<string> {
  const payload = await fetchUpstream<TopicsPayload>("/api/public/topics", {
    revalidate: CACHE.topics,
  });
  const shaped = shapeTopics(payload);

  const lines = [
    `# AI·RADAR 主题档案（近 ${shaped.windowDays} 天，共 ${shaped.itemCount} 条收录）`,
  ];
  for (const group of shaped.groups) {
    lines.push("", `## ${group.name}`, "");
    for (const topic of group.topics) {
      const delta = topic.weekCount - topic.prevWeekCount;
      // 给绝对增量而不是倍数：基数小的时候倍数会放大噪声（1→3 是「涨 200%」）
      const trend = delta === 0 ? "持平" : delta > 0 ? `↑${delta}` : `↓${-delta}`;
      lines.push(
        `- ${topic.name}（id: ${topic.id}）：近 ${shaped.windowDays} 天 ${topic.count} 条，本周 ${topic.weekCount} 条 vs 上周 ${topic.prevWeekCount} 条（${trend}）`,
      );
    }
  }

  if (shaped.storylines.length > 0) {
    lines.push("", `## 本周雷达（近 ${shaped.storylineWindowDays} 天仍在更新的多日多源事件）`, "");
    for (const line of shaped.storylines) {
      lines.push(
        `- ${line.title} — ${line.sourceCount} 家报道，跨 ${line.days} 天，最近更新 ${line.lastSeenAt ?? "未知"}`,
        `  事件 ID：${line.id} · ${line.links.radar}`,
      );
    }
  }

  lines.push("", "按主题细查请用 radar_search，或访问主题页面。");
  return lines.join("\n") + ATTRIBUTION_NOTE;
}

const HANDLERS: Record<string, (args: Args) => Promise<string>> = {
  radar_get_latest: getLatest,
  radar_search: search,
  radar_get_hot_topics: getHotTopics,
  radar_get_story: getStory,
  radar_get_daily: getDaily,
  radar_get_topics: getTopics,
};

export async function callTool(name: string, args: Args): Promise<string> {
  // Object.hasOwn 而不是直接取值：普通对象查表会命中 Object.prototype，
  // name="constructor" 拿到 Object 函数、"toString" 拿到方法，两者都能
  // 通过 if (!handler) 守卫，最后把非字符串塞进 MCP 的 content[0].text，
  // 返回一个违反协议的结果而不是"没有这个工具"。
  const handler = Object.hasOwn(HANDLERS, name) ? HANDLERS[name] : undefined;
  if (!handler) {
    throw new ToolError(
      `没有这个工具：${name}。可用工具：${Object.keys(HANDLERS).join("、")}。`,
    );
  }
  return handler(args ?? {});
}
