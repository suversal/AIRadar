# Suversal AI Radar 完整开发计划书

最后更新：2026-07-08
当前分支：`codex/ai-radar-data-loop`  
当前阶段：Phase 0 已完成，Phase 1 真实采集闭环进行中，Phase 2 真实 AI provider 接入进行中，Phase 6 前端 MVP 首版已完成

## 0. 总进度看板

| 阶段 | 状态 | 当前结论 | 下一步 |
| --- | --- | --- | --- |
| Phase 0 - 本地数据闭环骨架 | 已完成 | 代码骨架、核心模型、crawler 基础、AI 边界、评分、聚类、日报、CLI、测试、Docker 配置均已落地 | 进入真实源抓取验证 |
| Phase 1 - 真实采集与质量闭环 | 进行中 | 源清单 27 个（实测 27/27 可抓取，135 篇/轮）；Anthropic 用 sitemap 爬虫，机器之心 RSS 已下线故移除，venturebeat 修正 308 地址；抓取层：浏览器 UA、429/5xx 退避重试、同域 6 秒礼貌间隔、跨域并行（默认 8 并发）、sitemap 页面 lastmod 缓存、10 秒超时——整轮抓取 118s→25s | 继续人工检查日报质量并调源权重 |
| Phase 2 - OpenAI/Kimi/DeepSeek 接入、AI 总结与真实评分 | 进行中 | Kimi/Moonshot 和 DeepSeek chat provider 已接入环境变量；DeepSeek 20 并发 API smoke 和 20 条日报生成已跑通；OpenAI 边界保留；真实 key 不写入仓库 | 继续观察真实日报质量，并根据成本/稳定性调整默认并发 |
| Phase 3 - PostgreSQL + pgvector 持久化 | 基本完成 | 全部 8 张表已投入使用：raw/processed/event_clusters/关联表/daily_reports/pipeline_runs 均由 pipeline 持久化；事件 ID 改为内容哈希（跨 run 稳定）；pipeline 按 url_hash 增量复用已缓存的 AI 评分与译文（实测 74s→17s，仅新文章产生 AI 调用） | 补 Alembic 迁移；article_embeddings 待接入真实 embedding API 后启用 pgvector 相似查询 |
| Phase 4 - API 与日报服务化 | 进行中 | latest/daily/events/topics/period 全套公开 API 就绪；周期报告已期次化：period_reports 表持久化 AI 主线综述（每次日报刷新自动重生成当周/当月），/reports/weekly/2026-W28 可按 ISO 周号寻址，daily/weekly/monthly 均有归档端点 | 等 API compose 网络问题恢复后补容器验证 |
| Phase 5 - 任务调度与稳定性 | 进行中 | 轻量调度已就绪：`scripts/run_scheduled_refresh.sh`（带锁防重入、日志落 data/logs/）+ launchd 配置 `infra/launchd/`，每 2 小时抓取+处理；安装命令见 README；Celery/Redis 队列后置 | 用户确认安装 launchd agent；观察若干天后再评估是否需要 Celery |
| Phase 6 - 前端 MVP | 已完成（v1 收尾完成） | 分类统一为 全部/模型/产品/行业/论文/技巧 六类（后端 8 类评分→展示映射，AI prompt 已约束枚举）；主题页上线（公司与模型/技术方向/内容形态 三组，点击进入 `/all?topic=` 筛选流）；视觉重设计为"琥珀信号"体系（AI·RADAR 品牌、暖炭黑+琥珀金 token、等宽仪表读数、雷达状态条、共享 Sidebar）；Agent接入/关于/更新日志/反馈 四个静态页上线；全部 15 条路由 + 404/API宕机降级走查通过 | 收藏（v2）；移动端截图细调 |
| Phase 7 - RSS/Public API/MCP | 未开始 | RSS/Public API 完整版和 MCP 暂缓 | 等 API 和数据质量稳定后启动 |
| Phase 8 - 后台管理 | 前期完成 | Token 认证管理后台上线（/admin，ADMIN_TOKEN 环境变量 + HttpOnly cookie）：仪表盘（信源健康网格/运行台账/手动刷新——刷新入口已从公开页移入后台）、信源管理（启停/编辑/新增/试抓，DB 为配置事实源）、内容修正（隐藏/恢复/改标题分类标签，隐藏事件公开侧即时 404）| 后期：阈值与 prompt 调参、故障告警、编辑工作流、审计日志、多管理员 |

## 0.1 已完成任务索引

以下任务已经完成，后文对应条目也已标为 `[x]`：

- [x] 已完成：后端优先 Monorepo 骨架。
- [x] 已完成：Python 项目配置和依赖声明。
- [x] 已完成：`.env.example` 环境变量模板。
- [x] 已完成：核心领域模型。
- [x] 已完成：默认信源清单。
- [x] 已完成：IT之家 RSS 信源接入。
- [x] 已完成：URL/title 标准化和 hash 去重基础。
- [x] 已完成：RSS、HN、GitHub crawler 基础。
- [x] 已完成：RSS HTML 原文段落、图片 URL 和图文块解析。
- [x] 已完成：AI provider 边界、fake provider、OpenAI 调用边界。
- [x] 已完成：Kimi/Moonshot chat provider 环境变量接入，支持真实中文总结和评分。
- [x] 已完成：DeepSeek chat provider 环境变量接入，默认模型 `deepseek-v4-flash`。
- [x] 已完成：pipeline AI 预筛/评分/embedding 可配置并发，支持 DeepSeek 高并发。
- [x] 已完成：fake AI 总结字段链路，覆盖中文标题、一句话摘要、核心摘要、推荐理由和下一步动作。
- [x] 已完成：评分公式、阈值和精选判断。
- [x] 已完成：事件聚类基础和主条选择。
- [x] 已完成：Markdown/JSON 日报生成。
- [x] 已完成：日报 JSON 暴露主文章原文段落、图片和阅读原文 URL。
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
- [x] 已完成：`/latest` AIHOT 风格精选首页首版，侧栏占位菜单已记录。
- [x] 已完成：`/latest` 浏览器截图级视觉验收。
- [x] 已完成：`/daily` 和 `/daily/:date` 日报页。
- [x] 已完成：`/weekly` 周报页和 `/monthly` 月报页。
- [x] 已完成：`/event/:id` 事件详情页。
- [x] 已完成：`/event/:id` 详情页改为文章阅读布局，仅保留推荐理由、AI 摘要、原文、标签和阅读原文按钮。
- [x] 已完成：`/all` AIHOT 风格全部 AI 动态页首版。
- [x] 已完成：`/search` 搜索页。
- [x] 已完成：`/latest` 点击刷新最新日报和完整成果按钮。
- [x] 已完成：README、实施说明和本开发计划书。
- [x] 已完成：本地 fake raw fixture。
- [x] 已完成：本地样例日报生成，当前样例为 12 条精选。
- [x] 已完成：真实 crawl pass 逐源报告。
- [x] 已完成：arXiv/Reddit Atom 日期、作者、链接解析兼容。
- [x] 已完成：GitHub Trending parser 不再误抓 `/trending/...` 伪 repo。
- [x] 已完成：HN 关键词边界过滤，不再把 `Aims` 这类子串误当作 `AI`。
- [x] 已完成：真实抓取结果跑通 fake AI pipeline。
- [x] 已完成：65 个单元测试全部通过。

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

当前测试结果：65 个测试通过。

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
  - 验收：包含 `DATABASE_URL`、`REDIS_URL`、`OPENAI_API_KEY`、`KIMI_API_KEY`、`DEEPSEEK_API_KEY`、`GITHUB_TOKEN`、模型和成本保护配置。

- [x] 建立核心领域模型。
  - 文件：`apps/api/app/models/domain.py`。
  - 覆盖对象：`Source`、`RawArticle`、`ScoreDimensions`、`ProcessedArticle`、`EventCluster`、`DailyReport`、`PipelineResult`。
  - 验收：测试可直接构造领域对象并运行评分、聚类、日报逻辑。

- [x] 实现默认信源清单。
  - 文件：`apps/api/app/data/default_sources.py`。
  - 已覆盖：OpenAI、Anthropic、DeepMind、Hugging Face、HN、arXiv、GitHub Trending、Reddit LocalLLaMA、Reddit MachineLearning、机器之心、量子位、IT之家。
  - 验收：`test_default_sources_cover_required_first_batch` 通过。

- [x] 实现 URL/title 标准化和去重基础。
  - 文件：`apps/api/app/crawlers/base.py`。
  - 能力：去掉 `utm_*`、`fbclid`、`gclid` 等跟踪参数，生成稳定 hash。
  - 验收：`test_normalize_article_removes_tracking_and_hashes_url_and_title` 通过。

- [x] 实现基础 crawler。
  - 文件：`apps/api/app/crawlers/rss.py`、`article_content.py`、`hn.py`、`github.py`、`registry.py`。
  - 当前能力：RSS/Atom 解析、RSS HTML 原文段落和图片 URL 解析、HN Algolia API 解析、GitHub Trending HTML 轻量解析、按 source type 选择 crawler。
  - 验收：RSS fixture 测试通过；真实网络抓取尚未作为自动测试启用。

- [x] 实现 AI provider 边界。
  - 文件：`apps/api/app/services/ai_service.py`。
  - 已完成：`FakeAIProvider`、OpenAI embeddings/chat 调用边界、Kimi/Moonshot chat provider、DeepSeek chat provider、预筛 JSON 解析、评分/总结 JSON 解析、分数 clamp。
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
  - 已完成：按分类输出日报，每条包含标题、摘要、为什么重要、下一步、来源、标签；JSON payload 额外携带主文章 `original_url`、`original_paragraphs`、`original_images`、`original_blocks`，供详情页显示原文。
  - 验收：日报模板测试通过。

- [x] 实现本地 JSON 存储。
  - 文件：`apps/api/app/storage/json_store.py`。
  - 用途：Phase 0 在没有 Postgres 时保存 sources、raw articles、processed articles、clusters、daily reports。
  - 验收：sources JSON round-trip 测试通过。

- [x] 实现 pipeline runner。
  - 文件：`apps/api/app/pipeline/runner.py`。
  - 流程：source raw items -> normalize -> dedupe -> fake/OpenAI prefilter -> score -> embed -> cluster -> report。
  - 并发：`ai_concurrency` 支持候选文章并发 prefilter/score/embed；CLI 参数为 `--ai-concurrency`，刷新服务读取 `AI_PIPELINE_CONCURRENCY`。
  - 验收：`test_pipeline_skips_over_limit_and_generates_daily_report`、`test_pipeline_can_process_ai_candidates_concurrently` 通过。

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

检查时间：2026-07-07
检查命令：

```bash
.venv/bin/python scripts/seed_sources.py --output data/sources.json
.venv/bin/python scripts/run_crawl_once.py --limit 36 --output data/crawl_checks/2026-07-07-ithome-raw.json --report data/crawl_checks/2026-07-07-ithome-crawl-report.json
.venv/bin/python scripts/run_pipeline_once.py --sources data/sources.json --raw data/crawl_checks/2026-07-07-ithome-raw.json --output-dir data/crawl_checks/2026-07-07-ithome-pipeline --limit 36 --top-n 30 --fake-ai --date 2026-07-07
```

输出文件：`data/crawl_checks/2026-07-07-ithome-raw.json`。

结论：当前数据源获取不是全部正常，但 IT之家 RSS 已接入并验证可用。联网环境下抓到 24 条真实文章，来自 8 个 source；4 个 source 失败。IT之家本轮抓到 3 条，其中样例文章包含 4-11 个原文段落、1-3 张图片和有序图文块；fake AI pipeline 生成的日报 JSON 已验证可携带 `original_url`、`original_paragraphs`、`original_images`、`original_blocks`。

成功 source：

- [x] `openai_blog`：成功抓取 3 条。
- [x] `huggingface_blog`：成功抓取 3 条。
- [x] `hacker_news`：成功抓取 3 条，已增加关键词边界过滤，本轮未再出现 `Aims/Taiwan` 误匹配。
- [x] `arxiv_ai`：成功抓取 3 条，已修复 Atom ISO 日期和作者解析。
- [x] `github_trending_ai`：成功抓取 3 条，已修复 `/trending/...` 伪 repo 误识别。
- [x] `reddit_localllama`：成功抓取 3 条，已修复 Atom alternate link 和作者解析。
- [x] `qbitai`：成功抓取 3 条。
- [x] `ithome`：成功抓取 3 条，RSS description 内原文段落、图片 URL 和图文顺序可解析。

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
5. 人工检查真实日报质量，继续压低 Reddit/HN/泛科技内容比例，并决定 IT之家是否需要只保留 AI 频道或继续全站 RSS。

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

## 6. Phase 2 - OpenAI/Kimi/DeepSeek 接入、AI 总结与真实评分

目标：使用真实 OpenAI、Kimi/Moonshot 或 DeepSeek API 替换 fake provider，验证预筛、AI 中文总结、推荐理由、六维评分和 embedding/聚类链路的真实质量。

当前说明：

- Phase 0 已经打通 AI 总结字段的端到端链路，但使用的是 `FakeAIProvider`，只适合本地干跑和测试。
- 真实的“AI 总结功能”从 Phase 2 开始验收：每条精选事件由真实模型生成中文标题、一句话摘要、核心摘要、推荐理由和下一步动作。
- 当前已接入 Kimi/Moonshot 和 DeepSeek OpenAI-compatible chat endpoint，用于预筛、中文总结和六维评分；Kimi/DeepSeek embedding 暂时使用本地 deterministic fallback，保证没有 embedding API 时聚类链路不阻塞。
- 日报 Markdown 当前展示中文标题、一句话摘要、核心总结、推荐理由和下一步动作；JSON 同时保留 `summary` 核心摘要，供后续 API/前端复用。

- [x] 接入 Kimi/Moonshot provider。
  - 涉及文件：`apps/api/app/services/ai_service.py`、`scripts/run_pipeline_once.py`、`apps/api/app/services/refresh_service.py`。
  - 当前完成：
    - 支持 `AI_PROVIDER=kimi`。
    - 支持 `KIMI_API_KEY` 或 `MOONSHOT_API_KEY`。
    - 支持 `KIMI_MODEL` 和 `KIMI_BASE_URL`；默认 endpoint 为官方文档的 `https://api.moonshot.cn/v1`。
    - `/latest` 点击刷新和 CLI 共用同一个 provider 工厂。
    - 主机侧 API/CLI 会读取本地 `.env` 中缺失的环境变量，已导出的变量优先级更高。
  - 注意：真实 API key 只放本地 `.env`，不得写入仓库、文档或提交。

- [x] 接入 DeepSeek provider。
  - 涉及文件：`apps/api/app/services/ai_service.py`、`.env.example`。
  - 当前完成：
    - 支持 `AI_PROVIDER=deepseek`。
    - 支持 `DEEPSEEK_API_KEY`。
    - 支持 `DEEPSEEK_MODEL` 和 `DEEPSEEK_BASE_URL`；默认模型 `deepseek-v4-flash`，默认 endpoint `https://api.deepseek.com`。
    - 支持 `DEEPSEEK_USER_ID` 做请求隔离，支持 `DEEPSEEK_MAX_TOKENS` 降低 JSON 截断风险。
    - DeepSeek `deepseek-v4-flash` 官方并发限制为账号级 2500；当前 pipeline 已支持通过 `AI_PIPELINE_CONCURRENCY` 并发执行 AI 预筛、评分和 embedding。
  - 注意：真实 API key 只放本地 `.env`，不得写入仓库、文档或提交。

- [x] 配置本地 `.env`。
  - 文件：从 `.env.example` 复制为 `.env`。
  - 真实 AI 三选一：
    - OpenAI：`AI_PROVIDER=openai` + `OPENAI_API_KEY`。
    - Kimi：`AI_PROVIDER=kimi` + `KIMI_API_KEY` 或 `MOONSHOT_API_KEY`。
    - DeepSeek：`AI_PROVIDER=deepseek` + `DEEPSEEK_API_KEY`。
  - 可选：`GITHUB_TOKEN`。

- [ ] 使用 Kimi 跑小批量 pipeline。
  - 命令：

```bash
AI_PROVIDER=kimi KIMI_API_KEY=<local-only> python3 scripts/run_pipeline_once.py --limit 20 --date 2026-07-07
```

  - 验收：
    - 预筛 JSON 能稳定解析。
    - 评分 JSON 能稳定解析。
    - 日报中文内容明显优于 fake provider。
    - Kimi embedding fallback 不影响聚类流程产出。

- [x] 使用 DeepSeek 跑小批量 pipeline。
  - 命令：

```bash
AI_PROVIDER=deepseek DEEPSEEK_API_KEY=<local-only> python3 scripts/run_pipeline_once.py --limit 20 --date 2026-07-07
```

  - 验收：
    - 预筛 JSON 能稳定解析。
    - 评分 JSON 能稳定解析。
    - 日报中文内容明显优于 fake provider。
    - DeepSeek embedding fallback 不影响聚类流程产出。
  - 当前完成：
    - 20 个 DeepSeek 并发预筛请求全部成功，错误数 0，总耗时约 2.7 秒。
    - `--limit 20 --top-n 20 --ai-concurrency 20` 真实 pipeline 已通过；当前 `/api/public/latest` 返回 20 条日报 items。
    - 新增 `--skip-prefilter` 用于一次性审查运行：跳过 AI 相关预筛，100 个候选全部评分并进入日报，便于检查评分分布和低分样本。

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

- [x] 完成数据库迁移策略（2026-07-11 起 Alembic 是 schema 唯一来源）。
  - `apps/api/alembic/` 已接入，`env.py` 读取 `DATABASE_URL`、target_metadata 指向 `app.db.models.Base.metadata`。
  - 基线迁移 `254438b7a6b4_baseline_schema.py` 已回填为 Alembic 接入时点的完整历史 DDL：全新空库只需 `alembic upgrade head` 即可建出全部表，不再需要 `stamp` 协议。历史库已 stamp 到基线之后，该 DDL 在其上永不执行，因此基线内容必须冻结在历史形态（如 `article_embeddings` 在基线仍是 vector(1536)、无 source_hash，由后续 migration 重塑）。
  - `infra/postgres/init.sql` 只创建 pgvector extension（需要超级用户、由 docker-entrypoint-initdb.d 执行）；所有业务表都在 migration 里。
  - 验收（2026-07-11 已执行）：scratch pgvector 容器空库 `alembic upgrade head` 后 `pg_dump --schema-only` 与生产库逐行 diff 为零差异（仅 pg_dump 随机 `\restrict` 令牌行不同）。

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
    - `/latest` 已重构为 AIHOT 风格精选首页：侧栏、精选菜单、分类标签、当前热点、日期折叠信息流、摘要、推荐理由、来源和评分。
    - `/daily` 已重构为 AIHOT 风格日报页：报告模式切换、今日看点、统计卡、分栏目正文和复制 Markdown；`/daily/:date` 保留日期详情兼容。
    - `/weekly` 和 `/monthly` 已实现 AIHOT 风格周期报告页：本期主线、统计卡、本期看点和主题章节。
    - `/event/:id` 可从 latest payload 查找事件并展示推荐理由、AI 摘要、原文正文、原文图片、标签和阅读原文按钮。
    - `/all` 已重构为 AIHOT 风格全部 AI 动态页：侧栏高亮、来源类型筛选、分类筛选、内联搜索、日期折叠时间线、摘要、图片、标签、推荐理由、评分和事件详情链接。
    - `/search` 可按关键词过滤 latest payload 中的标题、标签、来源、摘要和推荐字段。
    - `/latest` 侧栏提供“刷新最新日报”和“刷新完整成果”按钮，点击后通过 Next route 启动 FastAPI 后台刷新任务，执行 crawl + AI pipeline + DB 写入，并通过轮询刷新当前页面。
  - 验证：

```bash
.venv/bin/python -m unittest tests.test_web_app_structure -v
cd apps/web && npm run typecheck && npm run build
AI_RADAR_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1 --port 3000
```

- [x] 实现精选页初版。
  - 内容：AIHOT 风格侧栏、精选入口、当前热点 Top 3、按日期折叠的信息流、分类筛选。
  - 验收：
    - 桌面和手机都可读。
    - 首页不拥挤。
    - 推荐理由明显可见。
  - 当前完成：`/latest` 已参考 AIHOT 样式重构为精选首页首版；左侧菜单“全部 AI 动态”已链接到 `/all`，“AI 日报”已链接到 `/daily`；其余“主题、收藏、Agent 接入、关于、更新日志、反馈”继续作为后续占位。
  - 本轮不放搜索框；搜索能力仍保留在独立 `/search` 页面，避免首页第一版变复杂。
  - dev 验证：`/latest` 返回 200，HTML 包含“AIHOT”“精选”“当前热点”“推荐理由”；`/latest?category=model_release` 返回 200，并按分类渲染 `<article>`。
  - 截图验证：桌面 `1440x1100` 和手机 `390x844` 页面需在本轮最终验收后更新记录。

- [x] 实现 AIHOT 风格日报页。
  - 内容：AIHOT 报告壳层、日报/周报/月报切换、今日看点、统计卡、分类正文、一键复制 Markdown。
  - 验收：
    - 可复制到 Notion、公众号草稿或 AI 助手。
  - 当前完成：`/daily` 默认读取最新日报并直接展示 AIHOT 风格日报；`/daily/:date` 保留旧日期详情页和复制 Markdown 兼容。
  - dev 验证：`/daily` 结构测试包含“AIHOT 日报”“今日看点”“ReportShell”“reportModeTabs”“buildDailyDigest”；日期页仍包含“复制 Markdown”“为什么重要”“下一步”。
  - 截图验证：待本轮浏览器视觉复核。

- [x] 实现 AIHOT 风格周报/月报页。
  - 内容：`/weekly`、`/monthly`，共用报告壳层，包含本期主线、统计卡、本期看点、主题章节和侧栏期次列表。
  - 验收：
    - 周报和月报可从 AI 日报模式切换进入。
    - 无专用后端 API 时可基于当前 latest payload 聚合生成可读版本。
  - 当前完成：`/weekly` 和 `/monthly` 已基于 current latest payload 自动聚合，后续需要接入真正周期聚合 API 和历史归档。
  - dev 验证：结构测试包含“AIHOT 周报”“AIHOT 月报”“本期主线”“本期看点”“本期主题”“独立事件”“条精选”“阅读本页”。

- [x] 实现事件详情页。
  - 内容：推荐理由、AI 摘要、原文正文、原文图片、标签、阅读原文按钮。
  - 验收：
    - 详情页不再重复拼接摘要/推荐理由/动作建议。
    - 有结构化原文时按原文图文块展示，没有原文时降级显示摘要。
  - 当前完成：`/latest` 和 `/daily/:date` 事件标题链接到 `/event/:id`；详情页从 latest payload 查找事件，并消费 `original_blocks`、`original_paragraphs`、`original_images`；阅读文章时保留 AIHOT 左侧菜单栏，顶部不再显示“返回最新情报”。
  - dev 验证：`/event/:id` 结构测试通过，HTML 源码不再包含“报告正文”“时间线”“下一步”“返回最新情报”，包含“推荐理由”“AI 摘要”“原文”“阅读原文”和 AIHOT 主导航。
  - 截图验证：待下一轮浏览器视觉复核。

- [x] 为英文来源详情页增加原文/译文切换。
  - 内容：pipeline 只为最终日报入选的英文主文章生成 `translated_paragraphs` 和有序 `translated_blocks`；详情页有译文时默认展示“AI 翻译 · 中文”，按钮可切换“显示原文”/“显示译文”。
  - 验收：
    - 中文来源不触发翻译。
    - 未入选候选不触发翻译，避免扩大模型成本。
    - 有图片的原文块在译文模式中保留图片位置，便于对照阅读。
    - 没有译文字段时详情页保持原文展示，不显示空切换按钮。
  - 当前完成：`apps/api/app/pipeline/runner.py` 注入选中英文主文章译文 metadata；`daily_report_service.py` 输出译文字段；`apps/web/app/event/[id]/article-reading-toggle.tsx` 提供原文/译文切换。
  - dev 验证：pipeline 测试确认只翻译选中的英文文章；report/API 测试确认 JSON 契约包含 `source_language`、`translated_paragraphs`、`translated_blocks`；web 结构测试确认详情页使用切换组件。

- [x] 为 GitHub 开源项目详情页补抓 README 原文。
  - 内容：pipeline 在最终日报选中 GitHub Trending 主文章后，通过 GitHub README API 获取 README，优先使用根目录中文 README，并写入 `original_markdown`、`original_paragraphs`、`original_blocks`、`original_images`。
  - 验收：
    - 只对最终入选的 GitHub Trending 项目抓 README。
    - 未入选 GitHub 候选不抓 README。
    - 非 GitHub 来源不触发 README 抓取。
    - README 失败或限流时保留原 Trending 短描述，不阻塞日报生成。
    - 根目录存在 `README_zh.md`、`README_CN.md` 等中文 README 时优先使用中文版本。
    - 中文 README 不触发 AI 翻译；英文默认 README 保持原文/译文对照。
    - README 相对图片转换为 raw.githubusercontent.com 绝对 URL。
    - README 相对文档链接转换为 GitHub blob 绝对 URL。
    - 详情页优先渲染 `original_markdown`，没有该字段的旧日报继续使用 blocks 降级展示。
  - 当前完成：`apps/api/app/crawlers/github_readme.py` 负责 repo 解析、中文 README 优先选择、README API 请求、base64 解码、相对 URL 改写、80KB Markdown 上限和 Markdown 转图文块；`apps/api/app/pipeline/runner.py` 在翻译前注入 README 原文，并跳过中文 README 翻译；`apps/web/app/event/[id]/article-reading-toggle.tsx` 使用 Markdown/GFM 渲染原文。
  - dev 验证：crawler 测试覆盖中文 README 优先、失败回退、README helper、Markdown 字段、URL 改写和长度上限；pipeline/report 测试确认 public JSON 透传 `original_markdown` 和 README 诊断字段，且中文 README 不触发翻译；web 结构测试和 TypeScript 检查确认详情页使用 Markdown 渲染并保留降级。

- [x] 实现全部 AI 动态页。
  - 内容：AIHOT 风格侧栏、来源类型筛选、分类筛选、内联搜索、按日期折叠的信息流、摘要、图片、标签、评分、来源、推荐理由和详情链接。
  - 验收：
    - 可快速扫描当前可读 AI 动态。
    - 可按来源类型、分类和关键词缩小列表。
    - 日期分组可折叠。
  - 当前完成：`/all` 基于 latest payload 渲染当前可读事件；这是前端首版，真正包含未入选候选和 raw/processed 全量动态的 API 仍待后端扩展。
  - dev 验证：`/all` 结构测试包含“全部 AI 动态”“AI 相关资讯全量信息流”“一手信源”“资讯”“推文”“推荐理由”“评分”“来源”和 `<details>`。
  - 截图验证：待本轮浏览器视觉复核。

- [x] 实现搜索页。
  - 内容：关键词输入、搜索结果、评分、来源、标签、详情链接。
  - 验收：
    - 能按标题、标签、来源、摘要和推荐字段搜索当前可读事件。
  - 当前完成：`/search?q=OpenAI` 基于 latest payload 返回 1 条匹配事件。
  - dev 验证：`/search?q=OpenAI` 返回 200，HTML 包含“搜索结果”和事件详情链接。
  - 截图验证：桌面 `1440x900` 和手机 `390x844` 均无横向溢出，Playwright console error 为 0。

- [x] 实现点击刷新最新日报和完整成果。
  - 内容：`/latest` 侧栏按钮、Next 转发 route、FastAPI 本地刷新 endpoint。
  - 验收：
    - 点击后抓取最新内容，按环境变量选择 fake/Kimi/DeepSeek/OpenAI provider 运行 pipeline，写入 `daily_reports`，并刷新页面。
  - 当前完成：
    - `POST /api/admin/refresh-latest` 执行同步本地刷新，支持 `limit` 和 `top_n` query 参数。
    - `POST /api/admin/refresh-latest-async` 启动后台刷新任务；`GET /api/admin/refresh-jobs/:job_id` 查询任务状态。
    - `POST /api/refresh-latest` 供前端按钮调用并转发 query 参数；前端轮询 job 状态，避免 Kimi 慢请求触发 Next.js 单请求超时。
    - 普通刷新请求 `top_n=12`，完整成果请求 `top_n=30`。
    - AI 并发由 `AI_PIPELINE_CONCURRENCY` 控制；本地 DeepSeek 测试使用 20 并发。
    - `updated_at` 已改为报告生成时间；`latest_published_at` 保留最新来源发布时间，避免同一天刷新时看起来时间不变。
    - 真实模型评分过严时，日报会用最高分候选补足剩余展示位，同时保留 `selected_count` 表示真正过阈值数量。
  - 注意：没有真实 AI key 时自动使用 `FakeAIProvider`；配置 `AI_PROVIDER=deepseek`/`kimi` 和本地 key 后，点击刷新会用对应 provider 生成预筛、中文摘要、推荐理由和评分。API key 不写入仓库。

- [x] 记录 AIHOT 风格首页的占位范围。
  - 已实现：`/latest` 作为“精选”首页；`/all` 作为“全部 AI 动态”页面首版。
  - 占位待做：`主题`、`收藏`、`Agent 接入`、`关于`、`更新日志`、`反馈`。
  - 设计约束：本轮不在首页放搜索；分类使用顶部标签；主列表按日期折叠，优先展示少而精的判断型内容。

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

- [x] 用真实公开源跑一次 `run_crawl_once.py`。
- [ ] 修正无效或不可抓取的 source URL。
- [x] 用真实 raw 数据跑 fake pipeline，检查日报质量。
- [x] 配置 DeepSeek key 后跑小批量真实 AI pipeline。

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
- [x] 实现 `/weekly` 周报页和 `/monthly` 月报页。
- [x] 实现 `/event/:id` 事件详情页。
- [x] 优化 `/event/:id` 为原文阅读布局并显示原文图片。
- [x] 优化 `/event/:id` 阅读布局，保留左侧菜单并移除顶部返回按钮。
- [x] 为英文来源 `/event/:id` 增加原文/AI 翻译切换。
- [x] 为 GitHub 开源项目 `/event/:id` 增加 README 原文补抓。
- [x] 实现 `/all` 全量列表页。
- [x] 重构 `/all` 为 AIHOT 风格全部 AI 动态页。
- [x] 实现 `/search` 搜索页。
- [x] 实现 `/latest` 点击刷新最新日报和完整成果。
- [x] 将 `/latest` 重构为 AIHOT 风格精选首页首版。

### 暂缓

- [x] 前端 MVP 首版。
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
- [x] DeepSeek 小批量真实评分通过。
- [ ] 连续 7 天日报质量可接受。

### V1 产品完成

- [ ] 每日采集 100-300 条。
- [ ] 每日精选 8-12 条高质量事件。
- [ ] 重复事件能折叠。
- [ ] 日报 Markdown 可读、可复制。
- [ ] Public API 可被前端消费。
- [ ] 系统连续运行 7 天无需人工修复核心链路。
