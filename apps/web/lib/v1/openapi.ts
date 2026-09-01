// OpenAPI 3.1 文档。字段与错误码的权威来源——文档站和 Skill 都可以过时，
// 这份不行，所以枚举值直接引用代码里的常量，不再手抄一遍。

import { siteUrl } from "@/lib/site";
import { ITEM_CATEGORIES, ITEM_FOCUSES, ITEM_MODES, ITEM_WINDOWS } from "./items";

const ERROR_CODES = [
  "invalid_parameter",
  "unknown_parameter",
  "duplicate_parameter",
  "not_found",
  "upstream_unavailable",
  "internal_error",
];

function problemResponse(description: string) {
  return {
    description,
    content: { "application/problem+json": { schema: { $ref: "#/components/schemas/Problem" } } },
  };
}

const COMMON_ERRORS = {
  "400": problemResponse("参数不合法、未声明或重复。接口不会自动改成边界值。"),
  "404": problemResponse("资源不存在。"),
  "503": problemResponse("上游数据源暂时不可用，请退避后重试。"),
};

function queryParam(
  name: string,
  schema: Record<string, unknown>,
  description: string,
): Record<string, unknown> {
  return { name, in: "query", required: false, schema, description };
}

export function buildOpenApiDocument(): Record<string, unknown> {
  return {
    openapi: "3.1.0",
    info: {
      title: "AI·RADAR 公开 API",
      version: "1.0.0",
      summary: "中文 AI 情报的匿名只读接口",
      description: [
        "全部端点匿名只读，不需要 API Key，支持 CORS。",
        "",
        "**条件请求**：每个响应都带 ETag，用 `If-None-Match` 轮询，未变化返回 304。",
        "轮询间隔取响应 `Cache-Control` 里的 `s-maxage`（items 60 秒、hot-topics 300 秒）；",
        "更密只会拿到同一份共享缓存副本。不提供 SSE、Webhook 或流式订阅。",
        "",
        "**严格参数**：未声明的参数、重复的参数、越界的值一律返回 400，不会静默放宽。",
        "请移除 cache-buster 与未知参数。",
        "",
        "**边界**：动态检索的原生时间窗只有 24h 和 7d；不返回第三方原文正文。更长时间尺度请读取编辑成品周报/月报。",
        "",
        "**授权**：个人非商业、公益非商业、组织内部使用免费。面向外部的商业产品、",
        "收费服务、客户交付、代理接口、数据转售、公开镜像或批量再分发须先取得书面授权。",
      ].join("\n"),
      contact: { url: new URL("/feedback", siteUrl).toString() },
    },
    servers: [{ url: siteUrl }],
    paths: {
      "/api/v1/items": {
        get: {
          summary: "条目列表",
          description:
            "精选或全部收录，按 publishedAt 倒序。默认 mode=selected（经 AI 评分与多信源聚类的高信噪比条目）。",
          operationId: "listItems",
          parameters: [
            queryParam("mode", { type: "string", enum: [...ITEM_MODES], default: "selected" }, "selected 精选；all 同窗口全部收录。"),
            queryParam("window", { type: "string", enum: [...ITEM_WINDOWS], default: "7d" }, "时间窗口。只有这两个值。"),
            queryParam("limit", { type: "integer", minimum: 1, maximum: 100, default: 50 }, "返回条数。"),
            queryParam("offset", { type: "integer", minimum: 0, maximum: 10000, default: 0 }, "分页偏移。"),
            queryParam("category", { type: "string", enum: [...ITEM_CATEGORIES] }, "展示分类。"),
            queryParam("focus", { type: "string", enum: [...ITEM_FOCUSES] }, "阅读焦点分类。"),
            queryParam("q", { type: "string", minLength: 2, maxLength: 200 }, "关键词，2–200 字。"),
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/ItemList" } } },
            },
            "304": { description: "自上次请求以来内容未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/hot-topics": {
        get: {
          summary: "当前热点榜",
          description:
            "按多信源热度排序，回答「现在什么最热」。同一件事被多家同时报道才会冒头，所以榜很短。",
          operationId: "listHotTopics",
          parameters: [
            queryParam("hours", { type: "integer", minimum: 1, maximum: 168, default: 48 }, "统计窗口小时数。"),
            queryParam("limit", { type: "integer", minimum: 1, maximum: 20, default: 10 }, "返回条数。"),
            queryParam("category", { type: "string", enum: [...ITEM_CATEGORIES] }, "展示分类。"),
            queryParam("focus", { type: "string", enum: [...ITEM_FOCUSES] }, "阅读焦点分类。"),
            queryParam("q", { type: "string", minLength: 2, maxLength: 200 }, "关键词。"),
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/HotTopicList" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/stories/{publicId}": {
        get: {
          summary: "事件详情与报道时间线",
          description:
            "publicId 只应来自其它端点返回的 items[].id，不要自行构造——事件 ID 是聚类产物。不返回第三方原文正文。",
          operationId: "getStory",
          parameters: [
            {
              name: "publicId",
              in: "path",
              required: true,
              schema: { type: "string" },
              description: "事件 ID。",
            },
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/StoryResponse" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/dailies": {
        get: {
          summary: "日报期次索引",
          operationId: "listDailies",
          parameters: [
            queryParam("limit", { type: "integer", minimum: 1, maximum: 100, default: 30 }, "返回期数。"),
            queryParam("offset", { type: "integer", minimum: 0, maximum: 10000, default: 0 }, "分页偏移。"),
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/DailyIndex" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/dailies/latest": {
        get: {
          summary: "最新一期日报",
          description: "按上海时区日历日分期。当天那一期会随抓取滚动更新，隔天定版。",
          operationId: "getLatestDaily",
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/DailyResponse" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/dailies/{date}": {
        get: {
          summary: "指定日期的日报",
          operationId: "getDaily",
          parameters: [
            {
              name: "date",
              in: "path",
              required: true,
              schema: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
              description: "上海时区的日历日，YYYY-MM-DD。",
            },
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/DailyResponse" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/weeklies": {
        get: {
          summary: "周报期次索引",
          operationId: "listWeeklies",
          parameters: [
            queryParam("limit", { type: "integer", minimum: 1, maximum: 100, default: 30 }, "返回期数。"),
            queryParam("offset", { type: "integer", minimum: 0, maximum: 10000, default: 0 }, "分页偏移。"),
          ],
          responses: {
            "200": { description: "成功", content: { "application/json": { schema: { $ref: "#/components/schemas/PeriodIndex" } } } },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/weeklies/latest": {
        get: {
          summary: "最新可用周报",
          description: "可能是仍在更新的当前周；看 report.finalizedAt 判断是否封版。",
          operationId: "getLatestWeekly",
          responses: {
            "200": { description: "成功", content: { "application/json": { schema: { $ref: "#/components/schemas/PeriodResponse" } } } },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/weeklies/{key}": {
        get: {
          summary: "指定 ISO 周的周报",
          operationId: "getWeekly",
          parameters: [{ name: "key", in: "path", required: true, schema: { type: "string", pattern: "^\\d{4}-W\\d{2}$" }, description: "ISO 周期 YYYY-Www。" }],
          responses: {
            "200": { description: "成功", content: { "application/json": { schema: { $ref: "#/components/schemas/PeriodResponse" } } } },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/monthlies": {
        get: {
          summary: "月报期次索引",
          operationId: "listMonthlies",
          parameters: [
            queryParam("limit", { type: "integer", minimum: 1, maximum: 100, default: 30 }, "返回期数。"),
            queryParam("offset", { type: "integer", minimum: 0, maximum: 10000, default: 0 }, "分页偏移。"),
          ],
          responses: {
            "200": { description: "成功", content: { "application/json": { schema: { $ref: "#/components/schemas/PeriodIndex" } } } },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/monthlies/latest": {
        get: {
          summary: "最新可用月报",
          description: "可能是仍在更新的当前月；看 report.finalizedAt 判断是否封版。",
          operationId: "getLatestMonthly",
          responses: {
            "200": { description: "成功", content: { "application/json": { schema: { $ref: "#/components/schemas/PeriodResponse" } } } },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/monthlies/{key}": {
        get: {
          summary: "指定月份的月报",
          operationId: "getMonthly",
          parameters: [{ name: "key", in: "path", required: true, schema: { type: "string", pattern: "^\\d{4}-\\d{2}$" }, description: "月份 YYYY-MM。" }],
          responses: {
            "200": { description: "成功", content: { "application/json": { schema: { $ref: "#/components/schemas/PeriodResponse" } } } },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/topics": {
        get: {
          summary: "主题档案与本周雷达",
          description:
            "两组主题（公司与模型 / 技术方向）及周环比计数，外加近 14 天仍在更新的多日多源事件。",
          operationId: "listTopics",
          parameters: [
            queryParam(
              "days",
              { type: "integer", minimum: 14, maximum: 90, default: 90 },
              "计数窗口。下限 14——周环比固定比较「今天-6」与「今天-13」两段，窗口更短会让每个主题都被算成暴涨。",
            ),
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/TopicList" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
      "/api/v1/topics/{slug}": {
        get: {
          summary: "单个主题的档案",
          operationId: "getTopicDetail",
          parameters: [
            { name: "slug", in: "path", required: true, schema: { type: "string" }, description: "主题 id，来自 /api/v1/topics。" },
            queryParam("limit", { type: "integer", minimum: 1, maximum: 100, default: 60 }, "返回条数。"),
            queryParam("offset", { type: "integer", minimum: 0, maximum: 10000, default: 0 }, "分页偏移。"),
          ],
          responses: {
            "200": {
              description: "成功",
              content: { "application/json": { schema: { $ref: "#/components/schemas/TopicDetail" } } },
            },
            "304": { description: "未变化。" },
            ...COMMON_ERRORS,
          },
        },
      },
    },
    components: {
      schemas: {
        Problem: {
          type: "object",
          description: "RFC 9457 Problem Details。按 code 分支，不要解析 detail 文案。",
          required: ["type", "title", "status", "detail", "code", "requestId"],
          properties: {
            type: { type: "string", format: "uri" },
            title: { type: "string" },
            status: { type: "integer" },
            detail: { type: "string" },
            code: { type: "string", enum: ERROR_CODES },
            requestId: { type: "string", description: "反馈问题时附上它即可定位。" },
          },
        },
        Links: {
          type: "object",
          required: ["radar"],
          properties: {
            original: {
              type: ["string", "null"],
              format: "uri",
              description: "第三方原文地址。",
            },
            radar: {
              type: "string",
              format: "uri",
              description: "站内阅读页。引用时优先给用户这个。",
            },
          },
        },
        Source: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string" },
            tier: { type: ["string", "null"], description: "信源分级，T1 最高。非封闭枚举。" },
            category: {
              type: ["string", "null"],
              description: "official 官方 / media 媒体 / community 社区 / research 论文。非封闭枚举，未知值按 media 处理。",
            },
          },
        },
        Item: {
          type: "object",
          required: ["id", "title", "selected", "category", "categoryLabel", "tags", "topics", "sourceCount", "source", "timeBasis", "links"],
          properties: {
            id: { type: "string", description: "事件 ID。调 /api/v1/stories/{id} 用它，不要自行构造。" },
            title: { type: "string", description: "中文标题，AI 生成。" },
            oneLineSummary: { type: ["string", "null"] },
            summary: { type: ["string", "null"], description: "中文摘要，AI 基于第三方报道生成，只能当线索。" },
            reason: { type: ["string", "null"], description: "推荐理由：为什么这条值得看。" },
            action: { type: ["string", "null"], description: "建议动作。" },
            score: { type: ["number", "null"], description: "0–100 综合评分。" },
            selected: { type: "boolean", description: "是否入选精选。阈值按分类不同，不要从 score 反推。" },
            category: { type: "string", enum: [...ITEM_CATEGORIES] },
            categoryLabel: { type: "string" },
            focus: { type: ["string", "null"], enum: [...ITEM_FOCUSES, null] },
            focusLabel: { type: ["string", "null"] },
            tags: { type: "array", items: { type: "string" } },
            topics: {
              type: "array",
              items: { type: "string" },
              description: "AI 打标的主题归属，可与 /api/v1/topics 的 topic id 对上。",
            },
            sourceCount: { type: "integer", description: "报道这件事的信源数量。" },
            language: { type: ["string", "null"] },
            author: { type: ["string", "null"] },
            source: { $ref: "#/components/schemas/Source" },
            publishedAt: { type: ["string", "null"], format: "date-time" },
            lastSeenAt: { type: ["string", "null"], format: "date-time" },
            timeBasis: {
              type: ["string", "null"],
              enum: ["published", "discovered", null],
              description:
                "publishedAt 的性质，不是时间本身（publishedAt 恒有值）。published=已确认是原文发布时间；discovered=已确认只有收录时间，必须写「收录于」；null=没有逐条标注，站内绝大多数条目是这种。抽样 200 条，98% 的时间戳明显早于抓取时刻，确实是原文发布时间；少数没有发布时间概念的来源（如 GitHub Trending）会用收录时刻且未标注。对 null 直接报时间即可，不必逐条存疑，也不要主动断言为发布时间。",
            },
            links: { $ref: "#/components/schemas/Links" },
          },
        },
        Coverage: {
          type: "object",
          required: ["title", "sourceName", "isMain", "links"],
          properties: {
            title: { type: "string" },
            sourceName: { type: "string" },
            publishedAt: { type: ["string", "null"], format: "date-time" },
            isMain: { type: "boolean", description: "是否为该事件的代表报道。" },
            links: { $ref: "#/components/schemas/Links" },
          },
        },
        Page: {
          type: "object",
          required: ["count", "limit", "offset", "total", "hasMore"],
          properties: {
            count: { type: "integer", description: "本页条数。" },
            limit: { type: "integer" },
            offset: { type: "integer" },
            total: { type: "integer", description: "窗口内命中总数。" },
            hasMore: { type: "boolean" },
          },
        },
        ItemList: {
          type: "object",
          required: ["schemaVersion", "mode", "window", "sort", "page", "items"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            mode: { type: "string", enum: [...ITEM_MODES] },
            window: { type: "string", enum: [...ITEM_WINDOWS] },
            sort: { type: "string", const: "publishedAt:desc" },
            page: { $ref: "#/components/schemas/Page" },
            items: { type: "array", items: { $ref: "#/components/schemas/Item" } },
          },
        },
        HotTopicList: {
          type: "object",
          required: ["schemaVersion", "windowHours", "sort", "count", "items"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            windowHours: { type: "integer" },
            sort: { type: "string", const: "heat:desc" },
            count: { type: "integer" },
            items: { type: "array", items: { $ref: "#/components/schemas/Item" } },
          },
        },
        StoryResponse: {
          type: "object",
          required: ["schemaVersion", "story"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            story: {
              allOf: [
                { $ref: "#/components/schemas/Item" },
                {
                  type: "object",
                  required: ["coverage"],
                  properties: {
                    coverage: {
                      type: "array",
                      items: { $ref: "#/components/schemas/Coverage" },
                      description: "多信源报道时间线，按发布时间升序，缺时间戳的排在末尾。",
                    },
                  },
                },
              ],
            },
          },
        },
        DailyIndex: {
          type: "object",
          required: ["schemaVersion", "page", "items"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            page: { $ref: "#/components/schemas/Page" },
            items: {
              type: "array",
              items: {
                type: "object",
                required: ["date", "links"],
                properties: {
                  date: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
                  links: {
                    type: "object",
                    properties: {
                      radar: { type: "string", format: "uri" },
                      api: { type: "string", format: "uri" },
                    },
                  },
                },
              },
            },
          },
        },
        DailyResponse: {
          type: "object",
          required: ["schemaVersion", "report"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            report: {
              type: "object",
              required: ["date", "title", "itemCount", "sections", "items"],
              properties: {
                date: { type: "string" },
                title: { type: "string" },
                summary: { type: "string" },
                mainlineTitle: { type: ["string", "null"] },
                mainlineBody: { type: ["string", "null"] },
                summaryStatus: {
                  type: ["string", "null"],
                  description: "只有 generated 时 mainline* 才是 AI 真写出来的，其余取值下为空，不要渲染。",
                },
                categoryNotes: {
                  type: "array",
                  items: {
                    type: "object",
                    properties: {
                      category: { type: "string" },
                      label: { type: "string" },
                      note: { type: "string" },
                    },
                  },
                },
                itemCount: { type: "integer" },
                sections: {
                  type: "array",
                  items: {
                    type: "object",
                    properties: {
                      focus: { type: "string" },
                      label: { type: "string" },
                      items: { type: "array", items: { $ref: "#/components/schemas/Item" } },
                    },
                  },
                },
                items: { type: "array", items: { $ref: "#/components/schemas/Item" } },
                updatedAt: { type: ["string", "null"], format: "date-time" },
                links: { type: "object", properties: { radar: { type: "string", format: "uri" } } },
              },
            },
          },
        },
        PeriodIndex: {
          type: "object",
          required: ["schemaVersion", "page", "items"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            page: { $ref: "#/components/schemas/Page" },
            items: {
              type: "array",
              items: {
                type: "object",
                required: ["key", "rangeStart", "rangeEnd", "title", "itemCount", "links"],
                properties: {
                  key: { type: "string" },
                  rangeStart: { type: "string", format: "date" },
                  rangeEnd: { type: "string", format: "date" },
                  title: { type: "string" },
                  itemCount: { type: "integer" },
                  links: { type: "object", properties: { radar: { type: "string", format: "uri" }, api: { type: "string", format: "uri" } } },
                },
              },
            },
          },
        },
        PeriodResponse: {
          type: "object",
          required: ["schemaVersion", "report"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            report: {
              type: "object",
              required: ["mode", "key", "rangeStart", "rangeEnd", "themeNotes", "stats", "reportDates", "itemCount", "items", "links"],
              properties: {
                mode: { type: "string", enum: ["weekly", "monthly"] },
                key: { type: "string" },
                rangeStart: { type: "string", format: "date" },
                rangeEnd: { type: "string", format: "date" },
                mainlineTitle: { type: ["string", "null"] },
                mainlineBody: { type: ["string", "null"] },
                summaryStatus: { type: ["string", "null"] },
                finalizedAt: { type: ["string", "null"], format: "date-time", description: "非空表示已封版；为空表示当前周期仍会更新。" },
                themeNotes: {
                  type: "array",
                  items: {
                    type: "object",
                    required: ["label", "note", "category", "eventIds"],
                    properties: {
                      label: { type: "string" },
                      note: { type: "string" },
                      category: { type: ["string", "null"] },
                      eventIds: { type: "array", items: { type: "string" } },
                    },
                  },
                },
                stats: {
                  type: "object",
                  properties: {
                    sourceCoverageCount: { type: ["integer", "null"] },
                    multiSourceRatio: { type: ["number", "null"] },
                    categoryDistribution: { type: "object", additionalProperties: { type: "integer" } },
                    selectedCount: { type: ["integer", "null"] },
                    coverageCount: { type: ["integer", "null"] },
                  },
                },
                reportDates: { type: "array", items: { type: "string", format: "date" } },
                itemCount: { type: "integer" },
                items: { type: "array", items: { $ref: "#/components/schemas/Item" } },
                updatedAt: { type: ["string", "null"], format: "date-time" },
                links: { type: "object", properties: { radar: { type: "string", format: "uri" } } },
              },
            },
          },
        },
        Topic: {
          type: "object",
          required: ["id", "name", "count", "weekCount", "prevWeekCount", "links"],
          properties: {
            id: { type: "string" },
            name: { type: "string" },
            description: { type: "string" },
            count: { type: "integer", description: "windowDays 窗口内的条数。" },
            weekCount: { type: "integer", description: "今天往前 6 天。" },
            prevWeekCount: { type: "integer", description: "今天-7 到 今天-13。" },
            latestPublishedAt: { type: ["string", "null"] },
            links: { type: "object", properties: { radar: { type: "string", format: "uri" } } },
          },
        },
        TopicList: {
          type: "object",
          required: ["schemaVersion", "windowDays", "storylineWindowDays", "itemCount", "groups", "storylines"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            windowDays: { type: "integer" },
            storylineWindowDays: { type: "integer" },
            itemCount: { type: "integer" },
            groups: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  id: { type: "string" },
                  name: { type: "string" },
                  description: { type: "string" },
                  topics: { type: "array", items: { $ref: "#/components/schemas/Topic" } },
                },
              },
            },
            storylines: {
              type: "array",
              description: "本周雷达：近 storylineWindowDays 天仍在更新的多日多源事件。",
              items: {
                type: "object",
                properties: {
                  id: { type: "string" },
                  title: { type: "string" },
                  sourceCount: { type: "integer" },
                  days: { type: "integer", description: "报道跨越的自然日数（上海时区），≥2 才算故事线。" },
                  lastSeenAt: { type: ["string", "null"] },
                  links: { type: "object", properties: { radar: { type: "string", format: "uri" } } },
                },
              },
            },
          },
        },
        TopicDetail: {
          type: "object",
          required: ["schemaVersion", "topic", "windowDays", "focusWindowDays", "totalCount", "selectedCount", "focus", "page", "items"],
          properties: {
            schemaVersion: { type: "integer", const: 1 },
            topic: {
              type: "object",
              properties: {
                id: { type: "string" },
                name: { type: "string" },
                description: { type: "string" },
                groupId: { type: ["string", "null"] },
                groupName: { type: ["string", "null"] },
                links: { type: "object", properties: { radar: { type: "string", format: "uri" } } },
              },
            },
            windowDays: { type: "integer" },
            focusWindowDays: { type: "integer" },
            totalCount: { type: "integer", description: "含未精选。" },
            selectedCount: { type: "integer", description: "只算精选。" },
            latestPublishedAt: { type: ["string", "null"] },
            focus: {
              type: "array",
              items: { $ref: "#/components/schemas/Item" },
              description: "近 focusWindowDays 天的重点条目，与 items 会重叠，按 id 去重后再用。",
            },
            page: { $ref: "#/components/schemas/Page" },
            items: { type: "array", items: { $ref: "#/components/schemas/Item" } },
          },
        },
      },
    },
  };
}
