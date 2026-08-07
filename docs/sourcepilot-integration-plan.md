# SourcePilot → AIRADAR 接入与展示方案

> 起草：2026-08-04。依据 SourcePilot 契约 v1.8.0（`SourcePilot/docs/contract.md`，
> 唯一合同）与 AIRADAR 当前架构（爬取 + AI 管线在本地 Mac，整库同步腾讯云只读展示）。
>
> **Phase 1（公众号）已于 2026-08-04 落地**，见文末「Phase 1 实施记录」。

---

## 0. 结论先行

**接入点选在 AIRADAR 的爬虫层**：新增一个 `sourcepilot` 类型的 crawler，把
SourcePilot 当作「聚合上游」，每个 AIRADAR Source 对应 SourcePilot 的一个过滤视图。
AI 打分、聚类、成报管线一行不动；云端前端也不直连 SourcePilot。

展示侧分三类处理：

| 数据 | 走哪条路 | 展示位置 |
|---|---|---|
| 厂商发布 / RSS / 公众号 | 进现有 AI 管线 | 现有 `/latest` `/all` |
| 平台热榜 | **不进 LLM 管线**，独立同步 | 新页面 `/hot` |
| X 推文 | **不进 LLM 管线**，独立同步 | 新页面（或 `/all` 内 tweet 卡片） |

分四个阶段切换，每阶段可独立回滚。

---

## 1. 两边现状与网络路径

**SourcePilot**（Mac mini 常驻，契约 v1.8.0）：

- 44 个信源：8 厂商官方（`vendor`）+ 14 热榜 + RSS 迁移源 + 19 个公众号 + X 时间线
- 关键端点：`/api/v1/items`（喂 AIRADAR 的归一化信息流，`since` 增量实测 4ms）、
  `/api/v1/hotlist`、`/api/v1/x/tweets`（推文全貌）、`/api/v1/x/thread`、
  `/api/v1/wechat/feed`、`/api/v1/article`（现查正文转 Markdown）、`/api/v1/health`
- 查询路径纯读库、毫秒级，不会被上游抖动拖住

**AIRADAR**：

- 采集：`Source`（`type` 在 `crawlers/registry.py` 分发）→ `BaseCrawler.fetch()` →
  `RawArticle` → prefilter / LLM 打分 / 聚类 → `EventCluster` → 报告
- 部署：**爬取与 AI 管线在本地 Mac**，`sync_db_to_server.sh` 整库替换到腾讯云；
  云端只读展示（大陆服务器访问不了 GitHub/X，这个架构不能变）
- 去重：`raw_articles` 按 `url_hash` / `title_hash`；`article_id = hash(source.id + url_hash)`

**网络路径**：AIRADAR 爬虫在本地 Mac，SourcePilot 在 Mac mini，局域网 / Tailscale
直达。**云端永远不需要访问 SourcePilot**——数据经本地管线落库后随整库同步上云。

---

## 2. 四个架构决策

### 决策 1：在 crawler 层接，不动管线、不让前端直连

- SourcePilot 的职责边界是「看见·抓取·归一化」，明确不做排序和 LLM 分析；
  AIRADAR 的价值恰恰是打分 / 聚类 / 中文化——两边职责互补，接缝就在 RawArticle。
- 云端只读架构决定了前端实时调 SourcePilot 这条路不存在。

### 决策 2：一个 AIRADAR Source = SourcePilot 的一个过滤视图

`SourcePilotCrawler` 读 `source.config`，按 `platform` / `source` 过滤拉取
（如 `config: {"sp_platform": "openai"}` → `GET /items?platform=openai`），
而不是把 SourcePilot 整个当一个巨型源。理由：

- 保留 per-source 的 `tier` / `source_role`（打分的 tier 系数依赖它）；
- 保留 per-source 的爬取监控与失败统计；
- 聚类的 `source_count` 热度信号（一条新闻上了 N 个源）依赖源的独立性——
  这也正是 SourcePilot 契约坚持「跨源不去重」的原因，两边原则一致。

### 决策 3：迁移重叠源时保留原 `source.id`，只改 `type` 和 `config`

`article_id = hash(source.id + url_hash)`。id 不变则同一篇文章无论从直爬还是
SourcePilot 进来，生成的 article_id 一致——历史连续、天然幂等，不会出现双份。
回滚 = 把 `type` 改回去，零数据损伤。

### 决策 4：热榜与 X 不进 LLM 管线

热榜条目量大、生命周期短、标题即全部内容；推文碎片化且互动数才是核心信号。
全量喂 LLM 打分是烧钱制造噪音。两者走独立同步表 + 独立展示面；
若日后想让个别热点进事件聚类，取热榜 top-N 单独喂管线即可（留作可选项）。

---

## 3. `SourcePilotCrawler` 实现细节

新文件 `apps/api/app/crawlers/sourcepilot.py`，registry 加一行分发。

### 拉取协议

```
GET {SOURCEPILOT_BASE_URL}/api/v1/items
    ?platform=<config.sp_platform>     # 或 source=<config.sp_source_type>
    &since=<上次拉到的最大 discovered_at>
    &window=all                        # 增量语义交给 since，不要再叠时间窗
    &limit=200
# 翻页：带 meta.next_cursor 且 since 保持不变，直到 has_more=false
```

- `since` 按**收录时间**过滤（契约 §4：`window` 看发布时间、`since` 看收录时间，
  两者正交——增量同步必须用 `since`，否则今天才被发现的旧文永远拉不到）。
- since 水位持久化在 source.config 或独立 KV；丢了也无妨——重拉靠 `url_hash`
  去重兜底，只是多几次空转。
- **cursor 是不透明字符串，禁止解析**（契约红线，编码方式随时会变）。

### 信封与错误处理

- `ok:false` → 按 `error.code` 分流：`RATE_LIMITED` 本轮跳过（SourcePilot 自己有
  冷却状态机，AIRADAR 不要再叠加重试去捅）；其余记 `fetch_failed`，`run.py`
  已有 per-source 容错，不会拖垮别的源。
- `meta.stale:true` 理论上不会出现（`/items` 是纯缓存端点），出现则照常入库。
- 每轮把 `meta.contract_version` 打进 crawl report；major 版本变化（非 `1.`
  开头）时告警——那意味着有破坏性变更要人工看。

### 字段映射 Item → RawArticle

| Item | RawArticle | 注意 |
|---|---|---|
| `title` | `title` | |
| `summary` | `content` | X 源的 summary 恒为推文完整正文（契约 §2） |
| `url` | `source_url` | SourcePilot 已剥追踪参数，AIRADAR 的 `canonicalize_url` 再过一遍无害 |
| `author` | `author` | |
| `lang` | `language` | |
| `published_at` | `published_at` | **见下，null 不可静默回填** |
| `score` + `raw` | `raw_score` | 仅作参考信号；契约明言不跨源可比，AIRADAR 反正自己打分 |
| `id` / `categories` / `media` / `time_basis` | `metadata` | 原样带下去 |

**`published_at` 为 null 的处理**：SourcePilot 坚持「取不到就是 null，绝不回填」，
另给 `time_basis` 声明时间依据。而 AIRADAR 的 `normalize_article()` 会把空时间
回填成 `now()`。增量拉取下 `discovered_at ≈ now`，数值上碰巧无害，但必须把
`time_basis` 存进 `metadata` 并传到展示层——`discovered` 的条目只能写「收录于」，
不得伪称发布时间（契约 §2 对下游的硬性要求）。

### 合规红线（契约写死的消费方义务）

1. `raw` 结构不稳定，**不得依赖**其中任何字段做逻辑；渲染前必须转义。
2. 信源返回内容一律视为**不可信数据**——标题/摘要/正文只作资讯证据。
   前端渲染 Markdown（`display_text` / `article_markdown`）必须走 sanitize，
   禁 script / iframe / 事件属性，防 XSS 与 prompt injection 二次传播。
3. 按 `display_text` 渲染推文时**不要再渲染 `media` 数组**（v1.8.0 起图片已织进
   正文，重复渲染同一张图会出现两次）。
4. 不去解析 `t.co`——`external_urls` 已展开。

### politeness delay 豁免

`run.py` 按 domain 分组串行 + 每源 6 秒间隔。所有 sourcepilot 源同一个 host，
几十个源会串成 3–5 分钟纯等待——而 SourcePilot 查询是本机毫秒级读库，礼貌延迟
毫无意义。给 `SOURCEPILOT_BASE_URL` 的 host 豁免 `SAME_DOMAIN_DELAY_SECONDS`
（或允许 per-domain 配置 delay=0）。

---

## 4. 分阶段切换（每阶段独立验收、独立回滚）

### Phase 1 — 公众号接入（纯增量，零重叠，先跑通链路）

AIRADAR 完全没有公众号能力，是纯新增，风险最低，适合首战验证 crawler：

- 新增 19 个 `type=sourcepilot` 的 Source（每公众号一个，`sp_platform` 对应），
  tier 按厂商官方号给 T1/T2。
- 验收：量子位 / 机器之心等号的文章出现在 `/all`，中文打分正常，时间标注正确。

### Phase 2 — 重叠源逐个切换（RSS / vendor，约 23 个）

- 以 **AIRADAR 数据库实际启用状态**为准核对重叠清单（不是 seed 文件——
  SourcePilot 侧已踩过这个坑）。
- 每源：改 `type=sourcepilot` + 填 `config`，**保留 source.id**（决策 3）→
  观察一轮采集无重复入库 → 下一个。先切 2 个观察一天，再批量。
- 回滚：单源改回原 type 即可。
- 收益：AIRADAR 甩掉直爬的反爬维护（Cloudflare、TLS 指纹、改版），这些
  SourcePilot 已集中处理；同一批站点也不再被两套爬虫各抓一遍。

### Phase 3 — 热榜展示面 `/hot`

数据链：`GET /api/v1/hotlist` → 本地新表 `hot_items` → 随整库同步上云 → 新页面。

- 同步脚本并入现有 crawl 定时任务；整库替换的同步方式意味着**只要本地库有表，
  云端就有**，不需要动 sync 脚本。
- 表结构照 Item 存，外加 `platform` / `rank`（从 `raw` 里的原始榜单位换算或
  按 score 反推）、`snapshot_at`（= `meta.collected_at`）。

### Phase 4 — X 推文展示面

数据链：`GET /api/v1/x/tweets` → 本地新表 `x_tweets` → 同步上云 → 新页面。
用 `/x/tweets` 而非 `/items?source=x`——前者才有互动数、`external_urls`、
引用链、`article_markdown`（契约 §5.4：两个视图，渲染卡片必须用前者）。

---

## 5. 展示方案

### 5.1 常规文章流（vendor / RSS / 公众号）

进现有 `/latest` `/all`，无需新 UI。唯一改动：读 `metadata.time_basis`，
`discovered` 的条目时间前缀写「收录于」。

### 5.2 热榜页 `/hot`

- **多平台 tab**（B站 / 头条 / HN / 掘金…14 个），每 tab 按 rank 排列，
  显示榜内名次与原始热度值（`raw` 里的阅读数/榜单分，仅展示不参与逻辑）。
- **「N 个源在讨论」标记**：同一事件上了多个平台的榜，是最可靠的热度信号——
  SourcePilot 刻意不抹掉这个重数（契约 §2），展示层按标题相似度做轻量聚合，
  聚出「同题条目 ≥2 个源」的给醒目标记。这个聚合只在展示层做、只影响排版，
  不回写数据。
- 快照时间显著标注（`snapshot_at`），热榜是时点数据，不标会误导。

### 5.3 X 推文卡片（按 `content_kind` 分流渲染）

契约 §5.4 已把展示分流算好了，前端照 `content_kind` 写分支即可：

| `content_kind` | 渲染 |
|---|---|
| `repost` | 头部写「@A 转发了 @B」，正文展示 `retweeted_*`（外层推文没有自己的内容） |
| `article` / `longform` | 文章式卡片：`display_title` 做标题，`display_text`（Markdown，已含标题层级/加粗斜体/配图）做正文，可折叠 |
| `quote` | 主文 + 嵌套引用卡（`quoted_handle` + `quoted_text`） |
| `link` | 正文 + 外链卡片（用 `external_urls`，不要自己解析 t.co） |
| `brief` | 紧凑卡；同话题多条可聚合成「N 条在讨论 X」 |

- 统一用 Markdown 渲染 `display_text` + sanitize；**不再单独渲染 `media` 数组**。
- 互动数（likes / retweets / views）直接展示——这是用 `/x/tweets` 的意义。
- 线程：`conversation_id` 相同的展示「查看完整线程」，数据用
  `/api/v1/x/thread`（`author_only=true` 默认已滤掉评论区互动）。
- `article_ai_summary` 若非空可作摘要展示，但要标注「X 生成」（二手信息）。

### 5.4 正文阅读（可选优化）

AIRADAR 的语义阅读 / 正文抓取（`article_content.py`）可逐步改调
`GET /api/v1/article`（现查、SSRF 防护、Markdown 输出），少维护一套抓取逻辑。
非必需，留作 Phase 2 之后的顺手活。

---

## 6. 运维与可靠性

- **配置**：AIRADAR 侧环境变量 `SOURCEPILOT_BASE_URL`
  （同机 `http://127.0.0.1:8420`——8000 已被 AIRADAR 自己的 API 占用；
  跨机走 Tailscale MagicDNS 名）。
- **健康联动**：crawl 前探一次 `/api/v1/health`，分源状态并入 crawl report——
  SourcePilot 的 Canary 能报「连续失败 / 数据落后」，比 AIRADAR 自己猜准确。
- **SourcePilot 整体不可达**：per-source 容错已保证不拖垮直爬源；连续多轮
  失败时告警。Phase 2 切过去的源保留原直爬配置（`is_active=false`），
  紧急时翻回来。
- **数据保留**：SourcePilot 有自己的清理策略，AIRADAR 把拉到的条目自己持久化，
  上游清理不影响 AIRADAR 历史与云端展示。
- **契约版本**：监控 `meta.contract_version`；minor 升级无感，major（`/api/v2`）
  出现时人工介入。

## 7. 明确不做

- **不用推模式**：SourcePilot 侧已论证（T6 降级 P2）——`since` 增量 4ms，
  轮询天然幂等容错；推模式换几十秒延迟，代价是重试/验签/状态搬家。
- **不让云端直连 SourcePilot**：数据一律经本地管线随整库同步上云。
- **X 现查（`search_x`）暂不接**：AIRADAR 当前没有「用户即时提问」场景，
  它是给 Agent/MCP 出口的能力。日后做话题追踪时再评估。
- **不在 AIRADAR 侧解析 cursor、依赖 raw 结构、二次抓取已展开的外链**。

---

## 8. Phase 1 实施记录（2026-08-04 落地）

新增 `apps/api/app/crawlers/sourcepilot.py`（`SourcePilotCrawler`）+ registry 分发 +
23 个 `sp_wechat_*` Source（`default_sources.py`，已注册入库并启用）。
测试:`tests/test_sourcepilot_crawler.py` 18 例 + delay 豁免 2 例,全套 566 通过。

### 与 §3 拉取协议的一处偏差（重要）

**实际走的是 `GET /api/v1/wechat/feed?account=<公众号名>`,不是 `/items?platform=`**。
实测发现 `/items` 的 `platform` 参数有白名单校验,只认信源配置名
（`wechat` 整体算一个）,不认具体公众号名——按号过滤只有 `/wechat/feed` 能做。
连带两个变化:

- `/wechat/feed` 没有 `since` 参数（契约 §4 如此）,增量水位改为**客户端过滤**:
  水位存 `data/sourcepilot/state/{source_id}.json`,`discovered_at <= 水位` 的条目
  在解析前丢弃;`config.recent_days` 映射成 `window` 枚举（1→24h, ≤7→7d, ≤30→30d,
  0→all）做服务端截幅。
- 若日后 SP 侧把公众号名加进 `/items` 的 platform 白名单,可切回 §3 原方案
  拿到服务端 `since`;当前方案在本机毫秒级查询下没有实际代价。

### 其余按计划落地的关键点

- 正文 eager 走 SP `/article`,缓存 `data/sourcepilot/article_cache/{url_hash}.json`,
  每源每轮网络调用预算 `sp_article_limit=20`（缓存命中不占);失败降级 summary/title
  入库并标 `metadata.sp_body="missing"`。**绝不设 `body_fetch=deferred`**
  （mp.weixin 在 UNFETCHABLE_ARTICLE_DOMAINS,deferred 会让管线自己抓然后放弃）。
- 正文双通道:`content`=Markdown 喂评分;`metadata.original_markdown` 走前端
  既有渲染路径,展示侧零改动。
- delay 豁免:`run.py` 读 `config.same_domain_delay_seconds`（sp 源配 0),
  实测 23 源一轮 0.0s（原本要 132s 纯等待）。
- `time_basis` 透传:repository 白名单 + `LatestEvent` 类型 + `formatDateTime`
  「收录于」前缀。
- 信封分流:`RATE_LIMITED` 返回已收集不推水位不记 fetch_failed;其余 ok:false 抛
  RuntimeError 走既有 per-source 容错;contract major 变化 logger.error。

### 端到端验证结论（2026-08-04）

- 量子位单源:首轮 27 篇 29.4s（20 篇全文 enrich,命中预算上限）;第二轮 0.01s 0 篇
  （水位生效)。admin `/test` 完整管线:27 抓取 / 18 入选 / 19 落库,预筛正确拒掉
  「编辑作者招聘」等非 AI 内容,落库 metadata 带 `content_origin=sourcepilot_article`
  与 `time_basis=published`。
- 智谱等低频厂商号 0 条是**上游正确行为**:最近一篇发布于 6-17,`window=30d` 按
  发布时间过滤不到。SP 恢复采集后新文会正常流入。
- 注意:SP 公众号采集因上游限流停在 2026-07-27,恢复后 `recent_days` 窗口内的
  新文自动进入;历史存量不补(有意,旧闻对日报无价值)。
- 遗留观察项:事件聚类在下一轮定时 refresh 才会把新落库文章聚成事件出现在
  `/all`;首批验证文章发布日期在 7 月底,不进当日报告窗口属正常。

### 附带修正

`register_new_sources.py` 顺带把库里缺失的旧种子 `aihot_all` 也注册了（该脚本
推所有缺失默认源)。为保持既有行为已手动置回 `is_active=false`——之前它就不在库里、
不被抓取。

---

## 9. Phase 1 后续：公众号上游能力被微信关闭（2026-08-06）

**23 个 `sp_wechat_*` 源已全部 `is_active=false`**（已入库的 27 篇文章保留，不删数据）。

原因不在接入层，而在最上游：微信自 2026-07-30 前后收紧了第三方跨公众号调用
`appmsg?action=list_ex` 的权限，SourcePilot 拿不到文章列表，`/wechat/feed`
自然也就没有新数据。四组对照实测（换公众号主体、换个人微信号、IPv6/IPv4 出口）
全部仍返回 `ret=200013`，而同一套凭据打 `searchbiz` 正常——不是账号被封，
也不是我们把额度打爆。完整证据与三条替代路线的排查记录在
`SourcePilot/docs/progress.md` 已知问题表，以及 `config/sources/wechat.yaml` 文件头。

**AIRADAR 侧不需要任何代码改动**：`SourcePilotCrawler` 本身工作正常（实测量子位
27 篇 / 20 篇全文入库），只是上游没数据了。SourcePilot 的公众号能力一旦恢复，
把这 23 个源 `is_active` 改回 true 即可，水位文件还在，会从上次位置继续增量。

**Phase 2（RSS / vendor 重叠源切换）不受影响**——那批源走的是 SourcePilot 的
声明式引擎，与公众号 channel 完全隔离。

### 9.1 已恢复（2026-08-06 当天）

SourcePilot 侧改走**微信读书**（`weread` 后端）绕开了被关闭的公众平台接口，
23 个 `sp_wechat_*` 源已全部 `is_active=true` 重新启用。

实测一轮：**23/23 源 ok，47 篇入库，44 秒**，量子位/机器之心当天文章正常流入。
`SourcePilotCrawler` 一行未改——上游恢复供数后，水位文件接着上次位置继续增量，
这正是当初把水位放在本地文件、把接入层与上游解耦的价值。

### 9.2 正文提取改回 AIRADAR 自己那套（2026-08-06）

**决策：AIRADAR 侧的正文抓取不走 SourcePilot 的 `/api/v1/article`，改用自己的
`fetch_manual_article()`（草稿管理同一条路）。SourcePilot 那个端点保留不动。**

Phase 1 首版是绕去 SP 取正文的，理由是「SP 有专为公众号写的 htmlmd」。复核后发现
这个前提不成立——AIRADAR 本来就有能抓公众号的提取器：`article_content.py` 里配着
`wechat-article-v1` profile（`#js_content` 容器），草稿管理天天在用。

实测同一篇文章（DeepSeek-V3 那篇），两边覆盖度一致：

| | AIRADAR `fetch_manual_article` | SourcePilot `/api/v1/article` |
|---|---|---|
| 小标题 | 2（`type: heading`） | 2（`## `） |
| 配图 | 7（`type: image`） | 7（`![]()`） |
| 段落 | 21 | — |
| 耗时 | 0.95s | 1.1s |

差别只是**输出形态**（结构化块 vs 一整段 Markdown），不是完整度。而块结构正是
AIRADAR 前端与翻译流程原生消费的形状，比硬塞进 `metadata.original_markdown` 更贴合。

换回来的收益：少一跳网络、少一处要跟着微信改版维护的代码、正文不再依赖 SP 在不在线。

**一个容易踩的坑**：`mp.weixin.qq.com` 在 `UNFETCHABLE_ARTICLE_DOMAINS` 里，看起来
像是「AIRADAR 抓不了公众号」。但那道检查只在**爬虫路径**（`page_content.py`）上，
`fetch_manual_article` 不查那个名单（实测 0 处引用）。这个黑名单是早期只有 AI HOT
链接跳转场景时的策略遗留，不是技术上做不到——清理技术债时可以重新审视。

落地细节：

- `metadata` 写 `original_blocks` / `original_paragraphs` / `original_images`，
  这三个键早就在 `_EVENT_CONTENT_METADATA_KEYS` 白名单里，**展示侧零改动**。
- `content_origin` 用提取器自报的 `manual_url_fetch`。注意不能是
  `aihot_item_page_link_only`——那个值会让前端整块跳过原文渲染。
- 正文缓存加了版本号（`_CACHE_VERSION = 2`）。v1 存的是 SP 返回的 markdown 字符串，
  形状不兼容，读到旧版当未命中重取。
- **存量行不会自动转格式**：管线对已存在的文章直接标 `duplicate` 并跳过 upsert
  （`main.py:964`），所以 08-06 之前入库的 74 篇仍是 `original_markdown`。
  前端两种都支持，不影响展示；要统一需单独写回填脚本。

验证：一篇量子位文章提取出 143 个块（16 标题 / 14 图 / 112 段）；月之暗面 Kimi
7 篇入库，`blocks=28 imgs=1 origin=manual_url_fetch`。
