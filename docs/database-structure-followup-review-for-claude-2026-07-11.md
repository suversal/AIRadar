# HotAI 数据库结构重构复核意见（供 Claude 沟通）

复核日期：2026-07-11  
复核分支：`codex/source-quality`  
复核范围：截至提交 `cbc98ce0` 的代码、Alembic migration 与本地 PostgreSQL 实际结构

## 一、总体评价

这一轮修改已经关闭了上一版评估中的大多数数据库基础问题，当前结构不再只是依靠 Repository 代码维持正确性，而是开始由数据库约束、索引和 migration 共同保证。

已经确认完成的关键改进包括：

- Alembic 成为业务 Schema 的单一事实源；
- `init.sql` 只负责创建 pgvector extension；
- Alembic baseline 可以从空数据库创建完整历史结构；
- 增加文章处理结果、事件成员、主文和日报条目的关键唯一约束；
- 增加 `/all`、事件成员和来源查询所需索引；
- 新增事件级人工覆盖，避免主文章变化导致人工修正失效；
- 允许人工将标签明确清空为空数组；
- API 返回事件真实去重来源数；
- embedding 模型名和 `source_hash` 生成逻辑已修正；
- 新运行可以记录真实开始、结束时间和失败状态；
- 当轮事件聚类开始保存成员相似度。

验证结果：

- 259 个 Python 测试通过；
- TypeScript 类型检查通过；
- Next.js 生产构建通过；
- 当前 Alembic revision 为 `a7d51c3e9f24`；
- 实际数据库没有重复处理结果、重复事件成员、多个主文或孤儿日报条目。

因此，后续讨论重点不应再放在“是否需要拆表、是否需要 Alembic”上，而应转向以下三类语义：

1. 历史出版物是否允许随当前内容变化；
2. 事件是否是全站一等实体，如何处理合并、拆分和身份重定向；
3. AI 结果是否能够追溯到具体运行、模型、Prompt 和输入版本。

## 二、上一轮问题的当前状态

| 问题 | 当前状态 | 说明 |
|---|---|---|
| Alembic 不是单一事实源 | 已解决 | baseline 已补全，`init.sql` 只创建 extension |
| ORM、SQL、实际数据库约束漂移 | 基本解决 | 关键唯一约束和索引已迁移到实际数据库 |
| `processed_articles.raw_article_id` 无唯一约束 | 已解决 | 已创建唯一索引 |
| 事件成员可能重复 | 已解决 | 已增加成员组合唯一约束 |
| 一个事件可能多个主文 | 已解决“至多一个” | 部分唯一索引已加入；“至少一个”仍由应用保证 |
| 日报同日重复事件 | 已解决 | 已增加 `(report_date, event_id)` 唯一约束 |
| 日报条目可引用不存在日报 | 已解决 | 已增加 report date 外键 |
| 人工覆盖绑定当前主文章 | 已解决 | 新增 `event_editorial_overrides` |
| 空标签不能覆盖 | 已解决 | `tags=[]` 被视为有效覆盖 |
| API 固定返回 `source_count=1` | 已解决 | payload 读取事件真实来源数 |
| embedding 模型名 `unknown` | 代码已解决 | 旧数据库记录尚未回填 |
| embedding 哈希不包含标题 | 已解决 | 哈希与向量输入统一为 `title + content` |
| pipeline 无结束时间和失败记录 | 代码已改善 | 旧数据仍为空；还不是完整运行状态机 |
| 聚类相似度没有保存 | 部分解决 | 当轮聚类可保存；跨天语义和旧数据仍有问题 |
| 日报历史内容实时漂移 | 未解决 | 当前仍按 entries 实时解析内容 |
| pgvector 没有用于向量查询 | 未解决 | 仍把向量全部加载到 Python 计算 |
| 只聚类日报候选 | 未解决 | 事件表仍不是全部处理文章的事件图谱 |
| AI 结果缺少运行和模型血缘 | 未解决 | 派生表仍没有 `pipeline_run_id` 等字段 |
| 来源抓取没有历史 | 未解决 | `sources` 仍只保存当前摘要 |

## 三、已确认正确的修改

### 1. Alembic 单一事实源

当前迁移策略已经合理：

```text
init.sql
└── 只创建 pgvector extension

Alembic baseline
└── 创建 Alembic 接入时的历史完整结构

后续 migrations
└── 按顺序演进到当前结构
```

文档还记录了 scratch pgvector 数据库执行 `alembic upgrade head` 后与生产库 schema diff 一致。这一方向建议保持，不再恢复业务表的 SQL/Alembic 双维护。

仍建议将 scratch migration 验证加入 CI，而不是只保留人工验收记录。

### 2. 数据库完整性约束

新增 migration 已正确补充：

- `processed_articles(raw_article_id)` 唯一索引；
- `event_cluster_articles(event_cluster_id, raw_article_id)` 唯一约束；
- 每个事件至多一个主文的部分唯一索引；
- `daily_report_entries(report_date, event_id)` 唯一约束；
- 日报条目到日报的外键；
- 原文时间、来源、处理结果事件 ID、成员双向查询索引。

这些都是合理且必要的修复。

### 3. 事件级人工覆盖

事件级和文章级人工治理已经分开：

```text
已聚类事件
└── event_editorial_overrides

未聚类独立文章
└── editorial_overrides
```

读取优先级也已明确：

```text
事件级人工覆盖
> 文章级人工覆盖
> AI 结果
```

这一设计能够保证主文章变化后，事件级人工标题、分类、标签和隐藏状态继续有效。

## 四、仍需优先讨论：日报究竟是什么

当前 `daily_report_entries` 只保存：

- `event_id`；
- `raw_article_id`；
-位置；
-推荐理由快照；
-入选时分数。

日报读取时会根据 `event_id` 获取当前主文章和当前 AI 内容，因此历史日报会随着以下变化而改变：

- AI 重新评分或重新总结；
-事件更换主文章；
-人工修改事件标题、分类或标签；
-翻译更新；
-正文补抓；
- README 内容补全。

与此同时，`daily_reports` 仍保存旧的完整 `sections` JSON 和 Markdown。于是系统同时存在两套互相冲突的语义：

```text
daily_reports.sections / markdown
└── 生成时的出版快照

daily_report_entries
└── 名单固定、内容实时变化的视图
```

### 需要 Claude 明确回答的问题

1. 日报被定义为“历史出版物”还是“实时精选视图”？
2. 用户打开一周前的日报时，应该看到当时发布内容，还是当前修订后的内容？
3. 普通标题修改是否应该改变历史日报？
4. 严重内容隐藏是否应该即时从所有历史日报消失？
5. 同一天重新生成日报，是覆盖旧版还是创建新 edition？

### 推荐决策

建议采用：

```text
历史内容不可变
+
安全/隐藏状态实时生效
```

即：

- 日报条目保存标题、摘要、推荐理由、行动建议、分类、标签和分数快照；
- `hidden` 作为实时治理层，可以让不应继续展示的内容立即消失；
-普通编辑或重新生成产生新 edition，不静默重写旧版本。

建议目标模型：

```text
report_issues
- 期号，例如 2026-07-11

report_editions
- edition/version
- generated_at
- published_at
- pipeline_run_id
- status

report_entries
- edition_id
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

## 五、聚类相似度仍存在语义错误

当轮聚类现在会记录文章与本轮 bucket 起始向量之间的相似度，这部分正确。

但跨天合并流程是：

```text
新 bucket 主文章向量
→ 与历史事件主文章向量比较
→ 找到目标历史事件
→ 将新 bucket 成员加入历史事件
```

`find_similar_recent_event()` 目前只返回事件 ID，不返回实际跨天匹配分数。

最终写入 `event_cluster_articles.similarity_score` 的值来自：

```python
cluster.article_similarities
```

这个值描述的是新文章与“本轮 bucket”的相似度，不一定是它与“目标历史事件”的相似度。对于只有一篇文章的新 bucket，该值通常是 `1.0`，但真正触发跨天合并的分数可能只是 `0.93`。

因此当前字段混合了两种含义：

- 当轮聚类相似度；
-跨天事件匹配相似度。

建议让查询返回：

```python
SimilarEventMatch(
    event_id: str,
    similarity_score: float,
)
```

跨天合并的新成员应记录真实的事件匹配分数，而不是对自身 bucket 的相似度。

## 六、当前数据库仍需要数据修复

代码修改只保证未来写入正确，历史数据尚未更新。

当前实际数据：

```text
event_cluster_articles：25 条
similarity_score = 0：25 条

article_embeddings：22 条
embedding_model = unknown：22 条

pipeline_runs：5 条 succeeded
finished_at IS NULL：5 条
```

建议区分：

### 可以可靠回填

- embedding 模型名：如果能够确认旧向量均来自 BGE，可重新生成并写入真实模型名；
- embedding `source_hash`：重新根据当前 `title + content` 计算；
-当前事件 `source_count`：可从成员表重新计算。

### 不应伪造回填

- 历史 `pipeline_runs.finished_at`：没有可靠时间来源时保持 NULL，并标记 legacy；
-历史相似度：无法恢复真实比较上下文时，不应填 0，建议改为 NULL 或增加 `similarity_status=legacy_unknown`。

## 七、pipeline 记录仍不是完整运行状态机

现在成功和失败都可以留下记录，但仍是：

```text
任务执行
→ 完成后插入 succeeded

任务异常
→ 捕获后插入 failed
```

它还不是：

```text
开始前插入 running
→ 各阶段更新进度
→ 最终更新 succeeded / failed
```

因此仍无法可靠表示：

- 当前是否真的有任务运行；
-进程是否崩溃或卡死；
-失败发生在哪个阶段；
-由调度器、管理员、CLI 还是其他来源触发；
-本次生成了哪些文章、向量、翻译和报告。

更关键的是，以下派生结果仍没有 `pipeline_run_id`：

- `processed_articles`；
- `article_embeddings`；
- `article_translations`；
- `daily_reports`；
- `period_reports`。

建议将 pipeline run 变为派生数据血缘的根节点。

## 八、`daily_report_entries.event_id` 仍是多态引用

当前 `event_id` 同时表示：

- `e...`：真实 `event_clusters` 事件；
- `a...`：未聚类文章的伪事件。

因此它不能添加普通外键，数据库无法保证这个字符串一定可解析。

条目同时保存了有外键的 `raw_article_id`，但读取路径主要依赖 `event_id`。

建议考虑：

```text
event_cluster_id NULL REFERENCES event_clusters(id)
raw_article_id NOT NULL REFERENCES raw_articles(id)
```

其中：

- 聚类条目同时保存事件 ID 和当时主文章 ID；
-独立文章条目的 `event_cluster_id` 为 NULL；
-不再通过字符串前缀判断实体类型。

## 九、事件关系仍有两个事实源

文章归属事件同时存储于：

- `processed_articles.event_cluster_id`；
- `event_cluster_articles`。

当前 redirect 逻辑已经专门负责同步两者，这说明重复关系已经带来实现复杂度。

需要 Claude 明确：

1. 哪张表是事件成员关系的唯一事实源？
2. `processed_articles.event_cluster_id` 是正式关系还是查询缓存？
3. 如何持续验证两者一致？

推荐以 `event_cluster_articles` 为事实源。如果保留 `processed_articles.event_cluster_id`，应明确为缓存，并增加一致性审计或数据库触发器。

## 十、事件聚类范围仍不完整

当前处理顺序仍是：

```text
处理文章
→ 先选择 top N 文章
→ 只对这些文章聚类
→ 生成日报
```

因此事件表不是全部处理文章的事件图谱，只覆盖日报候选。

这会带来：

- 大量 `processed_articles` 没有事件关系；
- `/all` 同时包含事件主文和独立文章；
-文章身份和事件身份混合；
-多个 top N 文章合并后，日报事件数量下降；
-系统不会从后续候选补足目标事件数。

如果产品目标是“事件级 AI 情报雷达”，更合理的顺序是：

```text
处理全部候选文章
→ 全部文章事件归并
→ 事件级评分和主文选择
→ 从事件中选择 top N
→ 出版日报
```

## 十一、pgvector 仍只用于存储

跨天事件查询仍然会加载全部事件主文向量，在 Python 中逐个计算余弦相似度和过滤时间窗口。

当前尚未使用：

- pgvector cosine distance 查询；
- SQL top-k；
-数据库时间窗口过滤；
- HNSW/IVFFlat 索引；
-事件代表向量。

当前事件数量很少，这不是即时性能故障，但必须在规模扩大前解决。

此外，事件仍由当前主文章向量代表。主文章更换时，事件的向量语义会突变。建议使用成员向量 centroid 或独立事件摘要 embedding。

## 十二、仍未解决的运行与治理问题

### 1. 来源抓取历史

`sources` 仍只保存当前健康摘要，没有 `crawl_runs` 和 `source_crawl_results`，无法做可靠的 7 天来源稳定性分析。

### 2. AI 和翻译血缘

仍缺少 provider、模型版本、Prompt 版本、run ID、token 和成本。

### 3. 原文版本

`raw_articles` 会被后续全文补抓覆盖，`updated_at` 没有完整维护，也没有文章观察或版本历史。

### 4. 状态约束

文章、处理结果、报告和事件状态仍是自由字符串，没有数据库 CHECK。

### 5. 调度配置单例

`refresh_schedule` 仍由应用取第一行，数据库没有保证只能存在一个配置。

### 6. 删除策略

来源、文章、事件、报告和人工覆盖的 `ON DELETE` 行为没有形成统一保留策略。

### 7. 人工审计

人工覆盖表仍缺少修改人、修改原因、创建时间和不可变操作历史。

## 十三、建议后续优先级

### P0：必须先做产品与数据语义决策

1. 明确日报是不可变出版物还是实时视图。
2. 明确 `/all` 是文章流还是事件流。
3. 明确事件成员关系的唯一事实源。

### P1：保证可追溯和可解释

1. 建立真正的 pipeline run 状态机。
2. 为 AI、embedding、翻译和报告增加 run/model/prompt 血缘。
3. 修正跨天聚类相似度证据。
4. 增加事件 alias、合并和拆分历史。

### P2：完成事件系统

1. 将聚类前移到全部处理文章。
2. 使用真正的 pgvector top-k。
3. 引入稳定事件向量或 centroid。
4. 处理旧 embedding、相似度和运行数据。

### P3：运维和长期治理

1. 增加来源抓取历史。
2. 增加人工操作审计。
3. 增加状态 CHECK、调度单例和删除策略。
4. 将空库 migration 验证纳入 CI。

## 十四、希望 Claude 重点回答的问题

1. 历史日报应展示发布时内容还是当前最新内容？
2. 是否需要 report edition？如果不需要，如何解释历史日报内容变化？
3. `/all` 的业务实体是文章还是事件？
4. 为什么只聚类 top N 文章，而不是全部 processed articles？
5. `processed_articles.event_cluster_id` 和成员表谁是唯一事实源？
6. 跨天合并应保存哪一个相似度：文章对本轮 bucket，还是文章对目标历史事件？
7. 事件主文章变更后，事件代表向量如何保持稳定？
8. 什么时候将向量检索迁移到 pgvector top-k？
9. 派生结果如何关联 pipeline run、模型和 Prompt 版本？
10. 历史旧数据中的 `unknown` embedding、零相似度和空结束时间如何处理？

## 结论

这一版已经完成数据库基础设施和关键约束层面的主要收口，后续不应再进行零散补字段，而应围绕三个核心模型做完整决策：

```text
出版模型：历史是否可还原
事件模型：身份、成员、合并与拆分
血缘模型：每个 AI 结果从哪里来
```

这三个模型一旦确定，剩余迁移、索引和 API 调整才能形成稳定的最终结构。
