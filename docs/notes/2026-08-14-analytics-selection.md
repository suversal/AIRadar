# 访问统计与留存分析选型（2026-08-14）

一次性调查，写完定格。结论：**自托管 Umami**，脚本与上报走主域第一方路径，
面板走 `stats.suversal.com`。

## 为什么不是别的

站点在此之前**没有任何埋点**（全仓库搜不到一处 gtag/plausible/umami/posthog）。
诉求里"留存率"是硬指标，它把市面上多数轻量方案直接筛掉了。

| 方案 | 否决理由 |
|---|---|
| **GA4** | `google-analytics.com` / `googletagmanager.com` 在中国大陆被墙。读者主要在国内 → 数据到不了 Google，且被墙的请求会显著拖慢页面加载。数据与性能双输 |
| **Plausible** | 指标体系里**没有 cohort 留存**（官方 metrics-definitions 里只有跳出率/访问时长这类参与度指标）。自托管 CE 还要额外扛一个 ClickHouse，官方要求 ≥2GB RAM。功能不够 + 依赖更重 |
| **Cloudflare Web Analytics** | 数据只保留 30 天，且无留存/回访分析。算留存需要的时间跨度它天生给不了。可作为交叉校验的第二数据源 |
| **Matomo** | Cohorts 是付费插件（自托管 $229/年），本体是 PHP+MySQL，为一个报表引入整套异构栈不值 |
| **PostHog** | 功能最强（留存+cohort+session replay，免费 100 万事件/月），但对一个资讯站过重，`us.i.posthog.com` 国内同样不稳 |
| **Umami Cloud** | 功能与自托管同源，但脚本走 `cloud.umami.is` 第三方域名，国内访客可能加载失败 → 静默漏采 |

选 Umami 自托管的实际收益：内置按天 cohort 的留存报表、数据无限期保留、依赖只有一个
Postgres（无 ClickHouse/Redis）、MIT 免费，而且**脚本挂在自己域名下**——不被墙，
也不被 uBlock 一类按域名拦。

## 架构

```
访客浏览器
  ├── GET  radar.suversal.com/s.js        → nginx → umami:3000  （缓存 1d）
  └── POST radar.suversal.com/api/collect → nginx → umami:3000  （不缓存，api 档限流）
                                                     ↓
                                       postgres 实例内的**独立 umami 库**
                                                     ↑
看数据: stats.suversal.com（CF 橙云）→ nginx 具名 server 块 → umami:3000
```

两个刻意的设计：

1. **上报走主域，不走 stats 子域。** 子域名里带 `stats` 这类字样很容易被拦截器名单按域名
   收录，数据面一旦依赖它就会静默漏采。
2. **脚本名与上报路径都改掉了默认值**（`/s.js`、`/api/collect`，默认是 `/script.js`、
   `/api/send`，已被 EasyPrivacy 一类名单按路径收录）。三处必须一致：compose 的
   `TRACKER_SCRIPT_NAME`/`COLLECT_API_ENDPOINT`、`radar-cf.conf` 的两个精确 location、
   `analytics-script.tsx` 的 `SCRIPT_SRC`。

## 留存能看多远：读过源码后的真实边界

**这是本次调研最反直觉的一点，别被面板上的数字骗了。**

`src/queries/sql/reports/getRetention.ts` 里，cohort 与回访判定全部是
`group by website_event.session_id`，**完全不消费 `distinct_id`**。而 session_id 的生成是
（`src/app/api/send/route.ts`）：

```js
const saltRotation = process.env.SALT_ROTATION || 'month';   // 默认按自然月
const sessionSalt  = getSalt(saltRotation, createdAt);
const sessionId    = uuid(sourceId, ip, userAgent, sessionSalt);
```

于是：

- **面板的 Retention 只在同一个自然月内成立。** 跨月边界会断——月底首访的访客在下个月回访
  时 salt 已轮换、session_id 变了，会被当成全新访客，格子显示 0%。**那是假象，不是事实。**
- `getSalt` 源码里只有 `day` / `week` / `month` 三档（其它值一律 fallback 到 month），
  **month 已经是最长的一档**。不要为了"更隐私"改成 `day`，那等于把留存报表清零。
- 同一访客换个网络（IP 变了）也会被算成新人。这是无 cookie 方案的固有代价。

`umami.identify()` **修不了上面这条**——官方文档明确写着"设置 Distinct ID 不会合并会话，
每个设备/浏览器仍由 IP+UA+websiteId 独立标识"。

那为什么还要在 `analytics-script.tsx` 里存一个 localStorage UUID 并 identify？
因为它让 `session.distinct_id` 成为一个**跨月稳定**的标识，于是真正的跨月留存可以直接查库
算出来。面板看月内趋势，跨月留存用下面这条 SQL。

## 跨月留存 SQL

在 `umami` 库里跑（表 `session` 的主键列是 `session_id`，`distinct_id` 是 VarChar(50)）：

```sql
WITH cohorts AS (
  SELECT s.distinct_id,
         MIN((e.created_at AT TIME ZONE 'Asia/Shanghai')::date) AS cohort_date
  FROM website_event e
  JOIN session s ON s.session_id = e.session_id
  WHERE e.website_id = :website_id
    AND s.distinct_id IS NOT NULL
  GROUP BY s.distinct_id
),
activity AS (
  SELECT DISTINCT
         c.distinct_id,
         c.cohort_date,
         ((e.created_at AT TIME ZONE 'Asia/Shanghai')::date - c.cohort_date) AS day_number
  FROM website_event e
  JOIN session s ON s.session_id = e.session_id
  JOIN cohorts c ON c.distinct_id = s.distinct_id
  WHERE e.website_id = :website_id
)
SELECT cohort_date, day_number, COUNT(*) AS visitors
FROM activity
GROUP BY cohort_date, day_number
ORDER BY cohort_date, day_number;
```

口径差异要记住：这条 SQL 只覆盖**有 localStorage 的访客**（隐私模式下拿不到 ID，
那部分访客 `distinct_id` 为 NULL、不进这个统计），所以它的绝对值会低于面板的访客数，
但跨月趋势是可信的。

## 为什么埋点数据必须放独立库

`scripts/sync_db_to_server.sh` 是**整库替换**：本机 `pg_dump` 推上去建 `radar_new` →
rename 顶掉 `radar` → `DROP radar_old`。任何写进 `radar` 的埋点数据都会在下一次同步时
被连根丢掉。脚本只动 `radar*` 这三个名字，所以同一个 postgres 实例里另开一个 `umami` 库
是安全的，也省下再跑一份 postgres 的内存。

这不违反「Alembic 独占 schema」——那条不变式约束的是 `radar` 库；`umami` 的表由 Umami
自带的 Prisma migration 在首次启动时建，两者互不干涉。

## 面板本身的两个坑（3.3.0 实测）

- **`TWO_FACTOR_ENCRYPTION_KEY` 是必填**，不是"开了 2FA 才需要"。不配的话用户管理接口
  直接抛 `TWO_FACTOR_ENCRYPTION_KEY is missing or invalid`。64 字符 hex，`openssl rand -hex 32`。
- **建站入口是 `/websites`，不是 `/admin/websites`。** 后者是超管的全局视图、**没有创建按钮**，
  很容易以为是权限问题。另外 `/admin/users` 里的「编辑」点了没反应——实测无 JS 报错、
  无网络请求、DOM 无变化，是 3.3.0 自身的前端 bug（官方 issue 里没有对应记录）。
  改密码走 `/settings/profile`，不受这个 bug 影响。
- Website ID 在列表页看不到，要点进站点的设置页；或者直接查库：
  `docker exec infra-postgres-1 psql -U radar -d umami -tAc "SELECT website_id, name FROM website;"`

## 运维要点

- **`umami` 库要手动建一次**：`infra/postgres/init.sql` 只在数据卷首次初始化时执行，
  现有卷早已初始化过，改那个文件不会有任何效果。
  ```bash
  docker exec infra-postgres-1 psql -U radar -d postgres -c "CREATE DATABASE umami OWNER radar;"
  ```
- **`UMAMI_WEBSITE_ID` 改了要重建前端镜像**：它作为 build arg 传进 `next build` 被内联进
  产物（`infra/Dockerfile.web`）。不用运行时环境变量的原因是本站有静态预渲染页面
  （`/about`、`/agent`、`/changelog`、`/feedback` 等），运行时变量在构建阶段就把空值烘死了，
  那些页面会永远不埋点，而表现只是数字偏低、不报错——最难发现的失败模式。
- **`CLIENT_IP_HEADER: CF-Connecting-IP` 不能漏**：站在 CF+nginx 两层后面不配这个，
  所有访客会被算成同一个人，留存直接失真且不报错。
- **首次登录后立刻改密码**：Umami 默认账号 `admin` / `umami`。
- **面板依赖 CF DNS 里 `stats` 那条 A 记录开橙云代理**：不开则回源不来自 CF 网段，
  `radar-cf.conf` 里的 `$from_cloudflare` 判据直接 403。这是有意的失败方向——
  配错了是打不开，不是敞开。
- 面板与主站共用同一份 CF Origin CA 证书：SAN 是 `*.suversal.com` + `suversal.com`
  （2026-08-14 实测，有效期至 2041），已覆盖新子域，不需要另签。

## 一手来源

留存与 salt 轮换的结论来自源码，不是文档（文档没写）：
- `umami-software/umami` → `src/queries/sql/reports/getRetention.ts`、
  `src/app/api/send/route.ts`、`src/lib/crypto.ts`、`prisma/schema.prisma`
- Distinct ID 语义：https://docs.umami.is/docs/distinct-ids
- Tracker 函数签名（`identify(unique_id: string)`）：https://docs.umami.is/docs/tracker-functions
