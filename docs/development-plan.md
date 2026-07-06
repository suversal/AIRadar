# Suversal AI Radar 完整开发计划书

最后更新：2026-07-06
当前分支：`codex/ai-radar-data-loop`  
当前阶段：Phase 0 已完成，Phase 1 真实采集闭环进行中，Phase 6 前端 MVP 骨架进行中

## 0. 总进度看板

| 阶段 | 状态 | 当前结论 | 下一步 |
| --- | --- | --- | --- |
| Phase 0 - 本地数据闭环骨架 | 已完成 | 代码骨架、核心模型、crawler 基础、AI 边界、评分、聚类、日报、CLI、测试、Docker 配置均已落地 | 进入真实源抓取验证 |
| Phase 1 - 真实采集与质量闭环 | 进行中 | 已联网检查，当前 7/11 个 source 可抓取；真实 raw 可进入 fake AI 日报闭环 | 修正 Anthropic/DeepMind/Reddit ML/机器之心失败源，并继续人工检查日报质量 |
| Phase 2 - OpenAI 接入、AI 总结与真实评分 | 未开始 | 需要 `.env` 中配置 `OPENAI_API_KEY`；Phase 0 已打通 fake AI 总结字段链路 | 小批量运行真实 AI pipeline，验证中文总结质量 |
| Phase 3 - PostgreSQL + pgvector 持久化 | 进行中 | Docker 已安装；Postgres/Redis healthy；pipeline CLI 已写库；FastAPI public endpoints 已可读数据库 | 补 Alembic 迁移和 pgvector 相似查询 |
| Phase 4 - API 与日报服务化 | 进行中 | 本地 FastAPI 服务已启动并通过 HTTP smoke；latest/daily 从 DB 读到 12 条日报 | 等 API compose 网络问题恢复后补容器验证 |
| Phase 5 - 任务调度与稳定性 | 未开始 | Celery/Redis/scheduler 尚未接入 | 等数据库持久化完成后启动 |
| Phase 6 - 前端 MVP | 进行中 | `apps/web` Next.js + Tailwind 骨架、`/latest`、`/daily` 和 `/event/:id` 已完成并通过 build/dev HTTP 验证 | 补 `/all` 和 `/search` |
| Phase 7 - RSS/Public API/MCP | 未开始 | RSS/Public API 完整版和 MCP 暂缓 | 等 API 和数据质量稳定后启动 |
| Phase 8 - 后台管理 | 未开始 | 后台暂缓，避免早期范围膨胀 | 等数据闭环稳定后启动 |

## 0.1 已完成任务索引

以下任务已经完成，后文对应条目也已标为 `[x]`：

- [x] 已完成：后端优先 Monorepo 骨架。
- [x] 已完成：Python 项目配置和依赖声明。
- [x] 已完成：`.env.example` 环境变量模板。
- [x] 已完成：核心领域模型。
- [x] 已完成：默认信源清单。
- [x] 已完成：URL/title 标准化和 hash 去重基础。
- [x] 已完成：RSS、HN、GitHub crawler 基础。
- [x] 已完成：AI provider 边界、fake provider、OpenAI 调用边界。
- [x] 已完成：fake AI 总结字段链路，覆盖中文标题、一句话摘要、核心摘要、推荐理由和下一步动作。
- [x] 已完成：评分公式、阈值和精选判断。
- [x] 已完成：事件聚类基础和主条选择。
- [x] 已完成：Markdown/JSON 日报生成。
- [x] 已完成：本地 JSON 存储。
- [x] 已完成：本地 pipeline runner。
- [x] 已完成：CLI 脚本。
- [x] 已完成：最小 public API helper 和 route。
- [x] 已完成：Docker/Postgres/Redis/pgvector 配置文件。
- [x] 已完成：Docker Desktop/Compose 本机验证。
- [x] 已完成：Postgres + pgvector + Redis 基础服务启动验证。
- [x] 已完成：数据库健康检查脚本 `scripts/check_db_once.py`。
- [x] 已完成：SQLAlchemy session helper 和 repository 初版。
- [x] 已完成：pipeline persistence helper，可将 `PipelineResult` 写入 repository。
- [x] 已完成：`run_pipeline_once.py --persist-db` 写入 PostgreSQL。
- [x] 已完成：Public API repository payload helper。
- [x] 已完成：FastAPI public endpoints 接入 repository/DB 查询。
- [x] 已完成：API HTTP smoke 检查脚本和本地服务验证。
- [x] 已完成：Phase6 `apps/web` Next.js/Tailwind 骨架。
- [x] 已完成：`/latest` 分类筛选。
- [x] 已完成：`/latest` 浏览器截图级视觉验收。
- [x] 已完成：`/daily` 和 `/daily/:date` 日报页。
- [x] 已完成：`/event/:id` 事件详情页。
- [x] 已完成：README、实施说明和本开发计划书。
- [x] 已完成：本地 fake raw fixture。
- [x] 已完成：本地样例日报生成，当前样例为 12 条精选。
- [x] 已完成：真实 crawl pass 逐源报告。
- [x] 已完成：arXiv/Reddit Atom 日期、作者、链接解析兼容。
- [x] 已完成：GitHub Trending parser 不再误抓 `/trending/...` 伪 repo。
- [x] 已完成：HN 关键词边界过滤，不再把 `Aims` 这类子串误当作 `AI`。
- [x] 已完成：真实抓取结果跑通 fake AI pipeline。
- [x] 已完成：46 个单元测试全部通过。

## 1. 项目目标

Suversal AI Radar 第一版不是资讯站外壳，而是一个可持续运行的 AI 情报数据闭环：

- 从官方源、社区源、论文源、GitHub、Reddit 和中文媒体采集 AI 相关内容。
- 统一成 `RawArticle`，做 URL/title 去重和来源分级。
- 用 AI 做预筛、中文总结、六维评分、推荐理由和下一步行动建议。
- 用代码公式决定精选，避免完全依赖模型判断。
- 用 embedding/pgvector 聚合同一事件，减少重复报道。
- 每天生成少而精的 Markdown 日报和 JSON 数据，后续供 API、前端、RSS 和 MCP 使用。

## 2. 状态说明

- `[x]` 已完成并通过当前验证。
- `[ ]` 未完成。
- `[!]` 需要外部环境、账号、真实数据或进一步人工验收。
- 如果阅读器没有明显渲染 checkbox，请以“总进度看板”的“状态”列为准。

当前已通过验证：

```bash
.venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/hotai_pycache .venv/bin/python -m compileall apps/api scripts
python3 scripts/seed_sources.py --output data/sources.json
python3 scripts/run_pipeline_once.py --limit 100 --fake-ai --date 2026-07-01
python3 scripts/run_crawl_once.py --limit 30 --output data/crawl_checks/2026-07-01-hn-quality-crawl.json --report data/crawl_checks/2026-07-01-hn-quality-crawl-report.json
python3 scripts/run_pipeline_once.py --raw data/crawl_checks/2026-07-01-hn-quality-crawl.json --output-dir data/crawl_checks/hn-quality-pipeline --limit 100 --top-n 12 --fake-ai --date 2026-07-01
docker --version
docker compose version
docker compose -f infra/docker-compose.yml up -d postgres redis
python3 scripts/check_db_once.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/run_pipeline_once.py --limit 20 --top-n 12 --fake-ai --persist-db --database-url postgresql+psycopg://radar:radar@localhost:5432/radar --date 2026-07-02
.venv/bin/python scripts/check_api_once.py --base-url http://127.0.0.1:8000 --date 2026-07-02
```

当前测试结果：46 个测试通过。

## 3. 当前已完成范围

### Phase 0 - 本地数据闭环骨架

- [x] 创建后端优先 Monorepo 骨架。
  - 关键目录：`apps/api`、`scripts`、`infra`、`docs`、`tests`。
  - 验收：仓库内已存在后端包、脚本、Docker 配置、测试和文档。

- [x] 建立 Python 项目配置。
  - 文件：`pyproject.toml`、`requirements.txt`、`requirements-dev.txt`。
  - 验收：Python 3.9+ 可运行当前测试；FastAPI/SQLAlchemy 等依赖已声明。

- [x] 建立环境变量模板。
  - 文件：`.env.example`。
  - 验收：包含 `DATABASE_URL`、`REDIS_URL`、`OPENAI_API_KEY`、`GITHUB_TOKEN`、模型和成本保护配置。

- [x] 建立核心领域模型。
  - 文件：`apps/api/app/models/domain.py`。
  - 覆盖对象：`Source`、`RawArticle`、`ScoreDimensions`、`ProcessedArticle`、`EventCluster`、`DailyReport`、`PipelineResult`。
  - 验收：测试可直接构造领域对象并运行评分、聚类、日报逻辑。

- [x] 实现默认信源清单。
  - 文件：`apps/api/app/data/default_sources.py`。
  - 已覆盖：OpenAI、Anthropic、DeepMind、Hugging Face、HN、arXiv、GitHub Trending、Reddit LocalLLaMA、Reddit MachineLearning、机器之心、量子位。
  - 验收：`test_default_sources_cover_required_first_batch` 通过。

- [x] 实现 URL/title 标准化和去重基础。
  - 文件：`apps/api/app/crawlers/base.py`。
  - 能力：去掉 `utm_*`、`fbclid`、`gclid` 等跟踪参数，生成稳定 hash。
  - 验收：`test_normalize_article_removes_tracking_and_hashes_url_and_title` 通过。

- [x] 实现基础 crawler。
  - 文件：`apps/api/app/crawlers/rss.py`、`hn.py`、`github.py`、`registry.py`。
  - 当前能力：RSS/Atom 解析、HN Algolia API 解析、GitHub Trending HTML 轻量解析、按 source type 选择 crawler。
  - 验收：RSS fixture 测试通过；真实网络抓取尚未作为自动测试启用。

- [x] 实现 AI provider 边界。
  - 文件：`apps/api/app/services/ai_service.py`。
  - 已完成：`FakeAIProvider`、OpenAI embeddings/chat 调用边界、预筛 JSON 解析、评分/总结 JSON 解析、分数 clamp。
  - AI 总结字段：`title_zh`、`one_line_summary`、`summary_zh`、`reason_zh`、`action_zh`。
  - 验收：fake provider 与 JSON 解析测试通过。

- [x] 实现评分公式。
  - 文件：`apps/api/app/services/scoring_service.py`。
  - 已完成：PRD 六维权重、来源 tier 权重、freshness、category threshold、community heat bonus、精选判断。
  - 默认权重：T1=1.2、T1_5=1.1、T2=1.0、T3=0.85。
  - 验收：base score、final score、threshold 测试通过。

- [x] 实现事件聚类基础。
  - 文件：`apps/api/app/services/clustering_service.py`。
  - 已完成：cosine similarity、相似内容聚类、主条选择、聚合源不抢主条。
  - 验收：相似向量聚合和主条优先级测试通过。

- [x] 实现 Markdown/JSON 日报生成。
  - 文件：`apps/api/app/services/daily_report_service.py`。
  - 已完成：按分类输出日报，每条包含标题、摘要、为什么重要、下一步、来源、标签。
  - 验收：日报模板测试通过。

- [x] 实现本地 JSON 存储。
  - 文件：`apps/api/app/storage/json_store.py`。
  - 用途：Phase 0 在没有 Postgres 时保存 sources、raw articles、processed articles、clusters、daily reports。
  - 验收：sources JSON round-trip 测试通过。

- [x] 实现 pipeline runner。
  - 文件：`apps/api/app/pipeline/runner.py`。
  - 流程：source raw items -> normalize -> dedupe -> fake/OpenAI prefilter -> score -> embed -> cluster -> report。
  - 验收：`test_pipeline_skips_over_limit_and_generates_daily_report` 通过。

- [x] 实现 CLI 脚本。
  - 文件：`scripts/seed_sources.py`、`run_crawl_once.py`、`run_pipeline_once.py`、`build_daily_report.py`。
  - 验收：seed 和 fake pipeline smoke 已通过。

- [x] 实现最小 public API 入口。
  - 文件：`apps/api/app/main.py`、`apps/api/app/api/public.py`。
  - 已提供：`/health`、`/api/public/latest`、`/api/public/daily/{date}`。
  - 验收：payload contract 测试通过；FastAPI 运行需安装依赖。

- [x] 建立 Docker/Postgres/Redis 骨架。
  - 文件：`infra/docker-compose.yml`、`infra/Dockerfile.api`、`infra/postgres/init.sql`。
  - 包含：PostgreSQL + pgvector、Redis、API service、核心表结构。
  - 验收：Postgres + pgvector + Redis 已通过容器运行验证；API service 构建仍待 Docker Hub 网络恢复后验证。

- [x] 建立基础文档。
  - 文件：`README.md`、`docs/implementation-notes.md`、本文件。
  - 验收：README 已包含当前运行命令、Docker 说明和当前范围。

## 4. 当前本地样例数据状态

- [x] 已生成本地 fake raw fixture。
  - 文件：`data/raw_articles.json`。
  - 内容：13 条样例 raw article，其中 12 条 AI 相关，1 条非 AI 用于验证过滤。
  - 注意：`data/` 已被 `.gitignore` 忽略，不会提交到 Git。

- [x] 已生成样例日报。
  - 文件：`data/reports/2026-07-01.md` 和 `data/reports/2026-07-01.json`。
  - 当前结果：12 条精选事件，1 条非 AI 内容被过滤。
  - 命令：

```bash
python3 scripts/run_pipeline_once.py --limit 100 --fake-ai --date 2026-07-01
python3 scripts/build_daily_report.py --date 2026-07-01 --format markdown
```

## 4.1 最近一次真实数据源检查

检查时间：2026-07-01  
检查命令：

```bash
python3 scripts/run_crawl_once.py --limit 30 --output data/crawl_checks/2026-07-01-hn-quality-crawl.json --report data/crawl_checks/2026-07-01-hn-quality-crawl-report.json
```

输出文件：`data/crawl_checks/2026-07-01-hn-quality-crawl.json`。

结论：当前数据源获取不是全部正常，但比第一轮有明显改善。联网环境下抓到 14 条真实文章，来自 7 个 source；4 个 source 失败。

成功 source：

- [x] `openai_blog`：成功抓取 2 条。
- [x] `huggingface_blog`：成功抓取 2 条。
- [x] `hacker_news`：成功抓取 2 条，已增加关键词边界过滤，本轮未再出现 `Aims/Taiwan` 误匹配。
- [x] `arxiv_ai`：成功抓取 2 条，已修复 Atom ISO 日期和作者解析。
- [x] `github_trending_ai`：成功抓取 2 条，已修复 `/trending/...` 伪 repo 误识别。
- [x] `reddit_localllama`：成功抓取 2 条，已修复 Atom alternate link 和作者解析。
- [x] `qbitai`：成功抓取 2 条。

失败 source：

- [!] `anthropic_news`：HTTP 404，当前候选 RSS URL 未找到可用版本，可能需要改 HTML/站点地图采集。
- [!] `deepmind_blog`：HTTP 404，当前 URL 失效，需要修正。
- [!] `reddit_machinelearning`：HTTP 429，被 Reddit 限流，需要降频、加 User-Agent 或改用 RSS/API 策略。
- [!] `jiqizhixin`：XML `mismatched tag`，该 feed 不是标准 XML 或内容不干净，需要容错解析或替换源。

下一步修复顺序：

1. 修正 DeepMind URL 或改 HTML 采集。
2. 为 Anthropic 增加 HTML/站点地图采集降级。
3. 对 Reddit MachineLearning 增加限流退避或降频策略。
4. 对机器之心增加 XML 容错或替换成可用 RSS/HTML 源。
5. 人工检查真实日报质量，继续压低 Reddit/HN 低价值内容比例。

## 5. Phase 1 - 真实采集与质量闭环

目标：从 fake fixture 过渡到真实公开信源，仍然使用 JSON 文件作为本地持久化，先验证采集稳定性和日报质量。

- [x] 真实运行 RSS/公开 API 抓取。
  - 涉及文件：`scripts/run_crawl_once.py`、`apps/api/app/crawlers/*`。
  - 命令：

```bash
python3 scripts/seed_sources.py
python3 scripts/run_crawl_once.py --limit 100
```

  - 验收：
    - `data/raw_articles.json` 或指定 `--output` 文件生成真实文章。
    - 单个 source 失败只输出 `SKIPPED <source_id>`，不阻塞其他 source。
    - 至少 5 个 source 有有效输出。本轮验证：7 个 source 有有效输出。

- [!] 调整真实源可用性。
  - 重点检查：OpenAI RSS、Anthropic RSS、DeepMind RSS、Hugging Face RSS、Reddit RSS、机器之心 RSS、量子位 RSS。
  - 验收：
    - 已完成：OpenAI、Hugging Face、arXiv、GitHub Trending、Reddit LocalLLaMA、QbitAI、HN 可抓。
    - 未完成：Anthropic、DeepMind、Reddit MachineLearning 限流、机器之心 XML 异常。
    - 反爬或不可用源保留但标记为 skipped/degraded。

- [x] 增强 crawler 失败记录。
  - 建议文件：`apps/api/app/crawlers/registry.py`、`scripts/run_crawl_once.py`。
  - 验收：
    - 输出每个 source 的成功数、失败原因和耗时。
    - 失败原因可进入 `data/crawl_report.json`。
    - 本轮已新增 `--report`，报告包含 `per_source`、`duration_ms`、`error`、`skipped_reasons`。

- [x] 真实数据跑 fake AI pipeline。
  - 命令：

```bash
python3 scripts/run_pipeline_once.py --limit 100 --fake-ai --date 2026-07-01
```

  - 验收：
    - 日报生成成功。本轮验证：14 条真实 raw，12 条 selected，12 个 clusters。
    - 非 AI 内容能被过滤。本轮 fake provider 过滤 2 条。
    - 结果中没有大量重复标题或明显非 AI 内容。HN `Aims/Taiwan` 误收已通过关键词边界过滤修复；Reddit/HN 低价值内容仍需人工检查和后续调参。

- [!] 人工检查首批真实日报质量。
  - 检查点：
    - 精选是否值得看。
    - 中文标题/摘要是否可读。
    - 分类是否合理。
    - 来源是否可信。
    - 是否有重复事件未聚合。

## 6. Phase 2 - OpenAI 接入、AI 总结与真实评分

目标：使用真实 OpenAI API 替换 fake provider，验证预筛、AI 中文总结、推荐理由、六维评分和 embedding 的真实质量。

当前说明：

- Phase 0 已经打通 AI 总结字段的端到端链路，但使用的是 `FakeAIProvider`，只适合本地干跑和测试。
- 真实的“AI 总结功能”从 Phase 2 开始验收：每条精选事件由 OpenAI 生成中文标题、一句话摘要、核心摘要、推荐理由和下一步动作。
- 日报 Markdown 当前展示中文标题、一句话摘要、核心总结、推荐理由和下一步动作；JSON 同时保留 `summary` 核心摘要，供后续 API/前端复用。

- [ ] 配置 `.env`。
  - 文件：从 `.env.example` 复制为 `.env`。
  - 必填：`OPENAI_API_KEY`。
  - 可选：`GITHUB_TOKEN`。

- [ ] 使用 OpenAI 跑小批量 pipeline。
  - 命令：

```bash
OPENAI_API_KEY=<key> python3 scripts/run_pipeline_once.py --limit 20 --date 2026-07-01
```

  - 验收：
    - 预筛 JSON 能稳定解析。
    - 评分 JSON 能稳定解析。
    - embedding 返回向量。
    - 日报中文内容明显优于 fake provider。

- [ ] 验收 AI 总结质量。
  - 涉及文件：`apps/api/app/services/ai_service.py`、`apps/api/app/pipeline/runner.py`、`apps/api/app/services/daily_report_service.py`。
  - 每条精选事件必须包含：
    - `title_zh`：中文标题，不机械翻译。
    - `one_line_summary`：一句话摘要，说明发生了什么。
    - `summary_zh`：核心摘要，保留关键事实和上下文。
    - `reason_zh`：为什么值得看，必须是判断型理由。
    - `action_zh`：下一步可行动作。
  - 验收：
    - Markdown 日报展示标题、一句话摘要、核心总结、推荐理由和下一步动作。
    - JSON 日报保留完整 `summary/reason/action` 字段。
    - 抽查 Top 8-12 条没有明显机器翻译腔、空泛套话或事实缺失。

- [ ] 增加 AI 调用成本统计。
  - 建议文件：`apps/api/app/services/ai_service.py`、`apps/api/app/pipeline/runner.py`。
  - 验收：
    - 记录 prefilter/score/embed 调用次数。
    - 记录 token 或近似成本。
    - 超过 `DAILY_CANDIDATE_LIMIT` 后跳过并记录 skipped reason。

- [ ] 增强模型返回错误处理。
  - 覆盖场景：非法 JSON、缺字段、超时、HTTP error、分数越界。
  - 验收：
    - 单条文章 AI 失败不阻塞整批。
    - 失败文章进入 skipped/retry 状态。

- [ ] 调整日报生成 prompt 风格。
  - 目标：少而精判断型，而不是泛泛摘要。
  - 每条必须包含：
    - 为什么重要。
    - 适合谁看。
    - 下一步行动。
    - 主来源链接。

## 7. Phase 3 - PostgreSQL + pgvector 持久化

目标：从 JSON 文件过渡到数据库，支持长期运行、去重、聚类、API 查询和后续后台管理。

- [x] 安装并验证 Docker Desktop。
  - 当前状态：本机 `docker` 和 `docker compose` 已可用。
  - 已验证命令：

```bash
docker --version
docker compose version
```

  - 为什么重要：
    - 验证 `infra/docker-compose.yml`。
    - 启动 PostgreSQL + pgvector。
    - 启动 Redis。
    - 后续验证 FastAPI 容器和 Celery worker。

- [x] 验证 Docker Compose 基础服务。
  - 命令：

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d postgres redis
python3 scripts/check_db_once.py
```

  - 验收：
    - Postgres healthcheck 通过。
    - Redis healthcheck 通过。
    - `pg_extension` 中存在 `vector`。
    - public schema 当前初始化表数为 8。
    - Redis `PING` 返回 `PONG`。
  - 本轮结果：
    - `[OK] pgvector: vector extension available`
    - `[OK] tables: 8 public tables available`
    - `[OK] redis: PONG received`

- [ ] 验证 API Docker service。
  - 命令：

```bash
docker compose -f infra/docker-compose.yml up --build api
```

  - 验收：
    - API service 启动。
    - `GET /health` 返回 `{"status":"ok"}`。
  - 说明：基础数据库层已验证，API 容器构建会拉取 Python 依赖，作为 Phase 4 服务化启动项单独验收。

- [x] 实现 SQLAlchemy session 和 repository 初版。
  - 文件：`apps/api/app/db/session.py`、`apps/api/app/repositories/radar_repository.py`。
  - 验收：
    - sources 可写入数据库。
    - raw_articles 可写入数据库并按 url_hash 去重。
    - daily_reports 可写入数据库并被 API 读取。
  - 本轮结果：
    - `upsert_sources` 支持按 source id 新增/更新。
    - `upsert_raw_articles` 支持按 `url_hash` 去重写入。
    - `upsert_daily_report` 支持按 `report_date` 新增/更新。
    - `get_daily_report_payload` 和 `get_latest_daily_report_payload` 可返回 Public API 需要的 JSON payload。
    - ORM 模型已补 `DailyReportModel`，并修正 Python 3.9 下 SQLAlchemy 注解兼容性。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_repositories -v
.venv/bin/python -m unittest discover -s tests -v
```

- [x] 建立 pipeline 结果写入 repository 的 helper。
  - 文件：`apps/api/app/pipeline/persistence.py`。
  - 验收：
    - 先写 sources。
    - 再写 `PipelineResult.raw_articles`。
    - 最后写 `PipelineResult.daily_report`。
    - 返回每一步 repository 写入统计。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_pipeline_persistence -v
```

- [x] 将 pipeline CLI 接入数据库 repository。
  - 文件：`scripts/run_pipeline_once.py`。
  - 验收：
    - CLI 支持选择 JSON 输出或 DB 输出。
    - `PipelineResult.raw_articles` 可写入 `raw_articles`。
    - `PipelineResult.daily_report` 可写入 `daily_reports`。
    - 单次 pipeline 重跑不会重复插入相同 URL。
  - 本轮结果：
    - 新增 `--persist-db`。
    - 新增 `--database-url`。
    - host 侧写入 Docker Postgres 使用 `postgresql+psycopg://radar:radar@localhost:5432/radar`。
    - 第一次运行：`sources=11+0`，`raw_inserted=13`，`daily_inserted=1`。
    - 第二次同命令重跑：`sources=0+11`，`raw_inserted=0`，`raw_skipped=13`，`daily_updated=1`。
    - 数据库确认：`sources=11`，`raw_articles=13`，最新 `daily_reports=2026-07-02|12|generated`。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_run_pipeline_cli -v
.venv/bin/python scripts/run_pipeline_once.py --limit 20 --top-n 12 --fake-ai --persist-db --database-url postgresql+psycopg://radar:radar@localhost:5432/radar --date 2026-07-02
```

- [x] 建立 Public API repository payload helper。
  - 文件：`apps/api/app/api/public.py`。
  - 验收：
    - latest payload 可从 repository 最新日报 payload 构造。
    - daily payload 可按日期从 repository payload 构造。
    - repository 无数据时返回稳定 empty payload。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_report_and_api -v
```

- [x] 将 FastAPI endpoint 接入数据库 repository。
  - 文件：`apps/api/app/main.py`。
  - 验收：
    - `/api/public/latest` 可从 `daily_reports` 读取最新日报。
    - `/api/public/daily/{date}` 可按日期读取日报。
    - 无数据时返回清晰 empty/not found 响应。
  - 本轮结果：
    - `create_app(report_repository_factory=...)` 支持测试注入 repository。
    - 默认运行时若存在 `DATABASE_URL`，endpoint 会按请求打开 `RadarRepository` 读取数据库。
    - 无 `DATABASE_URL` 时保留 JSON 文件 fallback。
    - 真实 Docker Postgres 验证：`latest_items=12`，`daily_date=2026-07-02`，`daily_count=12`。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_api_main -v
env DATABASE_URL=postgresql+psycopg://radar:radar@localhost:5432/radar PYTHONPATH=apps/api .venv/bin/python -c "from app.main import create_app; from fastapi.testclient import TestClient; c=TestClient(create_app()); latest=c.get('/api/public/latest').json(); daily=c.get('/api/public/daily/2026-07-02').json(); print({'latest_items': len(latest['items']), 'daily_date': daily['report_date'], 'daily_count': daily['article_count']})"
```

- [ ] 完成数据库迁移策略。
  - 当前已有：`infra/postgres/init.sql`。
  - 下一步：
    - 引入 Alembic。
    - 将 init schema 转为 migration。
  - 验收：
    - 新数据库可通过 migration 建表。
    - 已有 schema 变更可版本化。

- [ ] 实现 pgvector 相似查询。
  - 当前聚类使用内存向量。
  - 下一步使用数据库 `article_embeddings.content_vector vector(1536)`。
  - 验收：
    - 查询 72 小时内相似文章。
    - similarity >= 0.85 进入同一 cluster。

## 8. Phase 4 - API 与日报服务化

目标：让本地日报 JSON 变成可查询服务，为前端和 RSS 做准备。

- [x] 最小 API payload helper 已完成。
  - 文件：`apps/api/app/api/public.py`。

- [x] 最小 API route 已完成。
  - 文件：`apps/api/app/main.py`。
  - 路由：`/health`、`/api/public/latest`、`/api/public/daily/{date}`。

- [x] 安装依赖并本地启动 API。
  - 命令：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=apps/api uvicorn app.main:app --reload
```

  - 验收：
    - `http://127.0.0.1:8000/health` 返回 ok。
    - `http://127.0.0.1:8000/api/public/latest` 返回日报 items。
  - 本轮结果：
    - 使用 `DATABASE_URL=postgresql+psycopg://radar:radar@localhost:5432/radar` 启动 host 侧 FastAPI。
    - `scripts/check_api_once.py` 验证 `/health`、`/api/public/latest`、`/api/public/daily/2026-07-02`。
    - HTTP smoke 输出：`health: status ok`，`latest: 12 latest items`，`daily: 12 daily items`。

- [x] 增加 API HTTP smoke 检查脚本。
  - 文件：`apps/api/app/api/smoke.py`、`scripts/check_api_once.py`。
  - 验收：
    - 检查 `/health`。
    - 检查 `/api/public/latest` 至少返回一条 item。
    - 检查 `/api/public/daily/{date}` 返回目标日期。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_api_smoke -v
.venv/bin/python scripts/check_api_once.py --base-url http://127.0.0.1:8000 --date 2026-07-02
```

- [x] API 改为优先读数据库。
  - 当前：存在 `DATABASE_URL` 时从 `daily_reports` 查询；无 `DATABASE_URL` 时保留 `data/reports/*.json` fallback。
  - 验收：
    - API 返回结构与当前测试契约一致。

- [ ] 增加事件详情接口。
  - 路由：`GET /api/public/events/{id}`。
  - 返回：事件摘要、推荐理由、AI 点评、主来源、相关来源、时间线、标签。
  - 验收：
    - 支持前端详情页直接消费。

## 9. Phase 5 - 任务调度与稳定性

目标：让系统可以每日自动运行，而不是手动执行脚本。

- [ ] 引入 Celery/Redis worker。
  - 任务：`crawl_source`、`prefilter_article`、`score_article`、`cluster_article`、`generate_daily_report`。
  - 验收：
    - 单 source 失败不会中断整批。
    - 失败任务可重试。

- [ ] 引入 scheduler。
  - 方案：Celery Beat 或 APScheduler。
  - 验收：
    - 每日固定时间自动生成日报。
    - 可手动触发重跑。

- [ ] 增加结构化运行记录。
  - 表：`pipeline_runs`。
  - 验收：
    - 每次运行记录 raw_count、processed_count、cluster_count、skipped_reasons、error。

- [ ] 增加告警。
  - 首选：Telegram Bot。
  - 告警条件：
    - 单 source 连续失败 >= 3 次。
    - AI 调用连续失败 >= 3 次。
    - 当天日报生成失败。
    - 当天精选数为 0。

## 10. Phase 6 - 前端 MVP

目标：在数据质量稳定后做可读网站，而不是提前做展示壳。

- [x] 创建 `apps/web`。
  - 技术栈：Next.js + React + Tailwind CSS。
  - 页面优先级：
    - `/latest`
    - `/daily`
    - `/daily/:date`
    - `/event/:id`
    - `/all`
    - `/search`
  - 本轮结果：
    - 创建 Next.js App Router 项目骨架。
    - 使用 Tailwind v4 `@tailwindcss/postcss` 和 `@import "tailwindcss"`。
    - `/` 直接跳转 `/latest`，避免落地页外壳。
    - `lib/api.ts` 通过 `AI_RADAR_API_BASE_URL` 读取 `/api/public/latest`。
    - `/latest` 已展示 Top 3、全部精选、分类筛选、摘要、推荐理由、下一步、来源和评分。
    - `/daily` 可跳转最新日报日期；`/daily/:date` 展示分类日报并支持复制 Markdown。
    - `/event/:id` 可从 latest payload 查找事件并展示摘要、推荐理由、主来源、相关来源、时间线和标签。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_web_app_structure -v
cd apps/web && npm run typecheck && npm run build
AI_RADAR_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1 --port 3000
```

- [x] 实现精选页初版。
  - 内容：今日主线、Top 3、最新精选、分类筛选。
  - 验收：
    - 桌面和手机都可读。
    - 首页不拥挤。
    - 推荐理由明显可见。
  - 当前完成：Top 3、全部精选、分类筛选、推荐理由、下一步和浏览器截图级验收已完成。
  - dev 验证：`/latest` 返回 200，HTML 包含“最新 AI 情报”“推荐理由”“下一步”；`/latest?category=model_release` 返回 200，HTML 包含“全部分类”，并按分类渲染 1 个 `<article>`。
  - 截图验证：桌面 `1440x1100` 全部分类页渲染 12 个 `<article>`，手机 `390x844` 分类页渲染 1 个 `<article>`，两者均无横向溢出。

- [x] 实现日报页。
  - 内容：按日期归档、分类展示、一键复制 Markdown。
  - 验收：
    - 可复制到 Notion、公众号草稿或 AI 助手。
  - 当前完成：`/daily` 根据 latest `report_date` 跳转，`/daily/2026-07-02` 可读取 public daily JSON，按分类展示 12 条，并提供复制 Markdown 按钮。
  - dev 验证：`/daily` 跳转到 `/daily/2026-07-02`；日期页 HTML 包含“复制 Markdown”“按日期归档”“为什么重要”“下一步”，并渲染 12 个 `<article>`。
  - 截图验证：桌面 `1440x1100` 和手机 `390x844` 日期页均无横向溢出，Playwright console error 为 0。

- [x] 实现事件详情页。
  - 内容：摘要、推荐理由、主来源、相关来源、时间线、标签、原文链接。
  - 验收：
    - 同一事件多来源关系清晰。
  - 当前完成：`/latest` 和 `/daily/:date` 事件标题链接到 `/event/:id`；详情页从 latest payload 查找事件。
  - dev 验证：`/event/c1` 返回 200，HTML 包含标题、主来源、相关来源、时间线、推荐理由和下一步。
  - 截图验证：桌面 `1440x900` 和手机 `390x844` 均无横向溢出，Playwright console error 为 0。

## 11. Phase 7 - RSS/Public API/MCP

目标：让数据可以被阅读器、开发者和 AI Agent 调用。

- [ ] 实现 RSS。
  - 路由：
    - `/feed/latest.xml`
    - `/feed/daily.xml`
    - `/feed/tag/{name}.xml`
    - `/feed/source/{id}.xml`
  - 验收：
    - 可被常见 RSS 阅读器订阅。

- [ ] 完整 Public API。
  - 路由：
    - `/api/public/events`
    - `/api/public/events/{id}`
    - `/api/public/search`
    - `/api/public/tags`
    - `/api/public/sources`
  - 验收：
    - 前端所有页面都只依赖 Public API。

- [ ] MCP Server。
  - 启动条件：
    - 数据连续运行 2 周。
    - 精选质量稳定。
    - Public API 完整。
    - 重复和低质量内容比例可接受。
  - 工具：
    - `get_latest_ai_news`
    - `get_daily_ai_report`
    - `search_ai_news`
    - `get_ai_event_detail`
    - `get_trending_ai_topics`
  - 约束：只读，不暴露后台写操作。

## 12. Phase 8 - 后台管理

目标：让系统长期运行时可人工修正来源、事件和评分，但不在数据闭环未稳定前提前做复杂后台。

- [ ] 单管理员登录。
  - 方式：JWT + `ADMIN_USERNAME`/`ADMIN_PASSWORD`。
  - 验收：Public API 与 Admin API 隔离。

- [ ] 来源管理。
  - 功能：启用/禁用、调整 tier、role、抓取频率、allowed_domains。

- [ ] 内容管理。
  - 功能：查看 raw/processed/published/discarded，重新处理，隐藏内容。

- [ ] 事件管理。
  - 功能：合并/拆分事件、调整主条、重新计算分数。

- [ ] 评分配置。
  - 功能：调整信源权重、类别阈值、时间衰减、热度加成。

- [ ] 日志和成本统计。
  - 功能：采集日志、AI 日志、聚类日志、日报日志、token 消耗。

## 13. 当前优先级

### 最高优先级

- [ ] 用真实公开源跑一次 `run_crawl_once.py`。
- [ ] 修正无效或不可抓取的 source URL。
- [ ] 用真实 raw 数据跑 fake pipeline，检查日报质量。
- [ ] 配置 OpenAI key 后跑小批量真实 AI pipeline。

### 中优先级

- [x] 安装 Docker Desktop。
- [x] 验证 Postgres + pgvector + Redis 基础服务。
- [x] 建立 SQLAlchemy session/repository 初版。
- [x] 把 pipeline CLI 写入接到数据库 repository。
- [x] 建立 Public API repository payload helper。
- [x] 把 FastAPI endpoint 查询接到数据库 repository。
- [x] 启动 API 服务并做 HTTP smoke 验证。
- [ ] 验证 API compose。
- [x] 创建 `apps/web` 前端 MVP 骨架。
- [x] 为 `/latest` 增加分类筛选。
- [x] 启动前后端 dev server，做 `/latest` 浏览器截图级视觉验收。
- [x] 实现 `/daily` 日报页。
- [x] 实现 `/event/:id` 事件详情页。
- [ ] 实现 `/all` 全量列表页。
- [ ] 实现 `/search` 搜索页。

### 暂缓

- [ ] 前端 MVP。
- [ ] 后台管理。
- [ ] Telegram 推送。
- [ ] MCP Server。

## 14. Docker 当前状态

Docker Desktop 已安装，当前已经用于：

- 验证 `infra/docker-compose.yml` 的 `postgres` 和 `redis` 服务。
- 运行 PostgreSQL + pgvector。
- 运行 Redis。
- 验证 `scripts/check_db_once.py`。

仍待完成：

- API 容器构建与 `/health` 验证。
- Celery worker。
- pgvector 相似查询。

当前限制：`docker compose -f infra/docker-compose.yml build api` 两次失败在 Docker Hub `python:3.12-slim` 元数据认证请求，错误为 connection reset；这属于外部网络问题，非代码编译失败。本轮已改用项目 `.venv` 安装 `requirements.txt` 完成 SQLAlchemy 测试。

## 15. 每次开发后的固定验收命令

基础测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

语法编译：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/hotai_pycache .venv/bin/python -m compileall apps/api scripts
```

本地 fake pipeline：

```bash
python3 scripts/seed_sources.py --output data/sources.json
python3 scripts/run_pipeline_once.py --limit 100 --fake-ai --date 2026-07-01
python3 scripts/build_daily_report.py --date 2026-07-01 --format markdown
```

Docker 验证命令，需先安装 Docker：

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d postgres redis
python3 scripts/check_db_once.py
```

API 容器验证命令，数据库基础服务通过后执行：

```bash
docker compose -f infra/docker-compose.yml up --build api
```

## 16. 完成定义

### 数据闭环完成

- [x] 本地 fake pipeline 可生成日报。
- [x] 评分、聚类、日报核心逻辑有测试。
- [ ] 真实源可稳定抓取。
- [ ] OpenAI 小批量真实评分通过。
- [ ] 连续 7 天日报质量可接受。

### V1 产品完成

- [ ] 每日采集 100-300 条。
- [ ] 每日精选 8-12 条高质量事件。
- [ ] 重复事件能折叠。
- [ ] 日报 Markdown 可读、可复制。
- [ ] Public API 可被前端消费。
- [ ] 系统连续运行 7 天无需人工修复核心链路。
