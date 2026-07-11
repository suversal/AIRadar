# HotAI 现有表结构第一性原则评估

评估日期：2026-07-11  
评估对象：当前 `codex/source-quality` 分支及本地 PostgreSQL 实际结构

## 核心结论

当前表结构已经从“能跑的 MVP”升级为“分层较清晰的 V1 数据模型”：Alembic、翻译拆表、embedding 落库、人工覆盖、日报条目、跨天事件合并均已实现。

但从第一性原则看，它仍有四个根本问题：

1. **历史出版物与实时内容混合**：日报既保存旧快照，又按当前文章实时重建。
2. **事件身份虽改善，但事件关系仍缺少数据库级保证和治理规则。**
3. **AI 派生数据缺少运行、模型、Prompt 和输入版本血缘。**
4. **Alembic 已引入，但初始化 SQL、ORM、migration 仍没有真正成为单一事实源。**

当前 244 个 Python 测试、TypeScript 检查和 Next.js 生产构建均通过；实际数据库也没有重复成员、孤儿条目或主文错误。这说明应用层当前可运行，但不代表结构已经能够长期演进和审计。

## 一、第一性原则：系统必须保存什么

### 1. 外部事实

某信源在某个时间点发布或返回了什么。

应尽量不可变、可追溯，包括来源、URL、原始标题和正文、抓取时间、内容版本和抓取结果。

### 2. AI 派生结果

基于某一版输入，由某个模型、Prompt 和参数生成的评分、中文标题、摘要、翻译、embedding、分类和标签。

它们可以重算，但必须知道“由什么生成”。

### 3. 现实世界实体

多篇报道可能描述同一个事件：

```text
文章是来源事实
事件是系统识别出的现实实体
```

事件身份不应跟着某篇主文章变化。

### 4. 出版物

日报、周报和月报是“在某个时间正式发布了什么”。出版物必须能够还原历史版本，不能因为后来翻译更新或主文章变化而静默改变。

### 5. 运行与配置

包括任务开始和结束时间、来源成功或失败情况、调用模型、调度配置及人工修改记录。配置可以覆盖，运行历史不能只保存当前摘要。

## 二、当前结构概览

当前数据库有 13 张业务表，外加 `alembic_version`：

```text
配置与来源
└── sources

来源事实
└── raw_articles

AI 派生
├── processed_articles
├── article_embeddings
└── article_translations

人工治理
└── editorial_overrides

事件
├── event_clusters
└── event_cluster_articles

出版物
├── daily_reports
├── daily_report_entries
└── period_reports

运行控制
├── pipeline_runs
└── refresh_schedule
```

当前实际数据量：

| 表 | 数量 |
|---|---:|
| `sources` | 27 |
| `raw_articles` | 81 |
| `processed_articles` | 66 |
| `article_embeddings` | 16 |
| `article_translations` | 49 |
| `editorial_overrides` | 0 |
| `event_clusters` | 12 |
| `event_cluster_articles` | 21 |
| `daily_reports` | 1 |
| `daily_report_entries` | 4 |
| `period_reports` | 2 |
| `pipeline_runs` | 4 |
| `refresh_schedule` | 1 |

## 三、已经解决的问题

### 1. 翻译已经退出 `raw_metadata`

`article_translations` 现在独立保存翻译段落、翻译图文块、源语言和目标语言、原文哈希、状态和错误，解决了抓取数据与 AI 生成数据混放的问题。

### 2. Embedding 已经真正落库

`article_embeddings` 已改为 512 维，与当前本地 BGE 模型一致，并保存 `source_hash`。当前已有 16 条向量，不再是空占位表。

### 3. 人工修改不会被 AI 重算覆盖

`editorial_overrides` 将隐藏、标题、分类和标签从 `processed_articles` 中分离。AI 重算只更新机器结果，人工值在读取时覆盖机器值。

### 4. `/all` 重复事件已经止血

数据库读取现在只返回事件主文章，避免同一事件的多个成员以相同 `event_id` 出现在 `/all`。

当前数据库没有发现：

- 重复的文章处理结果；
- 重复事件成员；
- 一个事件多个主文；
- 主文不在成员列表；
- 日报条目引用不存在事件；
- 日报条目引用不存在日报。

### 5. 跨天事件合并已经出现

部分事件已经积累多个来源：当前分别存在覆盖 6 个、3 个和 2 个不同来源的事件。事件 ID 重定向也会同步到 `processed_articles` 和日报条目。

## 四、历史日报语义不成立

`daily_report_entries` 只快照：

- `reason_snapshot`；
- `score_at_selection`。

标题、摘要、分类、标签、主文章、翻译和事件内容全部读取当前值。

这意味着历史日报可能因后续 AI 重算、主文章替换、人工修改、翻译升级或 README 补全而静默变化，违反“历史报告必须能够还原当时发布版本”的原则。

当前还存在双重语义：

- `daily_reports.sections` 和 `markdown` 保存完整旧快照；
- 有 `daily_report_entries` 时，读取路径忽略旧快照并实时解析；
- 没有条目时才回退到旧快照。

同一张表同时表示历史出版快照和实时内容视图，是当前最需要优先解决的问题。

建议模型：

```text
report_issues
- 2026-07-11 日报这个期号

report_editions
- v1 初次生成
- v2 人工修订
- v3 重新发布

report_entries
- event_id
- main_article_id_at_selection
- position
- title_snapshot
- summary_snapshot
- reason_snapshot
- action_snapshot
- category_snapshot
- tags_snapshot
- score_at_selection
```

人工隐藏可以实时影响所有页面；普通标题、摘要和分类修改不应静默重写历史出版物，而应产生新 edition。

## 五、`daily_report_entries` 的冗余与约束问题

条目同时保存 `event_id` 和 `raw_article_id`，但读取时只使用 `event_id`，没有利用 `raw_article_id` 还原当时主文章。

此外：

- `report_date` 没有外键指向 `daily_reports.report_date`；
- `event_id` 只是字符串，没有外键；
- 没有 `(report_date, event_id)` 唯一约束；
- 同一天重新生成会删除全部条目后重建；
- 没有 edition，历史版本仍会丢失。

## 六、事件身份和事件关系问题

### 1. 缺少持久化事件重定向

跨天匹配会保留已有事件 ID，但 redirect 只存在于一次持久化调用的内存中。系统缺少事件别名、合并历史和拆分历史。

建议增加：

```text
event_aliases
- alias_event_id
- canonical_event_id
- reason
- created_at
```

### 2. 文章—事件关系存在两个事实源

当前关系同时存放在：

- `processed_articles.event_cluster_id`；
- `event_cluster_articles`。

两者理论上可能不一致。推荐以成员表为关系事实，`processed_articles.event_cluster_id` 若保留，应视为查询缓存并增加一致性校验。

### 3. 事件成员缺少数据库硬约束

实际数据库仍缺少：

- `(event_cluster_id, raw_article_id)` 唯一约束；
- 每个事件唯一主文的部分唯一索引；
- `event_clusters.main_article_id` 必须为事件成员的保证；
- 明确的外键删除策略。

### 4. 相似度没有保存

当前 21 条 `event_cluster_articles` 的 `similarity_score` 全部为 0。系统完成了相似度判断，却没有保留聚类证据，无法解释误合并、阈值边界和人工拆分行为。

### 5. `joined_at` 没有参与滑动窗口

字段注释称它用于滑动窗口来源热度，但当前 `source_count` 统计全部历史来源，没有按 `joined_at` 过滤，因此来源数会永久累计。

### 6. API 仍固定返回 `source_count = 1`

尽管 `event_clusters.source_count` 已正确计算，最终事件 payload 仍固定写为 1。数据库中覆盖 6 个来源的事件，前端仍可能显示 1 个来源。

## 七、事件聚类只覆盖日报候选

当前 pipeline 先选出 `top_n` 篇文章，再对这些文章聚类。这意味着大部分未入选文章没有事件关系。

因此必须明确 `/all` 的产品语义：

- 如果是文章流，应使用 `article_id` 作为身份，`event_id` 只作为可选归属；
- 如果是事件流，所有处理文章都应先参与事件归并，日报再从事件中选择 top N。

目前两种语义仍然混合。

另外，先选 top N 文章再聚类会使多个候选合并后条目数下降，系统目前不会从后续候选补足到目标事件数。

## 八、尚未真正使用 pgvector 检索

虽然 `article_embeddings` 使用 pgvector 类型，但相似事件查询实际上会：

1. 查询所有事件主文向量；
2. 全部加载到 Python；
3. 逐个计算 cosine similarity；
4. 在 Python 中过滤时间窗口。

当前只是“用 pgvector 存储”，并没有使用 pgvector 的 SQL 向量检索。

仍缺少：

- `<=>` 或 cosine distance SQL 查询；
- 时间窗口 SQL 过滤；
- HNSW/IVFFlat 索引；
- top-k 候选；
- 事件代表向量。

当前只比较主文章向量，主文章改变时事件语义向量也会突变。更稳定的表示应使用成员向量的归一化 centroid 或事件摘要独立 embedding。

当前 16 条 embedding 的 `embedding_model` 全部为 `unknown`。另外，embedding 输入是 `title + content`，持久化 `source_hash` 却只根据 `content` 计算；标题变化时哈希不能正确反映输入变化。

## 九、翻译血缘不足

当前 49 条翻译均为 `completed`，说明拆表链路已工作。但 `article_translations` 仍缺少：

- provider 和 `model_used`；
- Prompt 版本；
-生成运行 ID；
-输入内容版本；
-重试次数；
- token 和成本；
-真正的 `updated_at`。

同一文章只允许一条翻译，因此目前只能保存一个目标语言和一个模型版本。对于只支持中文的 V1 可以接受，但应明确为产品约束。

## 十、人工覆盖作用域不正确

`editorial_overrides` 绑定 `raw_article_id`，但后台接口接受 `event_id`，然后给当前主文章写 override。

如果事件主文章发生变化，原主文章上的人工标题、分类和标签不会自动作用于新主文章。

需要区分：

- 文章级治理：隐藏某篇来源、修正来源信息；
-事件级治理：修改事件标题、分类、标签、摘要；
-报告级治理：调整某一期顺序和推荐语。

建议至少拆成：

```text
article_editorial_overrides
event_editorial_overrides
```

当前表还缺少修改人、修改原因、审计历史和创建时间。此外，`tags=[]` 不能真正覆盖为无标签，因为读取代码会把空数组当作未覆盖并回退到机器标签。

## 十一、运行血缘基本缺失

实际数据库中：

- 4 条 `pipeline_runs` 的 `finished_at` 全部为空；
- 66 条 `processed_articles.model_used` 全部为空。

运行记录仍在 pipeline 成功后才插入，也没有记录失败路径。

`processed_articles`、`article_translations`、`article_embeddings`、日报和周期报告都没有 `pipeline_run_id`，因此无法回答：

- 哪次任务正在运行、何时结束；
-哪一步失败；
-哪条摘要由哪个模型生成；
-哪次运行写入哪些 embedding；
-哪次运行生成哪一期日报；
-使用了什么阈值和 Prompt。

## 十二、`raw_articles` 仍不是严格的原始事实

重复抓取时会合并 metadata、用更长正文覆盖旧正文并更新状态，但当前 81 条 `raw_articles.updated_at` 全部等于 `created_at`。

数据库无法判断文章何时被全文补抓、README 更新或内容升级。同一个 URL 也只有一条记录，后续内容会覆盖前一版。

V1 可以把它定义为“当前规范化文章”；如果未来需要审计，应增加 `article_observations` 或 `raw_article_versions`。

## 十三、信源健康没有历史

`sources` 只有最近抓取、最近成功、EMA 成功率和错误次数，没有逐次抓取结果，无法进行 7 天稳定性分析。

`fetch_interval_min` 目前也只被配置和展示，没有真正决定单个来源何时抓取。

建议增加：

```text
crawl_runs
source_crawl_results
```

## 十四、Alembic 仍不是唯一 Schema 来源

当前策略是：

- Alembic baseline 为空；
-历史结构由 `init.sql` 创建；
-现有数据库手工 `stamp`；
-后续变更既写 migration，又同步更新 `init.sql`。

对于全新数据库，`init.sql` 已创建最新表，但 `alembic_version` 尚不存在；直接执行 `alembic upgrade head` 可能再次创建已有表，因此仍依赖额外的 `stamp head` 协议。

推荐让 `init.sql` 只创建 extension 和数据库基础，全部业务表由 Alembic 从空库创建。

## 十五、数据库硬约束和索引不足

实际 PostgreSQL 仍缺少：

- `processed_articles(raw_article_id)` 唯一索引；
- `event_cluster_articles(event_cluster_id, raw_article_id)` 唯一约束；
-每个事件唯一主文的部分唯一索引；
- `daily_report_entries.report_date` 到日报的外键；
- `daily_report_entries.event_id` 到事件或 alias 的外键；
-调度配置单例约束；
-状态字段 CHECK；
-日期范围 CHECK；
-明确的外键删除策略。

关键查询索引也不足：

- `raw_articles(published_at DESC)`；
- `raw_articles(source_id)`；
- `processed_articles(event_cluster_id)`；
- `event_cluster_articles(event_cluster_id)`；
- `event_cluster_articles(raw_article_id)`；
-向量 HNSW 索引。

## 最终评价与优先级

当前重构已经解决了大约一半旧结构问题，应用层质量不错，实际数据也满足主要不变量。

生产级结构仍应按以下优先级收口：

1. **明确日报是历史出版物还是实时视图；推荐引入 edition 和完整条目快照。**
2. **补全 pipeline、crawl、model、Prompt 血缘和真实运行时间。**
3. **统一 Alembic 为 schema 唯一来源，并补数据库硬约束。**
4. **明确 `/all` 是文章流还是事件流，避免混合身份语义。**
5. **完善事件 alias、合并/拆分、事件级人工治理和相似度证据。**
6. **将跨天匹配迁移到真正的 pgvector top-k 查询，并使用稳定事件向量。**
7. **最后清理 `daily_reports.sections/markdown`、旧状态字段和双写文件路径。**

现在最需要避免的是继续增加功能。表已经拆开，但“历史、身份、血缘、约束”这四个系统级语义还没有完全闭合。
