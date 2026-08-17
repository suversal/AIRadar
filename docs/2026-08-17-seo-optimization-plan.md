# AI·RADAR SEO 优化方案

> 站点：<https://radar.suversal.com>  
> 日期：2026-08-17  
> 来源：本文正文（第 1 节起）是 GPT 出的建议书，原样保留  
> 状态：已评审，第一批已实施并上线（评审结论见下）

---

## 0. 评审结论（2026-08-17）

正文的事实断言逐条核对过，基本都准确：sitemap 只有 13 条、详情页无 canonical、
`/search` 被放进了 sitemap、`/weekly/[key]` 只有通用标题「AI 周报」、`/` 是 307、
`/latest` 上确实有 37 个图片 preload。

但它的**优先级排错了一个关键位置**，而且漏了两件更要紧的事。

### 0.1 决定性事实：根本没有爬虫来过

评审时查了线上 nginx 48 小时日志，共 5466 条请求：

| 爬虫 | 请求数 |
|---|---|
| Googlebot | **0** |
| Bingbot | **0** |
| Baiduspider | **0** |
| DuckDuckBot | 9 |

其余 88 条 bot 流量是 FlowIQLabsBot、Censys、FreePBX-Scanner 这类扫描器。

这意味着正文 P0 的九条——动态 sitemap、canonical、JSON-LD、308——**做了也没有任何
东西会读到**。正文把「Google Search Console / Bing 验证」放在 **P2 最后**，是全文
最大的问题：那不是收尾工作，是前置条件，也是验证其余所有改动是否生效的唯一手段。

顺带确认：48h 有 48 次 429，全部打给伪装成手机浏览器的爬虫，**没有一次误伤搜索引擎**——
2026-08-13 那批限流没有拖 SEO 后腿（见 [2026-08-13-hardening-plan.md](2026-08-13-hardening-plan.md)）。

### 0.2 采纳清单

| # | 事项 | 判定 | 说明 |
|---|---|---|---|
| 1 | GSC / Bing 验证 + 提交 sitemap | **提到第一位做** | 正文放在 P2，顺序错了 |
| 2 | `/search` 改 noindex 并移出 sitemap | **已做** | 顺带把 `/feedback` 也移出 |
| 3 | 详情页 canonical + 文章级 OG/Twitter | **已做** | 收益比预想大，见 0.4 |
| 4 | 动态 sitemap 纳入事件详情页 | 做，本周 | 实现方式有坑，见 0.5 |
| 5 | weekly/monthly 归档页动态 metadata | 做，本周 | |
| 6 | `/` 改 308 | 做，顺手 | 收益接近零，但没有理由不做 |
| 7 | 图片懒加载 / 干掉 37 个 preload | 做，但**理由不是 SEO** | 见 0.3 |
| 8 | 正式主题落地页 `/topics/{slug}` | **暂缓** | 见 0.3 |
| 9 | robots 放开 `/api/image-proxy` | **否决** | 见 0.3 |
| 10 | 图片站内持久化 `/media/{hash}.webp` | **否决** | 工作量大，收益近零 |
| 11 | 日报迁到 `/daily/YYYY-MM-DD` | **冻结** | 见 0.3 |
| 12 | IndexNow / 百度主动推送 | 推迟 | 一条都没收录就接主动推送是本末倒置 |

### 0.3 否决与暂缓的理由

**#8 主题落地页（正文的 P1 重点）——数据撑不起来。**
日均 35–60 条、8 月 90% 是单信源单日事件。按这个密度切 6 个专题页，每页只有十几条
没有时间跨度的卡片，正好命中正文自己第 11.1 节警告的「薄内容」。而且判断它值不值得做的
依据（哪些非品牌词有曝光）恰恰要等 GSC 跑够四周才有。**顺序应该是先拿数据再动手。**

**#9 放开 image-proxy——正文自相矛盾。**
4.6 节建议放开，11.5 节又写「不要为 SEO 削弱安全边界」。image-proxy 是全站最贵的端点，
刚做完 SSRF 加固和 8MB/8s 限制，对全网爬虫敞开换来的是 Google 图片搜索流量——对
AI 资讯聚合站近乎为零。**不做。**

**#11 日报改 URL——底层语义还没定。**
不是没价值，而是**日期口径本身悬而未决**：`/latest` 按 `published_at` 分组、日报按
`report_date`，两者差 30–40%。在 URL 里嵌一个还没定下来的语义，改回来的成本比现在做的收益大。

**#7 preload 归类为性能问题而非 SEO 问题。**
实测那 37 个 preload 是 React 19 自动为 `<img>` 注入的，一次页面加载并发 37 个
`/api/image-proxy`。但这些图 CF 已缓存 24h（`cf-cache-status: HIT`），源站压力不大；
真实代价在移动端首屏带宽。**按性能和成本去做，别指望它影响排名。**

### 0.4 正文漏掉的两件事

**（一）Cloudflare 正在往 robots.txt 里注入内容。**

源站返回的 robots.txt 是 158 字节（就是 `apps/web/app/robots.ts` 那份），
但公网拿到的多出一整块 CF「Managed Content」：

```
Content-Signal: search=yes, ai-train=no, use=reference
User-agent: GPTBot          Disallow: /
User-agent: ClaudeBot       Disallow: /
User-agent: Google-Extended Disallow: /
User-agent: Bytespider      Disallow: /
```

这是 CF 的 AI Crawl Control 默认值，**不是我们写的**，它把所有 AI 爬虫全挡了。
对一个 AI 资讯站，ChatGPT / Perplexity / Claude 的引用正在成为真实的新流量入口。
取舍是真实的（挡住 = 内容不被白嫖去训练；放开 = 可能被 AI 搜索引用带流量），
**待决策**，但必须知道当前默认值是「全挡」。

**（二）这个站的 SEO 天花板不在技术层，在内容原创性。**

正文 6.3 提了，但分量给得太轻。详情页主体是**原文正文 + AI 摘要**——对这种页面，
Google 大概率把原始来源判为 canonical，或直接认定本站无增量价值。**做多少 JSON-LD
都顶不动这一条。**

站内真正独有的东西是：多信源折叠（`coverage` / `source_count`）、评分与入选理由
（`reason` / `final_score`）、同一事件的后续跟踪。这些**现在都渲染在页面上但没有被
结构化表达**。要投内容侧的力气，投这里比投 6 个专题页划算得多。

### 0.5 实施记录（第一批，已上线）

改动落在三个文件：`app/sitemap.ts`、`app/search/page.tsx`、`app/event/[id]/page.tsx`。

改动前线上详情页的分享卡片是这样的：

```
og:title  AI·RADAR — 为创作者和开发者准备的 AI 情报雷达   ← 站点通用标题
og:url    https://radar.suversal.com                    ← 指向根域名
```

**每篇文章分享出去卡片长得一模一样，链接还都指向首页。** 改完后是文章自己的标题、
摘要、配图和 URL，`og:type` 从 `website` 改成 `article`。

另外补了两个正文没提的**诚实性**约束：

- `time_basis="discovered"` 的条目不输出 `article:published_time`。这类条目我们只有
  收录时间，页面上写的是「收录于」；机器可读字段谎报成发布时间，等于把页面上诚实标注的
  东西又骗回去一遍（SourcePilot 契约红线）。
- `admin_preview=1` 与 `hidden` 的文章一律 `noindex, nofollow`。

**踩到并修掉的坑（Next.js 16.2.10）**：页面一旦自己定义 `openGraph` 对象，
`app/opengraph-image.tsx` 的默认图就**不再注入**，哪怕根本没写 `images` 键。
表现是 `/latest` 有 og:image、`/event/xxx` 一个都没有，**不报任何错**。
已改成显式兜底到 `/opengraph-image`。

**配图策略**：用原始外链图，**不套 `/api/image-proxy`**（理由同 #9）。这依赖
「抓取器不带 Referer 时原图能拿到」，已实测：`img.ithome.com` 原图在 `UA=Twitterbot`
且无 Referer 时返回 200 / 180KB。拿不到图的文章回退站点默认图，卡片退化成无图但不会出错。

**验证**：typecheck 通过（显式查退出码，不走管道——见
[hardening-plan 第 8 节](2026-08-13-hardening-plan.md)的教训）；dev 与 docker build
生产产物各验一遍，6 项全部一致。上次 `/weekly` 那类「dev 正常、build 烘死」没有复现。

### 0.6 顺带修复：部署脚本的健康检查盲点

`scripts/deploy_to_server.sh`（不在 git 中）的健康检查原本只 `curl` 公网 URL，
2026-08-13 那次 nginx 在重启循环、整站 521，CF 却拿缓存副本回 200，脚本一路绿灯
报「发布完成」。本次改成三层：

1. 容器状态**硬校验**（原本只打印不校验），命中 `restarting|exited|unhealthy|created` 即失败；
2. 从 nginx 容器内 `wget http://web:3000{path}` 验源站活性——既不过 CF，也不受源站
   CF IP 白名单限制（从服务器本机 curl 公网域名会被白名单挡成 403）；
3. 公网 curl 保留，但降级为「只证明 DNS/CF/证书链没断」。

⚠️ **不要再试 `?healthcheck=$RANDOM` 这类 cache buster**：2026-08-17 实测，
CF 那边的 Cache Rule 缓存键**忽略查询字符串**，带随机参数请求 `/latest` `/all` `/daily`
拿到的仍然是 `cf-cache-status: HIT`。公网这层没有便宜的穿透办法。

### 0.7 下一步

1. 观察 GSC「网页」与「站点地图」报告，确认首次抓取发生；
2. 本周做 #4 #5 #6（动态 sitemap、报告页 metadata、308）；
3. 攒够四周 GSC 数据后，再回头判断 #8（主题页）和 0.4（二）（内容原创性）。

---

以下为 GPT 原始建议书全文，未作改动。

## 1. 结论

AI·RADAR 已具备服务端渲染、基础标题描述、robots.txt、sitemap.xml 和 canonical 等基本 SEO 能力，但当前 sitemap 只暴露 13 个入口页面，没有包含数百个事件详情页以及历史日报、周报、月报。

当前 SEO 的首要问题不是关键词数量，而是：

1. 主要内容资产没有进入 sitemap；
2. 详情页缺少完整 canonical、文章级分享信息和结构化数据；
3. 站内搜索等低价值页面仍可被索引；
4. 主题筛选页没有独立、可排名的落地页；
5. 图片代理被 robots 统一拦截，同时列表图片存在过度预加载风险；
6. 尚未通过站长平台形成“提交、抓取、收录、流量”监控闭环。

建议分三个阶段推进：

- P0：技术收录基础；
- P1：主题落地页和内容可信度；
- P2：持续提交、监控和实验。

## 2. 本次检查范围

### 2.1 线上检查

已检查：

- `https://radar.suversal.com/`
- `https://radar.suversal.com/latest`
- `https://radar.suversal.com/robots.txt`
- `https://radar.suversal.com/sitemap.xml`
- 一个线上事件详情页
- `/search`、`/weekly` 等入口页
- 当前搜索引擎可见性快照

检查时确认：

- 根路径返回 307，并跳转至 `/latest`；
- `/latest` 返回 200，正文由服务端输出，不依赖浏览器执行 JavaScript 才能出现；
- robots.txt 和 sitemap.xml 均返回 200；
- robots.txt 允许普通搜索爬虫访问公开页面；
- sitemap.xml 当前只有 13 个入口 URL；
- 事件详情页有动态标题和摘要，但没有自引用 canonical；
- 事件详情页继承全站通用 Open Graph 信息；
- 页面中未发现文章级 JSON-LD；
- `/search` 当前为 `index, follow`；
- 当前 `site:radar.suversal.com` 搜索快照未看到明确结果。

说明：`site:` 查询不是权威收录统计。最终状态必须以 Google Search Console、Bing Webmaster Tools 和百度搜索资源平台的数据为准。

### 2.2 代码检查

重点文件：

- `apps/web/app/sitemap.ts`
- `apps/web/app/robots.ts`
- `apps/web/app/layout.tsx`
- `apps/web/app/event/[id]/page.tsx`
- `apps/web/app/search/page.tsx`
- `apps/web/app/daily/page.tsx`
- `apps/web/app/weekly/[key]/page.tsx`
- `apps/web/app/monthly/[key]/page.tsx`
- `apps/web/app/topics/page.tsx`
- `apps/web/components/event-card.tsx`
- `infra/nginx/radar-cf.conf`

## 3. 当前已有的基础

以下能力应保留：

- 全站 `lang="zh-CN"`；
- Next.js 服务端渲染；
- 全站 metadataBase 使用正式域名；
- `/latest`、`/all` 等入口已有独立标题、描述与 canonical；
- 已有站点级 Open Graph 图片；
- robots.txt 已声明 sitemap；
- `/admin`、内部 API 和本地收藏页不会作为公开内容入口；
- Cloudflare 与 nginx 已对公开 HTML 设置短时缓存；
- 列表页通过普通 `<a href>` 链接到详情页，爬虫能够沿内链发现内容。

## 4. 主要问题与影响

## 4.1 Sitemap 没有覆盖主要内容资产

当前 `apps/web/app/sitemap.ts` 明确排除了 `/event/[id]`，线上 sitemap 只包含入口页面。

影响：

- 新详情页只能等待爬虫从列表页逐层发现；
- 列表翻页或加载更多中的内容发现速度更慢；
- 搜索引擎无法准确知道哪些详情页是希望收录的 canonical URL；
- 历史日报、周报、月报不能通过 sitemap 稳定进入抓取队列；
- 所有 sitemap 条目的 `lastmod` 都是同一个生成时间，不能反映真实更新时间。

## 4.2 详情页 metadata 不完整

当前事件详情页只返回动态 `title` 和 `description`。

缺少：

- `alternates.canonical`；
- 文章级 `openGraph.title`；
- 文章级 `openGraph.description`；
- 文章级 `openGraph.url`；
- 与内容相关的 `openGraph.images`；
- 对应的 Twitter Card 信息；
- `Article` 或 `NewsArticle` JSON-LD；
- `BreadcrumbList` JSON-LD；
- 机器可读的发布时间与更新时间。

影响：

- 搜索引擎需要自行判断规范 URL；
- 分享详情页时仍可能展示站点通用标题和图片；
- 搜索引擎难以准确理解“标题、摘要、发布时间、发布方、图片”之间的关系；
- 页面无法获得适用的文章富结果资格。

## 4.3 低价值页面仍可索引

当前 `/search`：

- 使用 `index, follow`；
- 被放入 sitemap；
- 不同查询参数最终 canonical 到 `/search`。

站内搜索页通常不是希望搜索引擎展示的正式内容落地页。继续索引可能产生薄内容、空结果和重复页面。

需要重新确认的其他页面：

- `/bookmarks`：本地浏览器状态，不应索引；
- `/feedback`：主要是功能页，通常不需要进入 sitemap；
- 无内容的日报或报告页：应按实际状态 noindex；
- `admin_preview=1`：不得进入索引或分享缓存。

## 4.4 历史报告缺少独立 metadata

`/weekly/[key]` 和 `/monthly/[key]` 当前只有通用标题“AI 周报”“AI 月报”。

影响：

- 每一期在搜索结果中缺少日期和内容主线；
- 多期页面标题高度重复；
- 没有自引用 canonical；
- 分享卡片不能反映本期内容；
- sitemap 没有暴露归档 URL。

## 4.5 主题筛选页不能形成长尾入口

当前主题页链接到 `/all?topic={id}`，而 `/all` 使用固定 canonical `/all`。

这意味着：

- OpenAI、DeepSeek、Agent、模型发布等筛选结果不会成为独立搜索落地页；
- 所有主题信号最终被合并到 `/all`；
- 站点无法承接“DeepSeek 最新动态”“AI Agent 新闻”等稳定长尾搜索需求。

这是 P1 的重点，不应通过直接放开所有查询参数解决。正式专题必须有稳定路径、独立介绍、足够内容和内部链接。

## 4.6 图片可抓取性和加载性能

正文与列表图片经过 `/api/image-proxy`，但 robots.txt 当前禁止整个 `/api`。

影响：

- 搜索爬虫可能无法抓取最终图片 URL；
- 图片难以进入 Google Images 等图片搜索；
- 未来结构化数据中的图片也可能因不可抓取而无效。

同时，列表卡片图片没有显式 `loading="lazy"`，线上 HTML 中出现大量图片 preload。首页一次输出较多卡片时，可能造成：

- 移动端首屏竞争带宽；
- HTML 体积增大；
- 图片代理请求集中；
- LCP 和爬虫抓取效率下降。

本次尝试调用 PageSpeed Insights 时遇到公共 API 配额限制，因此没有把当前 Lighthouse 分数作为已确认事实。性能结果应在实现后通过本地 Lighthouse、Chrome DevTools 和 Search Console Core Web Vitals 重新测量。

## 4.7 根路径使用临时重定向

当前 `/` 使用 Next.js `redirect()`，线上返回 307 到 `/latest`。

如果产品约定根路径永久等同于 `/latest`，应使用永久重定向；如果希望强化品牌词和站点定位，可以将 `/` 建设为真正的首页。

两种方案只能选择一种：

### 方案 A：根路径永久跳转

- `/` 返回 308 到 `/latest`；
- sitemap 只保留 `/latest`；
- 所有品牌内链统一指向 `/latest`。

### 方案 B：根路径作为品牌首页

- `/` 返回 200；
- 展示产品定位、方法、核心入口和最新精选；
- `/` 使用自引用 canonical；
- `/latest` 继续作为内容流页面。

当前阶段建议方案 A，改动更小。后续有品牌内容需求时再评估方案 B。

## 5. P0：技术收录基础

## 5.1 动态 Sitemap

### 目标

让搜索引擎直接获得所有希望收录的公开 canonical URL，并看到可信的更新时间。

### 建议结构

短期 URL 量不足 50,000 时，可以继续使用一个 sitemap：

```text
/sitemap.xml
  ├─ 核心入口页
  ├─ 公开事件详情页
  ├─ 有内容的日报归档
  ├─ 周报归档
  └─ 月报归档
```

未来 URL 超过 50,000 或需要分类观测时，改为：

```text
/sitemap.xml                  sitemap index
/sitemaps/static.xml
/sitemaps/events-1.xml
/sitemaps/daily.xml
/sitemaps/weekly.xml
/sitemaps/monthly.xml
```

### 数据契约

只输出：

- 公开可访问；
- 未隐藏；
- 有实际内容；
- 返回 200；
- 当前 canonical 事件 ID；
- 希望出现在搜索结果中的 URL。

不要输出：

- 管理后台；
- 管理员预览 URL；
- 搜索页；
- 收藏页；
- API；
- 空报告页；
- 已删除页面；
- 旧事件 ID 或跳转地址；
- 任意筛选参数组合。

### `lastmod` 规则

- 事件详情：使用真实内容更新时间；没有更新时间时使用最后收录时间或发布时间；
- 日报：使用日报最后生成或修订时间；
- 周报、月报：使用报告最后生成或修订时间；
- 静态页：只在内容真正变化时更新；
- 禁止每次请求都把所有 URL 的 `lastmod` 改成当前时间。

### 实现方向

避免让 Docker 构建依赖 API：

1. sitemap 在运行时读取轻量 URL 清单；
2. 后端提供专用 sitemap 数据接口，或 Web 运行时直接查询只读数据源；
3. 接口只返回 `url/id + updated_at`，不返回正文；
4. 对 sitemap 设置合理缓存，例如 10～30 分钟；
5. 数据源不可用时保留最近一次有效版本，不输出空 sitemap。

### 验收标准

- sitemap 返回 200 和合法 XML；
- 包含公开事件详情页；
- 包含真实存在的日报、周报和月报；
- 不包含隐藏、删除、空内容或工具页；
- 随机抽取 20 个 URL，全部返回 200；
- sitemap 中只出现 `https://radar.suversal.com`；
- `lastmod` 与数据真实更新时间一致；
- Google Search Console 能成功读取且无解析错误。

## 5.2 事件详情页 Metadata

每个 `/event/{id}` 至少输出：

```ts
{
  title: event.title,
  description,
  alternates: {
    canonical: `/event/${canonicalEventId}`,
  },
  openGraph: {
    type: "article",
    url: `/event/${canonicalEventId}`,
    title: event.title,
    description,
    images: [...],
  },
  twitter: {
    card: "summary_large_image",
    title: event.title,
    description,
    images: [...],
  },
}
```

规则：

- description 从摘要中生成，去除异常空白和标记；
- 不机械截断到半个句子，建议控制在约 80～160 个中文字符；
- 优先使用站内可抓取的首图；
- 无可靠图片时使用站点默认分享图；
- 旧事件 ID 页面应跳转到 canonical ID，而不是两个页面都返回 200；
- 隐藏内容、管理员预览、无效内容设置 `noindex`。

### 验收标准

- 页面源代码存在自引用 canonical；
- OG URL 与 canonical 完全一致；
- OG 标题、摘要、图片对应当前事件；
- 不再继承首页通用 OG URL；
- 旧 ID 只保留一个规范页面；
- 分享到常用平台时展示正确标题和图片。

## 5.3 结构化数据

### 全站

增加：

- `WebSite`
- `Organization`

可包含：

- `name: AI·RADAR`
- `url`
- `logo`
- `description`
- 官方账号 `sameAs`，没有真实账号时不要填写

### 事件详情页

优先使用 `Article`。只有当页面确实符合新闻文章语义和发布责任时再使用 `NewsArticle`。

建议字段：

- `headline`
- `description`
- `url`
- `mainEntityOfPage`
- `datePublished`
- `dateModified`
- `image`
- `author`
- `publisher`
- `isBasedOn` 或清晰的原始来源关系（作为语义补充，不代替页面可见来源）

作者字段必须诚实：

- AI 自动聚合内容不能伪造个人作者；
- 可使用真实的组织或编辑部身份；
- 页面需要同步展示相同身份及 AI 处理说明。

同时添加 `BreadcrumbList`：

```text
AI·RADAR → 精选/分类 → 当前事件
```

### 报告页

日报、周报、月报可以根据页面实际形态使用 `Article` 或 `CollectionPage`，不要为了富结果强行使用不符合页面内容的类型。

### 验收标准

- Rich Results Test 无错误；
- JSON-LD 内容与页面可见内容一致；
- 图片 URL 可被匿名访问和抓取；
- 发布时间和更新时间真实；
- 隐藏字段中不存在页面未展示的夸大信息；
- Search Console 增强功能报告无模板级错误。

## 5.4 索引控制

### 建议规则

| 页面 | 建议 |
|---|---|
| `/latest` | index, follow |
| `/all` | index, follow |
| `/event/{id}` | 有效公开内容 index, follow |
| `/daily` 和真实历史日报 | index, follow |
| `/weekly` 和真实历史周报 | index, follow |
| `/monthly` 和真实历史月报 | index, follow |
| `/topics` | index, follow |
| 正式专题页 | 达到内容门槛后 index, follow |
| `/search` | noindex, follow |
| `/bookmarks` | noindex |
| `/admin/**` | 不公开，继续鉴权和 robots 限制 |
| 管理员预览 | noindex, nofollow，并避免公开缓存 |
| 空报告、无效详情 | noindex 或正确返回 404 |
| `/feedback` | 可访问，但从 sitemap 移除；是否 noindex 按产品定位决定 |

注意：如果希望搜索引擎读取某页面的 `noindex`，不能只依赖 robots.txt 禁止抓取该页面。robots 禁止抓取后，搜索引擎可能无法看到页面中的 noindex。

## 5.5 图片与首屏性能

### 图片可抓取

推荐优先级：

1. 最优：将公开内容图片缓存成稳定站内资源，例如 `/media/{hash}.webp`；
2. 次优：提供稳定、可缓存、允许搜索爬虫访问的公开图片代理路径；
3. 临时：在 robots 中精确允许图片代理，同时继续禁止其他内部 API。

图片 URL 应满足：

- 无登录要求；
- 不依赖临时签名；
- 返回正确 Content-Type；
- 支持长期缓存；
- 不因 Referer 缺失而失败；
- 不把任意外部 URL 代理能力无限暴露给爬虫。

### 加载策略

- 列表中非首屏图片使用 `loading="lazy"`；
- 设置 `width` 和 `height`，或稳定 `aspect-ratio`；
- 只有真正的 LCP 主图使用高优先级；
- 不要让几十张列表图自动生成 preload；
- 评估将列表首批 50 条减少到 20～30 条，其余继续加载更多；
- 检查 Next RSC 数据是否重复发送过多全文字段。

### 验收标准

- 页面源代码不再包含几十个非必要图片 preload；
- 搜索爬虫可以访问结构化数据中的图片；
- 图片加载失败不影响正文和链接；
- 移动端无明显布局跳动；
- Lighthouse 和真实用户数据不出现由本次修改导致的回退。

## 5.6 根路径规范化

本阶段建议将 `/` 到 `/latest` 改成永久 308。

验收：

- `/` 返回 308；
- Location 为 `/latest`；
- `/latest` 返回 200；
- sitemap 不包含 `/`；
- 所有 canonical 和内部品牌首页链接保持一致。

## 5.7 日报、周报、月报归档

### 日报

当前日期通过 `/daily?date=YYYY-MM-DD` 表达，技术上可以收录，但长期更推荐干净路径：

```text
/daily/2026-08-17
```

是否迁移应单独决策。如果迁移：

- 新路径返回 200；
- 旧查询参数 URL 永久跳转到新路径；
- sitemap 只放新路径；
- canonical 指向新路径；
- 不同时保留两套 200 页面。

如果本阶段不迁移，则保留当前 URL，但必须将真实日期 URL 放入 sitemap，并维持自引用 canonical。

### 周报和月报

为历史页面动态生成：

- 标题：带期数或时间；
- description：优先使用本期主线摘要；
- canonical；
- OG/Twitter；
- 结构化数据；
- 上一期、下一期内链。

示例：

```text
2026 年第 33 周 AI 周报：本周主线标题 · AI·RADAR
2026 年 8 月 AI 月报：本月主线标题 · AI·RADAR
```

## 6. P1：内容结构与长尾流量

## 6.1 正式主题落地页

建议稳定路径：

```text
/topics/openai
/topics/deepseek
/topics/claude
/topics/ai-agent
/topics/multimodal
/topics/open-source-models
```

也可以在数据成熟后拆出：

```text
/companies/{slug}
/models/{slug}
/sources/{slug}
```

但不建议一次创建大量薄页面。

### 收录门槛

专题页只有同时满足以下条件才 index：

- 主题定义稳定；
- 有唯一 slug；
- 至少有足够数量的有效事件，例如 8～10 条；
- 有最近更新内容；
- 有独立主题说明；
- 不是同义词或大小写造成的重复主题；
- 页面不会只展示一组没有解释的卡片。

### 页面组成

每个专题页建议包含：

1. 唯一 H1；
2. 100～300 字人工确认的主题说明；
3. 最近更新；
4. 重要事件或时间线；
5. 相关模型、公司和技术方向；
6. 相关专题内链；
7. 更新时间；
8. 数据和筛选口径说明。

不要把关键词机械重复到正文。关键词应自然体现在标题、说明、事件标题和内部链接中。

## 6.2 内部链接

建议增加：

- 详情页 breadcrumb；
- 详情页相关主题；
- 同公司、同模型、同技术方向的相关事件；
- 同一事件的后续进展；
- 日报到详情页；
- 详情页回到对应日报、周报或专题；
- 周报、月报的上一期与下一期。

内部链接文字应描述目标内容，不要全部写“查看详情”。

## 6.3 聚合内容的独特价值

AI·RADAR 不应仅依赖转载正文或通用摘要获得排名。长期可持续的独特价值应来自：

- 多信源折叠；
- 原始来源优先级；
- 为什么值得关注；
- 可信度和证据边界；
- 同一事件的后续变化；
- 对创作者和开发者的实际影响；
- 站内独有的主题时间线；
- 评分方法和入选依据。

详情页需要明确区分：

- 原始来源事实；
- AI 生成摘要或翻译；
- AI·RADAR 的筛选与判断；
- 不确定信息或待核实内容。

## 6.4 可信度页面

建议补齐或强化：

- 关于我们；
- 信源与筛选方法；
- AI 使用说明；
- 纠错与下架机制；
- 内容更新时间定义；
- 联系方式；
- 隐私说明；
- 编辑或发布责任主体。

不要虚构编辑人员、作者身份或人工审核流程。

## 7. P2：站长平台与主动提交

## 7.1 Google Search Console

建议优先验证 `suversal.com` Domain Property，以覆盖所有协议和子域。如果权限只覆盖当前站点，可先验证 URL-prefix Property：

```text
https://radar.suversal.com/
```

操作：

1. 添加站点并完成 DNS 验证；
2. 提交 `https://radar.suversal.com/sitemap.xml`；
3. 使用 URL Inspection 检查：
   - `/latest`
   - 一个事件详情页
   - 一期日报
   - 一期周报
   - 一个正式专题页
4. 检查 Live URL 是否能看到完整 HTML、canonical 和 JSON-LD；
5. 对少量代表 URL 请求编入索引；
6. 观察 Page indexing、Sitemaps、Core Web Vitals 和 Enhancements。

不要对每一个 URL 手工重复请求收录，也不要把 Google Indexing API 用于普通文章页。

## 7.2 Bing Webmaster Tools 与 IndexNow

操作：

1. 添加或从 Google Search Console 导入站点；
2. 提交 sitemap；
3. 部署 IndexNow key 文件；
4. 当页面新增、更新、删除或 canonical 变化时主动提交；
5. 批量提交只发送发生变化的 URL；
6. 在 Bing Webmaster Tools 中检查实际抓取与收录状态。

IndexNow 是发现通知，不保证排名和收录。

## 7.3 百度搜索资源平台

如果自然搜索目标包含中国大陆用户：

1. 验证 `radar.suversal.com`；
2. 提交 sitemap；
3. 配置普通收录 API 主动推送新增 URL；
4. 只推送公开 canonical URL；
5. 监控抓取异常、索引量和关键词展现；
6. 不向提交接口发送搜索参数页、隐藏内容或旧事件 ID。

平台的当前配额和接口要求应在接入时以控制台显示为准。

## 8. 指标与观测

## 8.1 收录指标

- Sitemap 已发现 URL 数；
- Sitemap 已编入索引 URL 数；
- “已抓取但未编入索引”；
- “已发现但未编入索引”；
- 重复网页和 canonical 冲突；
- 404、软 404、重定向错误；
- 每日新增事件从发布到首次抓取的时间；
- 每日新增事件从发布到首次展现的时间。

## 8.2 搜索表现

- 自然搜索曝光；
- 自然搜索点击；
- CTR；
- 平均排名；
- 品牌词与非品牌词占比；
- 事件页、报告页、专题页分别获得的曝光和点击；
- 带来有效阅读的查询，而不仅是总点击。

## 8.3 页面质量

- Core Web Vitals；
- 移动端 LCP、INP、CLS；
- 详情页首屏图片请求数量；
- HTML 和 RSC 响应体积；
- 图片代理错误率；
- 爬虫访问的 5xx、429 和挑战页比例。

## 8.4 分析工具

当前 Umami 可继续承担站内访问统计，但需要增加 SEO 分组：

- landing page 类型；
- referrer 搜索引擎；
- event/topic/report 页面类别；
- 首次访问后的原文跳转；
- 详情页到相关内容的继续阅读。

Search Console 负责搜索曝光和查询，Umami 负责进入站点后的行为，两者不要混为同一口径。

## 9. 分阶段实施计划

## 阶段一：P0 技术基础

建议包含：

1. 动态 sitemap；
2. 详情页 canonical 和文章级 metadata；
3. JSON-LD；
4. 搜索页和工具页 noindex；
5. 报告归档 metadata；
6. 图片可抓取路径；
7. 图片懒加载和尺寸；
8. `/` 改为 308；
9. 自动化测试和线上抽样验证。

完成后再向站长平台重新提交 sitemap。

## 阶段二：P1 内容结构

建议先选择 5～10 个长期稳定主题试点，不批量创建所有标签页。

试点完成后观察：

- 是否被抓取和收录；
- 是否出现非品牌曝光；
- 用户是否继续阅读详情；
- 是否产生大量重复或薄内容。

## 阶段三：P2 自动提交与迭代

- 接入 IndexNow；
- 评估百度主动推送；
- 建立每周 SEO 看板；
- 根据 Search Console 查询数据调整专题说明、标题和内链；
- 每月清理低质量、重复和无更新的专题页。

## 10. 测试建议

### 单元测试

- sitemap 过滤隐藏内容；
- sitemap 只输出 canonical ID；
- lastmod 使用真实字段；
- 详情 metadata 正确处理无摘要、无图片；
- 隐藏内容输出 noindex；
- 报告 metadata 包含正确期数；
- JSON-LD 转义用户或外部内容，不能产生无效脚本。

### 集成测试

- sitemap 所有抽样 URL 返回 200；
- canonical URL 与请求 URL 一致；
- 旧 ID 正确跳转；
- `/search?q=x` 保持 noindex；
- 管理员预览不被公开缓存；
- 图片 URL 可由匿名客户端读取；
- robots 不意外放开其他内部 API。

### 上线后验证

```bash
curl -sSIL https://radar.suversal.com/
curl -sS https://radar.suversal.com/robots.txt
curl -sS https://radar.suversal.com/sitemap.xml
curl -sS https://radar.suversal.com/event/<event-id>
```

同时检查：

- 页面源代码中的 title、description、canonical；
- Open Graph URL 和图片；
- JSON-LD；
- robots meta；
- 响应状态和重定向链；
- Rich Results Test；
- Search Console Live Test。

## 11. 风险与边界

### 11.1 不要一次索引所有筛选组合

`source`、`focus`、`tag`、`topic`、`q` 可以组合出大量 URL。直接允许所有参数页索引会产生重复和薄内容。只有正式专题页才能独立 index。

### 11.2 不要伪造更新时间

每次生成 sitemap 都写当前时间，会让搜索引擎认为所有页面都发生变化，最终削弱 `lastmod` 的可信度。

### 11.3 不要把结构化数据当成排名保证

结构化数据用于帮助理解页面和获得适用的富结果资格，不保证收录、富结果或排名。

### 11.4 不要把来源全文当成唯一 SEO 资产

如果页面主要复制来源正文，搜索引擎可能选择原始来源作为 canonical 或认为本站缺少增量价值。应强化多源整合、筛选理由、证据关系和后续跟踪。

### 11.5 不要为 SEO 削弱安全边界

图片可抓取不等于放开整个 `/api`；站长验证不应暴露密钥；管理员预览和缓存隔离必须继续保持。

## 12. 完成定义

P0 只有同时满足以下条件才算完成：

- 完整 sitemap 已上线并包含公开详情及报告归档；
- sitemap 不包含隐藏、旧 ID、空内容和工具页；
- 所有事件详情页都有自引用 canonical；
- 详情页输出文章级 OG/Twitter 信息；
- JSON-LD 通过验证；
- 搜索页和本地状态页不再进入索引；
- 搜索爬虫能够访问公开内容图片；
- 列表非首屏图片已懒加载；
- 根路径规范化已明确并验证；
- Google、Bing，及需要时百度站点验证完成；
- 站长平台成功读取 sitemap；
- 已建立至少四周的收录和曝光观测表。

## 13. 参考资料

- Google：构建和提交 Sitemap  
  <https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap>
- Google：Canonical URL  
  <https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls>
- Google：Article 结构化数据  
  <https://developers.google.com/search/docs/appearance/structured-data/article>
- Google：结构化数据通用规范  
  <https://developers.google.com/search/docs/appearance/structured-data/sd-policies>
- Google：Robots Meta Tag  
  <https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag>
- Google：图片 SEO  
  <https://developers.google.com/search/docs/appearance/google-images>
- Bing：URL Submission 与 IndexNow  
  <https://www.bing.com/webmasters/help/URL-Submission-62f2860b>
- IndexNow 官方文档  
  <https://www.indexnow.org/documentation>

## 14. 待审查决策

实施前需要确认：

1. `/` 永久跳转到 `/latest`，还是建设独立品牌首页；
2. 日报继续使用 `?date=`，还是迁移到 `/daily/YYYY-MM-DD`；
3. 详情页结构化数据采用 `Article` 还是部分内容采用 `NewsArticle`；
4. 图片采用站内持久化，还是提供受控的公开代理路径；
5. 第一批正式专题选择哪些主题；
6. 是否同步接入百度搜索资源平台；
7. 发布责任主体和作者字段采用什么真实身份。

