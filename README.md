# AI·RADAR

> 为创作者和开发者准备的中文 AI 情报雷达：持续监听高信噪比信源，用 AI 完成筛选、评分、聚类与去重，把分散报道整理成值得阅读的事件、热点和日报。

[在线体验](https://radar.suversal.com/latest) · [Agent 接入](https://radar.suversal.com/agent) · [REST API](https://radar.suversal.com/agent/api) · [OpenAPI 3.1](https://radar.suversal.com/openapi-v1.json) · [RSS](https://radar.suversal.com/feed.xml) · [llms.txt](https://radar.suversal.com/llms.txt)

[![AI·RADAR 页面预览](https://radar.suversal.com/opengraph-image)](https://radar.suversal.com/latest)

## 为什么做 AI·RADAR

AI 资讯的问题不是“没有内容”，而是同一事件被反复转载、信息密度差异巨大，真正重要的变化很容易淹没在时间流里。

AI·RADAR 不追求收录越多越好，而是把信息处理成更适合判断和复用的结构：

- **多源聚合**：接入 RSS、Atom、RSSHub，并可按配置整合 SourcePilot 与 X 数据。
- **AI 筛选与评分**：先判断内容是否与 AI 相关，再按类别价值、证据质量和影响范围评分。
- **事件聚类与去重**：把多家媒体对同一件事的报道折叠成一个事件，同时保留来源关系与时间线。
- **编辑化输出**：提供精选、全部动态、当前热点、主题档案以及日／周／月报。
- **保留溯源**：摘要、推荐理由和译文都指向站内事件页与第三方原文，方便回查证据。
- **机器可读**：通过 Agent Skill、远程 MCP、RSS 和 REST API 把数据接入 Agent 或自动化流程。

## 你可以直接使用什么

| 入口 | 适合场景 | 地址 |
| --- | --- | --- |
| 精选 | 浏览近期高价值 AI 动态 | [radar.suversal.com/latest](https://radar.suversal.com/latest) |
| 当前热点 | 判断最近两天哪些事件正在升温 | [精选页右侧热点榜](https://radar.suversal.com/latest) |
| 日／周／月报 | 按时间尺度阅读主线和分类概述 | [日报](https://radar.suversal.com/daily) · [周报](https://radar.suversal.com/weekly) · [月报](https://radar.suversal.com/monthly) |
| 主题档案 | 持续跟踪公司、模型和技术方向 | [radar.suversal.com/topics](https://radar.suversal.com/topics) |
| Agent Skill | 安装后直接用自然语言提问 | [接入说明](https://radar.suversal.com/agent) |
| MCP Server | 给支持远程 MCP 的客户端增加 6 个只读工具 | `https://radar.suversal.com/api/mcp` |
| RSS | 阅读器、n8n、Zapier 等订阅与自动化 | [精选 RSS](https://radar.suversal.com/feed.xml) |
| REST API | 自建应用、脚本或数据分析 | [API 参考](https://radar.suversal.com/agent/api) |

## Agent 与自动化接入

所有公开接口均为匿名只读，不需要 API Key。

### Agent Skill

把下面这段话发给支持 Agent Skills 的工具：

```text
请安装 AI·RADAR Skill：https://radar.suversal.com/ai-radar-skill/SKILL.md
安装器在 https://radar.suversal.com/ai-radar-skill/install.sh
请先读一遍并说明它会修改哪些目录，再执行。装完告诉我是否需要开启新会话。
```

当前完成端到端验证的路径是 Claude Code。Skill、安装器和 SHA-256 校验值均可在执行前审阅。

安装后可以直接问：

```text
过去 24 小时最值得关注的 5 条 AI 动态是什么？
最近 7 天有哪些 Agent 相关消息？按重要性排序并给出原始来源。
这个事件有哪些媒体报道？它们的时间线和共同事实是什么？
今天的 AI 日报主线是什么？哪些结论还需要回到原文核验？
```

### MCP Server

支持 Streamable HTTP 的客户端只需要一个地址：

```text
https://radar.suversal.com/api/mcp
```

Claude Code 示例：

```bash
claude mcp add --transport http ai-radar 'https://radar.suversal.com/api/mcp'
```

连接后提供 `radar_get_latest`、`radar_search`、`radar_get_hot_topics`、`radar_get_story`、`radar_get_daily` 和 `radar_get_topics` 六个工具。

### REST API

```bash
curl 'https://radar.suversal.com/api/v1/items?window=24h&limit=5'
```

REST v1 支持 CORS、ETag 条件请求和 RFC 9457 Problem Details。参数、枚举、字段与错误码以 [OpenAPI 3.1](https://radar.suversal.com/openapi-v1.json) 为准。

### RSS

```text
精选       https://radar.suversal.com/feed.xml
全部动态   https://radar.suversal.com/feed/all.xml
日报       https://radar.suversal.com/feed/daily.xml
分类       https://radar.suversal.com/feed/category/{model|product|industry|research|tutorial}.xml
```

## 系统如何工作

```mermaid
flowchart LR
    A[RSS / Atom / RSSHub] --> C[采集与正文提取]
    B[SourcePilot / X 可选] --> C
    C --> D[AI 预筛选与分类评分]
    D --> E[向量化与事件聚类]
    E --> F[(PostgreSQL + pgvector)]
    F --> G[FastAPI]
    G --> H[Next.js Web]
    G --> I[管理后台]
    H --> J[精选 / 热点 / 报告 / 主题]
    H --> K[Skill / MCP / RSS / REST]
```

核心流水线为：

```text
抓取 → 时间过滤 → 原始入库 → AI 预筛选 → 正文提取 → 评分与分类
    → 向量化 → 事件聚类 → 持久化 → 日／周／月报更新
```

## 技术栈

- **后端与流水线**：Python、FastAPI、SQLAlchemy、Alembic
- **数据存储**：PostgreSQL、pgvector、Redis
- **采集与解析**：HTTPX、feedparser、Beautiful Soup
- **AI Provider**：Qwen、OpenAI、Kimi、DeepSeek 兼容接口，以及无密钥的 `FakeAIProvider`
- **前端**：Next.js 16、React 19、TypeScript、Tailwind CSS
- **运行与网关**：Docker Compose、Nginx
- **访问统计（可选）**：自托管 Umami

## 本地开发

下面的命令面向 macOS／Linux shell。建议准备：

- Python 3.9+
- Node.js 22+
- Docker 与 Docker Compose

### 1. 安装依赖

```bash
git clone https://github.com/suversal/AIRadar.git
cd AIRadar

cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cd apps/web
npm ci
cd ../..
```

没有配置真实模型密钥时，可以使用 `FakeAIProvider` 跑通开发链路。

### 2. 启动数据库并迁移

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis

export RADAR_DB_URL='postgresql+psycopg://radar:radar@localhost:5432/radar'
(cd apps/api && DATABASE_URL="$RADAR_DB_URL" ../../.venv/bin/alembic upgrade head)
```

### 3. 准备一批本地数据（可选）

抓取步骤会访问各公开信源：

```bash
.venv/bin/python scripts/seed_sources.py
DATABASE_URL="$RADAR_DB_URL" .venv/bin/python scripts/run_crawl_once.py
.venv/bin/python scripts/run_pipeline_once.py \
  --limit 50 \
  --fake-ai \
  --persist-db \
  --database-url "$RADAR_DB_URL"
```

运行产物、抓取报告和正文缓存写入 `data/`，默认不进入 Git。

### 4. 启动 API

```bash
DATABASE_URL="$RADAR_DB_URL" \
PYTHONPATH=apps/api \
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. 启动 Web

另开一个终端：

```bash
cd apps/web
AI_RADAR_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

打开：

- 精选：<http://127.0.0.1:3000/latest>
- 全部动态：<http://127.0.0.1:3000/all>
- Agent 接入：<http://127.0.0.1:3000/agent>
- 管理后台：<http://127.0.0.1:3000/admin>

管理后台需要在 `.env` 中设置强随机 `ADMIN_TOKEN`。手动文章导入、处理与发布由多个 `ADMIN_MANUAL_*` 开关控制，默认关闭。

## 管理后台与数据刷新

管理后台运行在 `/admin`，仅在数据库模式下可用。它不是公开 CMS，所有 `/api/admin/*` 请求都必须通过 `ADMIN_TOKEN` 验证。

当前后台包括：

- **仪表盘**：查看数据规模、抓取结果、AI 处理阶段和每次运行台账。
- **信源管理**：新增、编辑、启停、试抓和安全删除信源。
- **内容管理**：筛选、预览、编辑、隐藏或删除事件。
- **刷新计划**：手动触发完整刷新，或配置数据库中的定时间隔。
- **手动发文（可选）**：URL 导入、草稿编辑、AI 处理、图片上传和发布分别受功能开关约束。

API 进程每分钟检查一次数据库中的刷新计划；到期后执行抓取、预筛选、正文提取、评分、聚类、持久化和周期报告更新，并拒绝与仍在运行的刷新重叠。`scripts/run_scheduled_refresh.sh` 保留为手动或外部调度的备用入口，自带目录锁，日志写入 `data/logs/refresh.log`。

> 当前调度器随 API 进程启动。若把 API 横向扩成多个副本，需要先单独设计唯一调度权或分布式锁，不能直接假定多副本仍只会触发一次。

## 测试与检查

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_api_once.py --base-url http://127.0.0.1:8000

cd apps/web
npm run typecheck
npm run build
```

## 环境变量

完整模板见 [`.env.example`](.env.example)。本地至少需要数据库连接；真实 AI 处理再选择一个 Provider：

| 用途 | 主要变量 |
| --- | --- |
| 数据库与缓存 | `DATABASE_URL`、`REDIS_URL`、`FASTEMBED_CACHE_DIR` |
| Provider 选择 | `AI_PROVIDER=qwen|openai|kimi|deepseek|fake` |
| Qwen／阿里云百炼 | `ALI_API_KEY` 或 `DASHSCOPE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Kimi | `KIMI_API_KEY` 或 `MOONSHOT_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| 管理后台 | `ADMIN_TOKEN` 与 `ADMIN_MANUAL_*` 功能开关 |
| SourcePilot／X | `SOURCEPILOT_BASE_URL`、`X_TWEET_ARTICLE_PIPELINE_*` |
| 访问统计 | `UMAMI_APP_SECRET`、`UMAMI_TWO_FACTOR_KEY`、`UMAMI_WEBSITE_ID` |

不要把 `.env`、模型密钥、管理员 Token 或第三方服务凭证提交到仓库。

Provider 选择有两种方式：显式设置 `AI_PROVIDER`，或者留空并根据已配置的 Key 自动选择。开发环境建议先用 `AI_PROVIDER=fake` 或命令行的 `--fake-ai` 验证完整数据链，确认抓取、数据库和页面都正常后再启用付费模型。

## 生产部署

`infra/docker-compose.prod.yml` 描述了当前生产形态：PostgreSQL、Redis、FastAPI、Next.js、Nginx，以及当前默认启用的 Umami 访问统计。它是可审阅的部署参考，不是对任意服务器都能直接执行的一键安装包。

开始部署前至少需要：

1. 准备独立的生产 `.env`，生成强随机的数据库密码、`JWT_SECRET` 与 `ADMIN_TOKEN`。
2. 保持 PostgreSQL 默认只绑定 `127.0.0.1`，不要把 5432 暴露到公网。
3. 按实际拓扑处理 Compose 中的外部 `sourcepilot_default` 网络；不接 SourcePilot 时应移除对应网络依赖，而不是创建一个没有服务的空网络。
4. 默认 Compose 会启动 Umami；先创建独立的 `umami` 数据库并配置两项密钥，它不能与会被业务数据同步覆盖的 `radar` 库混用。若不需要统计，必须同时移除 `umami` 服务、Nginx 依赖与代理路由，不能只把密钥留空。
5. 从模板创建本机部署目标配置，并逐项检查 SSH 别名、远端目录、域名、Docker 权限和 Compose 文件组合：

```bash
cp scripts/deploy_targets.local.sh.example scripts/deploy_targets.local.sh
# 编辑 scripts/deploy_targets.local.sh；该文件包含机器信息，默认不进入 Git
bash scripts/deploy_to_server.sh
```

发布脚本执行代码同步、镜像构建、容器重启、Alembic 迁移和分层健康检查。CDN 返回 200 只能证明边缘仍有响应，不能替代容器状态与源站直连检查。

> 不要在日常运维中执行 `docker compose down -v`；`-v` 会删除 PostgreSQL 数据卷。数据库同步和恢复脚本同样会替换数据，执行前应先确认目标与备份。

## 目录结构

```text
apps/api/       FastAPI、采集器、AI 流水线、仓储与 Alembic 迁移
apps/web/       Next.js 网站、管理后台、公开 REST／MCP／RSS 路由
infra/          Docker、Nginx 与运行配置
scripts/        抓取、流水线、检查、同步与部署脚本
tests/          后端、流水线、接口和前端结构回归测试
docs/           架构决策、实施记录与运维文档
data/           本地运行产物和缓存（默认忽略）
```

## 延伸文档

- [开发计划](docs/development-plan.md)：阶段目标与历史验收记录；阅读时应以当前代码和测试为准。
- [实现说明](docs/implementation-notes.md)：早期架构决策与工程约束。
- [AI 调用降本记录](docs/2026-08-13-ai-cost-optimization.md)：Provider 切换、思考预算与验证方法。
- [安全加固计划](docs/2026-08-13-hardening-plan.md)：威胁模型、Nginx／CDN 防护和事故复盘。
- [SEO 优化方案](docs/2026-08-17-seo-optimization-plan.md)：索引、结构化数据、Sitemap 与验收标准。
- [SourcePilot 接入方案](docs/sourcepilot-integration-plan.md)：上游数据边界、网络路径和分阶段实施记录。

## 当前边界

- 产品以中文 AI 信息为主，不是通用新闻搜索引擎。
- 公开 API 的原生时间窗为过去 24 小时和最近 7 天；更早历史暂不提供查询合同。
- API、MCP 与 RSS 返回摘要、推荐理由和来源链接，不提供第三方原文的批量镜像。
- 周报与月报目前提供网页阅读，尚未纳入公开 API、MCP 或 RSS 合同。
- 当前没有 SSE、Webhook 或服务端推送；轮询应遵守响应中的 `Cache-Control` 与 ETag。
- 管理后台使用单一管理员 Token，尚未实现多用户权限模型。
- AI 生成内容只能作为线索；引用数字、政策或原话前应回到原始信源核验。

公开数据接口的使用授权与代码许可证是两件事。当前线上服务允许个人非商业、公益非商业和组织内部使用；面向外部的商业产品、收费服务、客户交付、代理接口、数据转售、公开镜像或批量再分发，需要事先取得书面授权。

仓库目前尚未提供 `LICENSE` 文件，因此不要自行假定代码采用 MIT、Apache-2.0 或其他开源许可证。后续如加入许可证，以仓库根目录的 `LICENSE` 为准。第三方文章、图片、商标和原始内容仍归各自权利人所有；AI·RADAR 提供的是索引、摘要、聚类与溯源入口。

## 参与项目

欢迎通过 [GitHub Issues](https://github.com/suversal/AIRadar/issues) 提交：

- 高质量 AI 信源建议
- 同事件误拆分或错误合并
- 摘要、分类、评分与译文问题
- Agent、MCP、RSS 或 REST 接入问题
- 文档、测试和可复现的修复方案

提交问题时请附上页面地址、发生时间和可复现步骤，不要附带 Token、Cookie、私有订阅地址或本地文件内容。

## 联系方式

[GitHub](https://github.com/suversal/AIRadar) · [Email](mailto:contact@suversal.com) · [Telegram](https://t.me/suversal) · [X](https://x.com/suversal)

## License

此仓库当前尚未包含开源许可证。在正式公开发布前，需要明确选择并添加许可证；在此之前，代码默认保留全部权利。线上公开数据接口的使用规则不等同于仓库代码许可证。
