# HotAI 日报、周报、月报统一出版系统需求说明书

文档版本：1.0  
编写日期：2026-07-11  
产品：Suversal AI Radar / AI·RADAR  
状态：待产品评审  

## 1. 文档目的

本文定义 HotAI 日报、周报和月报的统一产品语义、业务流程、数据模型、接口、页面行为、修订规则、迁移方案和验收标准。

本文是后续技术实现计划的需求依据。除非形成新版本需求文档，实施者不得自行改变本文锁定的出版、版本和历史保留规则。

## 2. 背景与现状

当前系统已经具备：

- 每日文章采集、AI 评分和事件聚类；
- 日报、周报、月报页面；
- `daily_reports`、`daily_report_entries` 和 `period_reports`；
- 日报 JSON/Markdown 输出；
- 周期报告 AI 主线综述；
- 管理后台隐藏和内容修正；
- 日报、周报、月报归档入口。

当前报告结构同时存在两种冲突语义：

1. `daily_reports.sections` 和 `markdown` 保存生成时的内容快照；
2. `daily_report_entries` 只保存名单和部分字段，页面读取时解析事件的当前内容。

这会导致历史日报随 AI 重算、主文章替换、翻译更新或人工编辑而变化，无法准确还原“当时发布了什么”。周报和月报也缺少对具体日报版本的输入血缘。

## 3. 产品目标

### 3.1 核心目标

1. 日报、周报、月报采用同一个出版模型和生命周期。
2. 每份正式发布报告都能完整还原发布时内容。
3. 同一期报告支持草稿、正式发布、修订版、撤回和历史版本查看。
4. 周报和月报能准确记录使用了哪些日报版本。
5. 报告中的事件链接可以跳转到事件的当前详情，但历史报告正文保持不变。
6. 安全、合规或严重错误内容可以实时从所有公开报告中隐藏。
7. Markdown 导出内容与页面展示的正式版本一致。
8. 现有公开 URL 和主要 API 在迁移期间保持兼容。

### 3.2 成功标准

- 任意已发布报告均能按 `issue_key + version` 还原。
- 重跑 AI pipeline 不会改变已发布报告版本。
- 主文章切换不会改变旧报告快照。
- 普通编辑产生新版本，不覆盖旧版本。
- 隐藏操作在所有公开页面即时生效，但审计后台仍可看到历史记录。
- 周报/月报能够列出其引用的每一份日报版本。
- 日报目标条目数为 8–12 个不同事件；聚类去重后不足时继续补位。
- 自动生成、发布、修订、撤回和回滚均有测试与运行记录。

## 4. 非目标

本期不包含：

- 多租户报告；
- 用户自定义报告模板；
- 用户自定义时区；
- PDF、邮件、Telegram 等外部分发渠道；
- 多语言报告正文；
- 报告付费、权限分层或订阅系统；
- 自动生成图表图片；
- 多人实时协同编辑器。

系统仍可继续生成 JSON 和 Markdown。PDF、邮件和推送将在统一出版模型稳定后另行设计。

## 5. 用户角色

### 5.1 公开读者

可以：

- 查看当前已发布日报、周报和月报；
- 查看归档期号；
- 在允许公开历史版本时查看指定版本；
- 复制正式 Markdown；
- 从报告条目进入当前事件详情；
- 看到报告完整性或修订状态。

不能：

- 查看草稿；
- 查看已隐藏条目的原始内容；
- 发布、撤回或重新生成报告。

### 5.2 管理员

可以：

- 查看所有期号及版本；
- 生成或重新生成草稿；
- 发布草稿；
- 基于已发布版本创建修订版；
- 撤回当前发布版本；
- 查看缺失输入和生成错误；
- 隐藏事件或独立文章；
- 查看版本输入血缘和生成运行。

V1 仍使用现有单管理员 Token 鉴权。

## 6. 核心术语

| 术语 | 定义 |
|---|---|
| Issue / 期号 | 某一自然日期、自然周或自然月对应的报告身份 |
| Edition / 版本 | 某一期报告的一次具体生成或修订结果 |
| Published Edition | 当前对公开读者生效的正式版本 |
| Section / 栏目 | 某个版本中的有序内容分组 |
| Entry / 条目 | 报告中一个事件或独立文章的发布快照 |
| Input / 输入版本 | 周报或月报生成时引用的具体日报版本 |
| Snapshot / 快照 | 发布时冻结的标题、摘要、分类、标签和推荐语等字段 |
| Live Governance / 实时治理 | 隐藏、撤回等必须即时影响公开展示的管理操作 |

## 7. 锁定的产品原则

### 7.1 报告是出版物

已发布版本不得原地修改。任何普通内容修订必须创建更高版本号的新 edition。

### 7.2 历史内容冻结，治理状态实时

- 标题、摘要、推荐理由、分类、标签、分数和来源信息按版本冻结；
- `hidden`、`withdrawn` 等安全或合规状态实时生效；
- 被隐藏条目不在公开报告正文中展示；
- 管理后台仍保留原始快照和隐藏原因。

### 7.3 日报是周期报告的基础事实

- 周报固定引用该周已发布日报的具体 edition；
- 月报固定引用该月已发布日报的具体 edition；
- 周报可作为月报 AI 总结的辅助上下文，但不得作为月报统计的唯一事实源。

### 7.4 报告链接与报告内容分离

- 报告条目正文使用发布快照；
- 条目链接跳转到事件当前详情；
- 事件合并后通过 alias 重定向到 canonical event；
- 旧报告快照不因事件合并而改写。

### 7.5 上海时区是唯一划期标准

所有日、周、月边界使用 `Asia/Shanghai`：

- 日报：00:00:00–23:59:59；
- 周报：周一 00:00:00–周日 23:59:59；
- 月报：自然月第一日 00:00:00–最后一日 23:59:59。

数据库时间戳仍使用 UTC 存储，显示和期号计算使用上海时区。

## 8. 报告类型定义

### 8.1 日报

日报回答：今天发生了哪些最值得关注的独立 AI 事件？

内容要求：

- 8–12 个不同事件；
- 按事件去重，不按文章计数；
- 每个事件包含标题、摘要、为什么重要、下一步、分类、标签、分数和主要来源；
- 按模型、产品、行业、论文、技巧等展示分类组织；
- 包含今日总览、条目数、来源覆盖和生成时间；
- 支持复制正式 Markdown。

选取流程：

```text
处理全部候选文章
→ 全部候选事件聚类
→ 事件级评分与主文章选择
→ 按事件排序
→ 选择 8–12 个不同事件
→ 生成日报草稿
```

不得先固定 top N 文章后再聚类。聚类导致条目数减少时，必须从后续事件候选补足。

### 8.2 周报

周报回答：过去一周最重要的主线、趋势和事件是什么？

固定周期：周一至周日。`issue_key` 使用 ISO 周格式，例如 `2026-W28`。

内容要求：

- 本周总体主线；
- 3–5 个趋势主题；
- 跨日报去重后的重点事件；
- 每个事件在周报中最多出现一次；
- 本周数据概览；
- 下周关注点；
- 完整性状态和缺失日期。

数据概览至少包含：

- 输入日报数量；
- 处理文章数量；
- 独立事件数量；
- 精选事件数量；
- 来源覆盖数；
- 多来源事件比例；
- 分类分布。

### 8.3 月报

月报回答：过去一个自然月发生了哪些结构性变化？

`issue_key` 使用 `YYYY-MM`，例如 `2026-07`。

内容要求：

- 月度总体结论；
- 3–8 个结构性趋势主题；
- 每个主题 3–5 个代表事件；
- 模型、Agent/产品、开源生态、产业/公司、研究等维度变化；
- 月度数据概览；
- 下月值得持续跟踪的问题；
- 完整性状态和缺失日期。

月报不是周报拼接。AI 必须基于整月去重事件和全部日报输入重新总结。

## 9. 报告生命周期

### 9.1 Edition 状态

```text
draft → published → superseded
  │          │
  └──────────┴→ withdrawn
```

状态定义：

| 状态 | 含义 |
|---|---|
| `draft` | 已生成但未公开，可在发布前被同版本重新生成 |
| `published` | 当前或历史正式发布版本，内容不可修改 |
| `superseded` | 已被更高版本替代，仍可审计和查看 |
| `withdrawn` | 已撤回，不作为当前公开版本 |

### 9.2 状态规则

1. 一个 issue 同时最多有一个 `published` 当前版本。
2. 发布新版本时，原 published 版本原子地变为 superseded。
3. published 和 superseded 版本的快照字段不得更新。
4. draft 可以删除或重新生成，但每次正式发布必须有唯一 version。
5. withdrawn 版本不能自动恢复为 published；恢复需要创建新 edition。
6. Issue 的 `current_published_edition_id` 必须指向属于本 issue 的 published edition。

### 9.3 版本号

- 每个 issue 从 version 1 开始；
- 版本号严格递增；
- 删除草稿不会复用已分配版本号；
- API 和后台都以整数版本展示。

## 10. 数据完整性和缺失输入

### 10.1 完整性状态

每个 edition 必须保存：

```text
completeness_status = complete | partial
expected_input_count
actual_input_count
missing_issue_keys
```

### 10.2 日报完整性

日报不依赖其他报告输入。只要本日 pipeline 成功并产生至少一个可发布事件，即可生成 complete 草稿。

如果没有可发布事件：

- 生成 empty draft；
- 不自动发布；
- 管理后台显示“无可发布事件”；
- API 在没有 published edition 时返回明确空状态，不回退到其他日期。

### 10.3 周报和月报完整性

- 所有预期日报均存在 published edition：`complete`；
- 任一预期日报缺失：`partial`；
- partial edition 可以生成草稿；
- partial edition 默认不自动发布；
- 管理员可以显式发布 partial edition，页面必须显示缺失日期；
- 缺失日报补齐后生成新 edition，不修改已发布 partial edition。

## 11. 数据模型需求

### 11.1 `report_issues`

职责：保存报告期号身份和当前正式版本指针。

| 字段 | 类型 | 要求 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `kind` | TEXT | `daily/weekly/monthly` |
| `issue_key` | TEXT | 日期、ISO 周或月份键 |
| `period_start` | DATE | 必填 |
| `period_end` | DATE | 必填 |
| `timezone` | TEXT | 固定 `Asia/Shanghai` |
| `status` | TEXT | `active/archived` |
| `current_published_edition_id` | BIGINT NULL | 当前公开版本 |
| `created_at` | TIMESTAMPTZ | 必填 |
| `updated_at` | TIMESTAMPTZ | 必填 |

约束：

- `UNIQUE(kind, issue_key)`；
- `CHECK(kind IN ('daily','weekly','monthly'))`；
- `CHECK(period_start <= period_end)`；
- 当前 edition 必须属于本 issue。

### 11.2 `report_editions`

职责：保存具体出版版本。

| 字段 | 类型 | 要求 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `report_issue_id` | BIGINT | 外键 |
| `version` | INTEGER | 从 1 递增 |
| `status` | TEXT | edition 状态 |
| `title` | TEXT | 必填 |
| `summary` | TEXT | 必填 |
| `mainline_title` | TEXT | 周/月报使用，日报可空 |
| `mainline_body` | TEXT | 周/月报使用，日报可空 |
| `theme_notes` | JSONB | 主题观察快照 |
| `rendered_markdown` | TEXT | 正式 Markdown 快照 |
| `pipeline_run_id` | BIGINT NULL | 生成运行血缘 |
| `idempotency_key` | TEXT | 同一期内的生成幂等键 |
| `content_schema_version` | INTEGER | 初始为 1 |
| `completeness_status` | TEXT | `complete/partial` |
| `expected_input_count` | INTEGER | 非负 |
| `actual_input_count` | INTEGER | 非负 |
| `missing_issue_keys` | JSONB | 字符串数组 |
| `generated_at` | TIMESTAMPTZ | 必填 |
| `published_at` | TIMESTAMPTZ NULL | 发布后必填 |
| `superseded_at` | TIMESTAMPTZ NULL | 被替代后填写 |
| `created_at` | TIMESTAMPTZ | 必填 |

约束：

- `UNIQUE(report_issue_id, version)`；
- `UNIQUE(report_issue_id, idempotency_key)`；
- edition 状态 CHECK；
- published 状态必须有 `published_at`；
- `actual_input_count <= expected_input_count`；
- `content_schema_version >= 1`。

### 11.3 `report_sections`

职责：保存版本内有序栏目。

| 字段 | 类型 | 要求 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `report_edition_id` | BIGINT | 外键，级联删除 draft |
| `section_key` | TEXT | 版本内稳定键 |
| `position` | INTEGER | 从 0 开始 |
| `title` | TEXT | 必填 |
| `summary` | TEXT | 可空 |

约束：

- `UNIQUE(report_edition_id, position)`；
- `UNIQUE(report_edition_id, section_key)`。

### 11.4 `report_entries`

职责：保存正式条目快照和当前事件跳转关系。

| 字段 | 类型 | 要求 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `report_edition_id` | BIGINT | 外键 |
| `report_section_id` | BIGINT | 外键 |
| `position` | INTEGER | 栏目内位置 |
| `event_cluster_id` | TEXT NULL | 当前事件关联 |
| `raw_article_id` | TEXT | 发布时主文章 |
| `title_snapshot` | TEXT | 必填 |
| `one_line_summary_snapshot` | TEXT | 必填 |
| `summary_snapshot` | TEXT | 必填 |
| `reason_snapshot` | TEXT | 必填 |
| `action_snapshot` | TEXT | 必填 |
| `category_snapshot` | TEXT | 必填 |
| `tags_snapshot` | JSONB | 字符串数组 |
| `score_at_selection` | DOUBLE PRECISION | 必填 |
| `source_count_snapshot` | INTEGER | 至少 1 |
| `main_source_snapshot` | JSONB | name/url/tier |
| `published_at_snapshot` | TIMESTAMPTZ | 原事件发布时间 |
| `snapshot_schema_version` | INTEGER | 初始为 1 |
| `created_at` | TIMESTAMPTZ | 必填 |

约束：

- `UNIQUE(report_edition_id, report_section_id, position)`；
- 同 edition 内同一 canonical event 最多出现一次；
- `raw_article_id` 必须存在；
- `event_cluster_id` 为空时表示独立文章，不使用 `a...` 伪外键；
- `source_count_snapshot >= 1`。

### 11.5 `report_edition_inputs`

职责：保存周报/月报的日报版本血缘。

| 字段 | 类型 | 要求 |
|---|---|---|
| `report_edition_id` | BIGINT | 输出版本 |
| `input_edition_id` | BIGINT | 输入日报版本 |
| `position` | INTEGER | 按日期排序 |

约束：

- 组合主键 `(report_edition_id, input_edition_id)`；
- `UNIQUE(report_edition_id, position)`；
- 输入 edition 必须属于 daily issue；
- 输出和输入不能相同；
- 输入必须是 published 或 superseded 的正式版本，不能引用 draft。

## 12. 生成流程

### 12.1 日报生成

1. 确认当日 pipeline run 成功。
2. 查询当日所有可展示的 processed articles。
3. 完成全部候选事件归并。
4. 应用文章和事件级隐藏治理。
5. 按事件计算最终排序。
6. 选取 8–12 个不同事件。
7. 生成标题、总览和栏目。
8. 将最终展示字段写入 entry snapshot。
9. 生成与 snapshot 完全一致的 Markdown。
10. 创建 draft edition。
11. 自动发布开关关闭时等待管理员；开启时发布 complete draft。

幂等要求：同一次生成请求重试不得创建重复 edition。自动生成使用 `pipeline:{pipeline_run_id}` 作为 `idempotency_key`；管理员手工生成使用客户端提交的 UUID，服务端保存为 `admin:{uuid}`。同一 issue 内重复提交相同 key 时返回已经存在的 edition，不创建新版本。

### 12.2 周报生成

1. 计算目标 ISO 周的 7 个日报 issue key。
2. 对每个日期选择当时 current published edition。
3. 固定这些 edition 为本周报版本输入。
4. 合并所有输入条目并按 canonical event 去重。
5. 汇总事件跨日持续时间、最高分和来源数。
6. 生成周主线、趋势主题和下周关注点。
7. 创建 sections 和 entries 快照。
8. 生成 Markdown。
9. 根据输入完整性创建 complete 或 partial draft。

### 12.3 月报生成

1. 计算自然月全部日报 issue key。
2. 固定每个日期的 current published edition。
3. 跨整月合并并按 canonical event 去重。
4. 计算月度趋势、分类变化和多来源事件指标。
5. 可将周报主线作为 AI 辅助上下文，但统计数据只来自日报 inputs。
6. 生成月度结论、主题、代表事件和下月问题。
7. 创建 sections、entries 和 Markdown 快照。
8. 根据输入完整性创建 complete 或 partial draft。

## 13. 修订、隐藏与撤回

### 13.1 普通修订

适用：标题、摘要、分类、标签、推荐理由或栏目顺序调整。

流程：

1. 基于当前 published edition 创建新 draft；
2. 复制原 sections 和 entries 快照；
3. 应用修订；
4. 发布新版本；
5. 旧版本标记 superseded。

不得直接更新旧版本快照。

### 13.2 实时隐藏

适用：严重错误、来源撤稿、安全、版权或合规问题。

规则：

- 写入现有事件或文章治理表；
-所有公开报告读取时检查 hidden；
-默认直接跳过隐藏条目；
-报告页面显示的 `article_count` 以实际可见条目数为准；
-管理后台仍显示原始快照和隐藏状态；
-取消隐藏后，历史报告可以恢复展示其原快照。

### 13.3 报告撤回

- 管理员可撤回当前 published edition；
-撤回后 issue 没有公开版本，除非存在另一个明确恢复发布的新 edition；
-公开 API 返回 `report_withdrawn`，不自动回退到旧版本；
-管理员可以基于撤回版本创建修订版。

## 14. 公共 API 需求

### 14.1 当前版本接口

保留：

```text
GET /api/public/daily/{date}
GET /api/public/reports/weekly/{issue_key}
GET /api/public/reports/monthly/{issue_key}
```

默认返回 current published edition。

统一响应至少包含：

```json
{
  "kind": "daily",
  "issue_key": "2026-07-11",
  "version": 2,
  "status": "published",
  "period_start": "2026-07-11",
  "period_end": "2026-07-11",
  "timezone": "Asia/Shanghai",
  "title": "...",
  "summary": "...",
  "mainline_title": null,
  "mainline_body": null,
  "generated_at": "...",
  "published_at": "...",
  "content_schema_version": 1,
  "completeness": {
    "status": "complete",
    "expected_inputs": 1,
    "actual_inputs": 1,
    "missing_issue_keys": []
  },
  "sections": [],
  "items": []
}
```

### 14.2 指定版本接口

```text
GET /api/public/reports/{kind}/{issue_key}/versions/{version}
```

只允许读取 published、superseded 版本。draft 和 withdrawn 版本不得公开读取。

### 14.3 归档接口

```text
GET /api/public/reports/daily/archive
GET /api/public/reports/weekly/archive
GET /api/public/reports/monthly/archive
```

每个归档项包含：

- `issue_key`；
-周期范围；
-当前版本号；
-当前状态；
-标题；
-发布时间；
-完整性状态；
-条目数。

### 14.4 Markdown 接口

```text
GET /api/public/reports/{kind}/{issue_key}/markdown
GET /api/public/reports/{kind}/{issue_key}/versions/{version}/markdown
```

返回数据库中该 edition 的 `rendered_markdown`，不得根据当前事件重新生成。

## 15. 管理 API 需求

所有接口沿用现有管理员鉴权。

```text
GET  /api/admin/reports
GET  /api/admin/reports/{kind}/{issue_key}
GET  /api/admin/reports/{kind}/{issue_key}/editions
POST /api/admin/reports/{kind}/{issue_key}/generate
POST /api/admin/report-editions/{edition_id}/publish
POST /api/admin/report-editions/{edition_id}/withdraw
POST /api/admin/report-editions/{edition_id}/clone-as-revision
PATCH /api/admin/report-editions/{edition_id}
```

规则：

- PATCH 只允许 draft；
-发布、撤回和修订必须记录管理员操作日志；
-并发发布必须使用事务和行锁，防止同 issue 出现两个当前 published edition；
-生成接口接受幂等键；
-partial edition 发布需要显式 `allow_partial=true`。

## 16. 页面需求

### 16.1 日报页面

页面显示：

- 期号和版本；
-修订标记；
-生成和发布时间；
-完整性状态；
-今日看点；
-分类栏目；
-条目快照；
-复制 Markdown；
-前一天/后一天；
-历史版本入口。

### 16.2 周报页面

页面显示：

- ISO 周号和日期范围；
-周主线；
-主题趋势；
-重点事件；
-统计概览；
-下周关注；
-引用日报列表；
-缺失输入警告；
-历史版本入口。

### 16.3 月报页面

页面显示：

-月份和版本；
-月度结论；
-趋势主题；
-代表事件；
-月度统计；
-下月关注；
-输入完整性；
-历史版本入口。

### 16.4 管理后台

增加统一报告管理页：

- 按 daily/weekly/monthly 筛选；
-查看期号、版本、状态和完整性；
-生成草稿；
-预览草稿；
-发布；
-撤回；
-创建修订版；
-查看输入血缘；
-查看 pipeline run；
-查看历史版本 diff。

## 17. 错误处理

| 场景 | 行为 |
|---|---|
| 期号不存在 | 404 `report_issue_not_found` |
| 期号存在但无已发布版本 | 404 `report_not_published` |
| 当前版本已撤回 | 410 `report_withdrawn` |
| 请求不存在版本 | 404 `report_edition_not_found` |
| 请求 draft 公开版本 | 404，不暴露其存在性 |
| 周/月报输入缺失 | 生成 partial draft，不自动发布 |
| AI 主线生成失败 | 保留确定性 fallback，并记录生成错误 |
| Markdown 生成失败 | edition 保持 draft，不允许发布 |
| 并发发布冲突 | 409 `report_publish_conflict` |
| 隐藏后报告无可见条目 | 返回空 items，并保留报告元数据 |

不得在指定日期报告不存在时回退到最新报告。

## 18. 可观测性和审计

每次生成和发布至少记录：

- issue 和 edition ID；
-触发来源：scheduler/admin/CLI；
-pipeline run ID；
-输入日报版本；
-输入事件数；
-输出条目数；
-AI provider、模型和 Prompt 版本；
-生成耗时；
-生成错误；
-发布管理员；
-发布时间；
-撤回或修订原因。

日志不得包含 API Key、管理员 Token 或完整私密请求头。

## 19. 性能要求

- 当前报告 API 的数据库查询目标：P95 小于 300 ms，不含网络代理图片；
-归档接口 P95 小于 200 ms；
-日报最多返回 12 条正式条目；
-周报建议不超过 30 条代表事件；
-月报建议不超过 50 条代表事件；
-报告正文读取不得在请求时调用 AI；
-Markdown 直接读取 edition 快照，不在请求时重建；
-报告读取应避免逐条 N+1 查询；
-周报/月报生成可以异步执行，不受普通 HTTP 请求超时限制。

## 20. 安全要求

- 草稿、撤回版本和审计信息只能由管理员访问；
-所有管理写接口执行现有 Token 鉴权；
-管理员 Token 不写入数据库报告内容；
-报告 Markdown 和摘要渲染必须经过现有 HTML/Markdown 清理；
-外部链接继续使用 URL 安全校验；
-隐藏内容不能通过公开指定版本接口绕过；
-事件详情被隐藏时，报告条目链接不得泄露正文。

## 21. 迁移需求

### 21.1 新旧系统并行

1. 通过 Alembic 创建统一报告新表。
2. 保留 `daily_reports`、`daily_report_entries` 和 `period_reports`。
3. 新生成报告短期双写旧表和新表。
4. 旧 API 继续读取旧表，新增内部对比读取新表。
5. 对比新旧返回结果，确认条目、顺序、Markdown 和隐藏行为。
6. 切换公共 API 到新表。
7. 停止旧表写入。
8. 稳定观察后再删除旧表或旧字段。

### 21.2 历史数据回填

日报：

- 每个 `daily_reports.report_date` 创建一个 daily issue；
- 使用 `daily_reports.sections` 的历史 JSON 作为 edition v1 的快照来源；
-使用 `daily_reports.markdown` 作为 v1 Markdown；
-如果 JSON 和 entries 不一致，以 JSON 快照为历史事实；
-标记 `migration_source=legacy_daily_snapshot`。

周报/月报：

- 每个 `period_reports(kind, period_key)` 创建 issue 和 edition v1；
-保存现有主线、主题和日期范围；
-根据 `report_dates` 尽可能解析输入日报版本；
-无法精确确定输入版本时标记 `legacy_input_unverified`；
-不得伪造不存在的输入血缘。

### 21.3 回滚

- 公共 API 切换前保留旧表完整数据；
-使用功能开关选择旧读取或新读取；
-迁移失败必须事务回滚；
-双写失败时记录运行错误，不发布新 edition；
-切换后出现严重问题可恢复旧读取，但不得删除已创建的新版本数据。

## 22. 兼容性要求

- `/daily`、`/daily/{date}`、`/weekly`、`/weekly/{key}`、`/monthly`、`/monthly/{key}` URL 保持不变；
-现有 API 字段在迁移期保留；
-新增字段必须向后兼容；
-现有前端可先忽略 version 和 completeness；
-旧 JSON 文件仅作为导出或紧急回退，不再作为生产数据库的并行事实源；
-事件 ID alias 必须支持旧报告链接跳转。

## 23. 验收标准

### 23.1 数据模型

- 空数据库可通过 `alembic upgrade head` 创建全部报告表；
-所有唯一约束、外键和 CHECK 生效；
-同 issue 无法同时存在两个 current published edition；
-同 edition 无法重复写入同一事件；
-周/月报 input 无法引用 draft edition。

### 23.2 日报

- 可生成包含 8–12 个不同事件的草稿；
-多个文章合并后能自动补足事件数量；
-发布后重跑 pipeline 不改变原版本；
-创建修订版后旧版仍可读取；
-复制 Markdown 与页面快照一致；
-隐藏事件后所有公开版本立即不可见；
-取消隐藏后恢复原快照，而不是当前 AI 文本。

### 23.3 周报

- 正确引用目标周 7 个日报 edition；
-同一事件跨多天只出现一次；
-缺失日报生成 partial draft；
-partial draft 不自动发布；
-补齐日报后产生新 edition；
-旧周报内容保持不变。

### 23.4 月报

- 正确引用自然月已发布日报；
-事件跨周去重；
-月报统计只基于日报输入；
-周报仅作为辅助上下文，不改变事实统计；
-输入缺失和修订行为符合完整性规则。

### 23.5 API 与页面

- 当前版本、指定版本和归档接口返回正确；
-不存在报告不回退其他日期；
-撤回报告返回 410；
-公开接口不可读取 draft；
-日报、周报、月报页面展示版本和完整性；
-管理后台可以生成、发布、修订、撤回和查看输入血缘。

### 23.6 回归验证

- Python 全量测试通过；
-TypeScript 检查通过；
-Next.js 生产构建通过；
-数据库 migration scratch 测试通过；
-API smoke 测试通过；
-桌面和移动端报告页面人工验收通过；
-旧 API 合同测试在兼容期内继续通过。

## 24. 实施边界与默认决策

以下决策在本文中已经锁定：

1. 报告是版本化出版物，不是纯实时视图。
2. 普通内容修改创建新 edition。
3. 隐藏治理实时生效。
4. 周报和月报固定引用具体日报 edition。
5. 上海时区是唯一划期标准。
6. 月报事实统计直接来源于日报，不依赖周报汇总。
7. Markdown 是 edition 的正式快照产物。
8. 不再使用 `a...` 字符串伪外键表达独立文章。
9. 旧系统通过双写、对比、切换、停写的方式渐进迁移。
10. 旧历史信息无法确认时必须标记未知，不得伪造血缘。

## 25. 未来扩展点

本期不实现，但数据模型应允许未来增加：

- PDF、邮件、Telegram 和 RSS 分发；
-不同语言的 report edition；
-人工编辑原因和多管理员审计；
-用户订阅不同报告类型；
-报告质量评分；
-公开版本差异对比；
-专题报告和自定义时间范围报告；
-报告引用外部图表或生成图片。

## 26. 最终完成定义

本需求完成必须同时满足：

```text
同一出版模型覆盖日、周、月报
+
正式版本完整可还原
+
周期报告输入可追溯
+
隐藏治理实时有效
+
普通修订不覆盖历史
+
现有 URL/API 平滑迁移
+
测试、迁移、构建和页面验收全部通过
```

只有页面样式完成、只有新表创建、或只有 API 返回 version 字段，均不视为完成。
