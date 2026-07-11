# AI HOT 动态精选实施计划

> 按测试驱动逐项执行；每个阶段先写失败测试，再做最小实现并回归。

**目标：** 接入 AI HOT 可信精编 Feed，给予独立 50 条预算，并移除固定精选数量及低分补足逻辑。

**架构：** 来源配置声明 `trusted_curated` 策略；抓取层和候选层分别识别该策略并使用独立预算；处理层将来源信任与模型评分解耦；报告层只接收真正入选且属于报告日期的事件；查询层直接读取最近七天已入选事件。

**技术栈：** Python 3、FastAPI、SQLAlchemy/Alembic、unittest/pytest、Next.js。

### 任务 1：来源与 RSS 元数据

- 修改 `apps/api/app/data/default_sources.py`，新增 `aihot_feed`。
- 修改 `apps/api/app/crawlers/rss.py`，保留 `feed_category`、`feed_position`。
- 在 `tests/test_sources_and_storage.py` 与 RSS 解析测试中先增加配置和元数据断言。

### 任务 2：独立抓取与候选预算

- 在 `apps/api/app/crawlers/run.py` 增加可信精编源识别：普通来源合计受 `limit` 限制，可信源分别受 `crawl_limit` 限制。
- 在 `apps/api/app/pipeline/runner.py` 将可信精编条目排除在 `candidate_limit` 计数之外。
- 在 `tests/test_crawl_run.py`、`tests/test_pipeline.py` 覆盖“普通 100 + 精编 50”与顺序无关性。

### 任务 3：来源驱动精选和降级

- 给 `ProcessedArticle` 与 `processed_articles` 增加 `selection_origin`、`selection_reason`，新增 Alembic 迁移并更新仓储映射。
- 在 `apps/api/app/pipeline/runner.py` 让可信精编源跳过预筛、强制入选；评分失败时生成可追溯的原文降级结果。
- 增加低分仍入选、预筛未调用、AI 异常仍保留的测试。

### 任务 4：动态事件精选与日报日期

- 删除 `fill_ids` 和基于 `top_n` 的切片，只聚类真实入选文章。
- 修改 `apps/api/app/services/daily_report_service.py`：按上海自然日过滤事件，输出全部结果，按分数、来源数、时间排序。
- 更新流水线与日报测试，证明低分普通文章不会被补入、超过 12 条不会截断、跨日条目不会进入当日日报。

### 任务 5：最近七天与调用链清理

- 给仓储查询增加 `selected_only`，`/api/public/latest` 读取最近 7 天精选事件并支持 `limit/offset`。
- 删除刷新链路、CLI、Web 管理端和环境变量中的 `top_n`/`DAILY_SELECTED_LIMIT`。
- 更新 API、Web 结构、README 与环境示例测试。

### 任务 6：验证

- 运行相关测试文件，再运行完整 Python 测试套件与 Web 静态检查。
- 运行 Alembic 升级检查，确认无固定 12 条配置或低分补足残留。
- 检查 `git diff`，确保不包含用户现有未跟踪文档。
