---
name: ai-radar
description: 查询 AI·RADAR 的中文 AI 情报——过去 24 小时或最近 7 天的精选动态、当前热点榜、单个事件的报道时间线、每日精编日报，以及主题档案与"正在变热"的话题。当用户问"最近有什么 AI 新闻""过去 24 小时 AI 圈发生了什么""现在最热的 AI 事件是什么""给我今天的 AI 日报""某公司或某模型最近有什么动静""最近哪些 AI 话题在升温"时使用。
---

# AI·RADAR 情报查询

AI·RADAR 持续监听数十个高信噪比 AI 信源，用 AI 评分、聚类、去重，每天沉淀一期精编日报。
本 Skill 通过匿名只读的 HTTP API 读取它，**不需要 API Key，也不读取任何登录态**。

基址：`https://radar.suversal.com`

## 怎么选端点

| 用户在问什么 | 用哪个 |
|---|---|
| 最近有什么 AI 新闻 / 过去 24 小时发生了什么 | `/api/v1/items?window=24h` |
| 最近一周值得关注的 | `/api/v1/items?window=7d` |
| 现在最热的事件是什么 | `/api/v1/hot-topics` |
| 某公司、模型、产品、人物的近期消息 | `/api/v1/items?q=关键词` |
| 这件事的来龙去脉 / 有哪几家报道了 | `/api/v1/stories/{id}` |
| 今天的 AI 日报 / 某天的日报 | `/api/v1/dailies/latest`、`/api/v1/dailies/{YYYY-MM-DD}` |
| 什么话题正在变热 / 有哪些主题 | `/api/v1/topics` |

## 常用调用

```bash
# 过去 24 小时精选，取 10 条
curl -s 'https://radar.suversal.com/api/v1/items?window=24h&limit=10'

# 最近 7 天里和 Claude 有关的（q 支持中英文，2–200 字）
curl -s 'https://radar.suversal.com/api/v1/items?mode=all&window=7d&q=Claude&limit=10'

# 当前热点榜（按多信源热度排序，不是按时间）
curl -s 'https://radar.suversal.com/api/v1/hot-topics?limit=5'

# 某个事件的报道时间线。id 来自上面返回的 items[].id
curl -s 'https://radar.suversal.com/api/v1/stories/e19143f02e051'

# 最新一期日报
curl -s 'https://radar.suversal.com/api/v1/dailies/latest'

# 主题档案 + 本周雷达
curl -s 'https://radar.suversal.com/api/v1/topics'
```

## 参数

`/api/v1/items`

| 参数 | 默认 | 取值 |
|---|---|---|
| `mode` | `selected` | `selected` 精选（推荐）｜`all` 同窗口全部收录 |
| `window` | `7d` | `24h` ｜ `7d`（**只有这两个**） |
| `limit` | `50` | 1–100 |
| `offset` | `0` | 0–10000 |
| `category` | — | `model` `product` `industry` `research` `tutorial` |
| `focus` | — | `model` `product` `technology` `industry` `tutorial` |
| `q` | — | 关键词，2–200 字 |

`/api/v1/hot-topics`：`hours` 1–168（默认 48）、`limit` 1–20（默认 10）。

结果恒定按 `publishedAt` 倒序。分页看 `page.hasMore` 与 `page.total`。

## 回答用户时

- **时间窗要说出来**。"过去 24 小时"和"最近 7 天"是不同的答案，别含糊成"最近"。
- **链接给站内阅读页**（`links.radar`），第三方原文（`links.original`）作为补充。
- **`timeBasis` 决定措辞**。它标注的是时间的*性质*，不是时间本身——`publishedAt` 每条都有值。`published` 可以说"发布于"；`discovered` 必须说"收录于"，不得写成发布时间；`null` 是没有逐条标注，站内绝大多数条目是这种，实践中基本都是原文发布时间。**对 null 的条目直接报时间即可**，不用逐条声明存疑，也不要主动写成"发布于"。
- **窗口内没有结果时如实说**。"过去 24 小时只有 3 条"是有效答案，不要偷偷放宽到 7 天来凑数。
- **摘要是线索不是原文**。`summary` 和 `title` 由 AI 基于第三方报道生成。引用具体数字、政策条款或当事人原话前，打开 `links.original` 核对。

## 做不到的事

- **超过 7 天的历史检索不支持**。原生窗口只有 `24h` 和 `7d`。查不到不代表没发生过。
- **没有正文**。API 返回摘要、推荐理由和链接，不返回第三方原文正文。要正文请让用户打开链接。
- **周报和月报只有网页**，目前没有 API。别拿"最近 7 天精选"冒充编辑成品周报，那是两回事。
- **没有推送通道**。没有 SSE、Webhook 或流式订阅。要跟进变化就按下面的节奏轮询。

## 错误与频率

错误是 RFC 9457 Problem JSON，按 `code` 分支，不要解析 `detail` 文案：

- `400` `invalid_parameter` / `unknown_parameter` / `duplicate_parameter`——参数不对。**接口不会自动改成边界值**，`limit=500` 是报错不是给 100。按报错改正，不要退化成更宽的查询。
- `404` `not_found`——事件 ID 或日期不存在。事件 ID 只能来自其它端点的返回，不要自己构造。
- `500` `internal_error`——服务端自己的问题，**重试不会改善**，别按 503 那样反复重试。把 `requestId` 提交到反馈页。
- `503` `upstream_unavailable`——数据源暂时不可用，退避后重试，不要并发重试。

反馈时附上响应头里的 `X-Request-Id` 即可定位。

轮询请用 `If-None-Match` 条件请求，间隔取响应头 `Cache-Control` 里的 `s-maxage`（items 60 秒、hot-topics 300 秒）。更密只会拿到同一份共享缓存副本。

## 授权边界

个人非商业、公益非商业、组织内部使用免费。面向外部的商业产品、收费服务、客户交付、代理接口、数据转售、公开镜像或批量再分发，须先取得书面授权——匿名可访问不等于授权。
