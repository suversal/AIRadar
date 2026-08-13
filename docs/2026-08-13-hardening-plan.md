# AR 抗压与安全加固计划（2026-08-13）

> **起因**：AIHOT 作者卡兹克发了[《我的网站被攻击了 48 个小时》](https://mp.weixin.qq.com/s/mvVVvlIF_rZISGXtsI7Igw)，
> 记录了 `#TeamAntiAI` 对他的 AI 资讯站发起的两波攻击，共约 2000 万请求。
> AR（radar.suversal.com）是同类型、同体量、同样公开的站点，把他被打的每一处对着 AR 查了一遍，
> 发现**他被打穿的四种打法里，我们中了三种**，而且其中两种比他更脆。
>
> 本文既是施工图，也是复盘材料：每一条都写清 **问题 / 证据 / 修法 / 为什么这么修 / 怎么验证 / 怎么回滚**。
>
> **怎么读这份文档**：
>
> - 想知道**每项改动做了什么、为什么、有什么用、代价是什么** → 直接看 **第十节「改动全览」**，
>   那是按流量分层组织的系统性说明，也包含总体代价、必须人工同步的耦合点清单。
> - 想知道**当初为什么要做这件事** → 第零节结论 + 第一节威胁模型。
> - 想**照着施工** → 第二节实施计划（含 nginx 配置与验证命令）+ 第四节 Cloudflare 控制台步骤。
> - 想看**踩了哪些坑** → 第八节四次事故，以及各节里的 ⚠ 警告框。
> - **真被打了** → 第三节 5 分钟处置流程。
>
> 前置说明：腾讯云 175.24.182.233 **已于 2026-08-13 关机**，本计划只针对 greenvps。
>
> 文中几处引用的 `docs/greenvps-deployment.md` 是**本机运维手册**，含服务器地址、
> SSH 端口与账号，按 `.gitignore` 排除在仓库之外（与 `scripts/deploy_to_server.sh`
> 等六个脚本同一理由），所以在公开仓库里看不到它——这是有意的，不是漏传。

---

## 零、一页纸结论

| # | 问题 | 严重度 | 现状 | 对应他文章里的哪一段 |
|---|---|---|---|---|
| 1 | 全部公开页面零缓存，每个请求都现场 SSR + 查库 | 🔴 P0 | 实测 `cache-control: no-store` + `cf-cache-status: DYNAMIC` | "专挑最贵的页面 + 随机参数骗缓存" |
| 2 | `/api/image-proxy` 是开放代理（任意 URL） | 🔴 P0 | 实测可代取任意外网图片 | "236 万个请求灌图片接口" |
| 3 | 反馈接口无限流无去重，且每条同步推 Telegram | 🔴 P0 | 代码确认 | "3 万条垃圾灌库，飞书群爆炸" |
| 4 | 全站没有任何限流层 | 🟠 P1 | 全仓库无 `limit_req` / slowapi | "多 IP 协同，每个都压在限流线下" |
| 5 | 列表接口 `limit`/`days` 无服务端上限 | 🟠 P1 | `limit: int = 50`，无 `Query(le=)` | —（我们独有的放大器） |
| 6 | nginx 并发上限 2048、web 容器 384MB | 🟠 P1 | 已确认 | "nginx 768 并发被握满，全站瘫痪" |
| 7 | 访问日志不留存、无告警 | 🟡 P2 | docker 默认 json-file 无 rotation | "日志留存拉到一年，为了取证" |
| 8 | `/admin/login` 无失败限流；cookie 缺 `secure` | 🟡 P2 | 代码确认 | —（他没提，我们该补） |
| 9 | 我们是**抓 AIHOT 的那一方**，对方已上自动封禁 | 🟡 P2 | crawler 静默降级，无告警 | "盗采爬虫做镜像站，全封了" |

**我们比他强的地方**（不要动，这是已经付过学费的资产）：

- greenvps 是**独占机器**，只有 5 个容器。他最致命的那一条——"整机 30+ 个项目，只有自己那个做了防护，攻击者绕道打隔壁"——我们结构上不存在。
- 已在 Cloudflare 后面 + 源站只放行 CF IP（`geo $realip_remote_addr`）+ Full (strict)。他当时是裸源站。
- Postgres 已绑 `127.0.0.1`。

**一句话总结**：他缺的是**边界**，我们缺的是**边界之内的成本控制**。
CF 挡得住流量的"量"，挡不住我们自己每个请求都很贵这件事。

---

## 一、威胁模型：攻击者会怎么打 AR

按他文章里那两波的实际打法，套到 AR 上：

```
第一波（单 IP 莽夫，5:30 起）
  踩点 → 拿到我们页面上的真实图片链接清单
  → 猛灌 /api/image-proxy
  → 我们每收 1 个请求就发起 1 次外网 fetch（他至少是读本地缓存文件）
  → 出口带宽 + 连接数双爆

第二波（多 IP 协同，深夜 0:30 起）
  每 IP 频率压在限流线下 → 我们连线都没画，任何频率都是"合规"的
  → 专打 /latest /all /search（无缓存、要查库、要 SSR）
  → 加随机参数 → 我们本来就不缓存，连"骗"这一步都省了
  → Next 渲染队列堆积 → 真实用户排队几十秒 → 全站体感瘫痪

同步骚扰
  → 灌 /api/feedback → 垃圾进库 + Telegram 通知通道被打死
```

**关键判断**：AR 的瓶颈不是带宽，是**单请求成本**。
2 核 / 3.8G，web 容器限 384MB，`/api/all-events?limit=50&days=30` 实测 **1.2~3.3 秒、122KB**。
不需要 340 倍的峰值，几十 QPS 持续打就够我们难受。所以**第一优先级是把单请求成本降下来**，而不是先去堆防护规则。

---

## 二、实施计划

四个阶段，按"收益/风险比"排序。**阶段 1 即使永远不被攻击也该做**——它是纯性能收益。

---

### 阶段 1 · 把请求变便宜（P0）

#### 1.1 问题：所有公开页面零缓存

**证据**（2026-08-13 线上实测）：

```
/latest  /all  /daily  /search  /x  /telegram
  cache-control: private, no-cache, no-store, max-age=0, must-revalidate
  cf-cache-status: DYNAMIC
```

**根因**：`apps/web/lib/api.ts` 里 **12 处** 数据获取全部硬写了 `cache: "no-store"`
（行 242 / 289 / 419 / 450 / 486 / 520 / 541 / 555 / 570 / 585 / 701 / 717）。
这既让 Next 的 Data Cache 完全失效，又把页面钉死成动态渲染，
Next 于是给出 `no-store` 响应头，**Cloudflare 和任何中间层都不敢缓存**。

结果：一个访客请求 = 一次完整 SSR + 一次 API 调用 + 一次数据库查询。CF 一份都没帮我们扛。

> 这条是历史包袱：早期本地开发时为了"改了数据立刻能看到"而加，之后一直没收。

**修法（三层，从上到下依次生效）**

**① nginx 反向代理缓存**——收益最大、和 Next 语义无关，直接缓存渲染好的 HTML。

新增 `infra/nginx/00-hardening.conf`（http 上下文）：

```nginx
proxy_cache_path /var/cache/nginx/radar levels=1:2 keys_zone=radar:20m
                 max_size=1g inactive=10m use_temp_path=off;
```

在 `radar-cf.conf` 的公开 location 里：

```nginx
proxy_cache            radar;
proxy_cache_valid      200 301 302 180s;
proxy_cache_valid      404 10s;
proxy_cache_lock       on;          # ← 他文章里的"合单"：100 个人同时要同一页，只放 1 个进后厨
proxy_cache_lock_timeout 10s;
proxy_cache_use_stale  updating error timeout http_500 http_502 http_503 http_504;
proxy_ignore_headers   Cache-Control Expires Set-Cookie;
proxy_cache_bypass     $cookie_admin_token;   # 管理员永远看实时数据
proxy_no_cache         $cookie_admin_token;
add_header X-Cache-Status $upstream_cache_status always;   # 便于验证
```

> `proxy_cache_use_stale updating` 顺带解决另一个老问题：数据整库同步时那 2~3 秒的
> "API 服务暂时不可用"，现在会被过期缓存兜住，用户根本看不到。

**② 缓存键忽略未知参数**——他那晚"真正的胜负手"。

不能直接用 `$args` 做键（那样随机参数照样穿透）。做法是白名单规范化：

```nginx
# 00-hardening.conf，每个允许的参数一条 map
map $arg_q        $ck_q        { default "";  "~^.{1,64}$"  "q=$arg_q&"; }
map $arg_category $ck_category { default "";  "~^[a-z_-]{1,32}$" "category=$arg_category&"; }
# … focus / tag / topic / source / kind / handle / channel / date / offset 同理
```

```nginx
# radar-cf.conf，公开 location 内
set $ckey "$ck_q$ck_category$ck_focus$ck_tag$ck_topic$ck_source$ck_kind$ck_handle$ck_channel$ck_date$ck_offset";
proxy_cache_key "$scheme$host$uri?$ckey";
```

> **⚠ 施工时改过一次设计，这段是复盘重点。**
>
> 原方案是"只规范化缓存键，请求仍原样回源"。本地功能测试时发现这会开出一个**缓存投毒**的口子：
> 攻击者请求 `/latest?q=<200 个字符的超长串>`，这个 `q` 不匹配白名单正则、
> 于是不进缓存键，但**它照样被发给了上游** —— 上游按这个查询返回了搜索结果，
> 而这份结果被存进了"没有 q 参数"的那个键里。
> 之后所有访问 `/latest` 的人，看到的都是攻击者那次搜索的结果。
>
> 修正后的设计：**规范化结果既是缓存键，也是真正发给上游的查询串**
> （`proxy_pass http://web:3000$uri?$ckey;`）。名单外参数和非法值在进入 Next 之前
> 就被丢掉，"键"和"内容"在结构上不可能不一致。
>
> 教训：任何"用 A 做键、拿 B 去取内容"的缓存设计，只要 A 和 B 能被分别控制，就是投毒面。
> 让它们是同一个值，比事后校验可靠得多。
>
> 丢弃参数是安全的：Next 页面只读自己声明的 `searchParams`；
> `utm_*` / `gclid` 这类只在浏览器里被读取，用户地址栏不受影响。

**完整参数白名单**（已逐页核对 `searchParams` 类型定义**与各 API route 实际读取的参数**）：

| 页面 | 参数 |
|---|---|
| `/latest` | `focus` `category` `q` `tag` |
| `/all` | `source` `focus` `category` `q` `tag` `topic` |
| `/daily` | `date` |
| `/search` | `q` |
| `/x` | `kind` `handle` `topic` `offset` |
| `/telegram` | `channel` |
| `/event/[id]` `/topics` `/weekly/[key]` `/monthly/[key]` | 无 |
| `/api/latest-events` | `limit` `offset` `category` `focus` `tag` `q` |
| `/api/all-events` | `days` `limit` `offset` `category` `focus` `source` `tag` `topic` `q` |
| `/api/telegram-events` | `days` `limit` `offset` `channel` |

> **第二个施工期发现**：初版白名单只看了页面的 `searchParams`，漏了 API route 的
> `limit` / `days`。后果是 `?limit=50` 和 `?limit=100` 共用一份缓存，
> **"加载更多"会永远返回第一页**。本地测试用例里加了翻页独立性检查才逮到。
> 教训：白名单要覆盖"所有会读参数的地方"，页面和 API route 是两套入口。

白名单外的参数（`?x=随机数`）不进缓存键 → 全部命中同一份缓存 → **随机参数攻击当场失效**。
正则同时限制了长度和字符集，超长/怪字符的参数会被规范化掉，顺带压掉一批探测流量。

**③ Next 数据层缓存**——省掉 API 与数据库那一跳。

把 `lib/api.ts` 的 `cache: "no-store"` 换成 `next: { revalidate: N }`：

| 函数 | revalidate | 理由 |
|---|---|---|
| `getLatestReport` `getHotspots` `getAllEvents` `getTelegramEvents` `getTweets` | 60s | 首页流量最大，1 分钟新鲜度足够 |
| `getEventDetail` `getTweet` `getDailyReport` `getPeriodReport` | 300s | 详情页发布后基本不变 |
| `getTopics` `getPeriodArchive` `getDailyArchive` | 600s | 归档/分类，变化极慢 |

已用 context7 核对 Next 16.2.10 语义：本项目未开启 `cacheComponents`，
`next: { revalidate }` 走经典 Data Cache，在动态渲染的页面里同样生效。

**新鲜度代价（必须写清楚，这是取舍不是 bug）**：三层叠加后，
最坏情况下用户看到的数据比数据库落后 **nginx 180s + Next 60s ≈ 4 分钟**。
AR 是资讯聚合站，数据本身来自每天几次的 pipeline 推送，4 分钟无感。
他文章里也是同样的取舍（60s → 3min）。**管理后台不受影响**（`proxy_cache_bypass`）。

**必须排除缓存的路径**（漏一条就是事故）：

```
/admin/*                  管理界面
/api/admin-proxy/*        管理 API 代理
/api/admin-upload-image   上传
/api/refresh-latest       手动触发刷新
/api/feedback             写接口
/_next/static/*           已有 immutable 头，直接放行不进 cache zone
```

**验证**

```bash
# 第一次 MISS，第二次 HIT
curl -sI https://radar.suversal.com/latest | grep -i x-cache-status
curl -sI https://radar.suversal.com/latest | grep -i x-cache-status

# 随机参数必须也是 HIT（证明规范化生效）
curl -sI "https://radar.suversal.com/latest?zzz=$RANDOM" | grep -i x-cache-status

# 真实过滤参数必须是独立的 key（第一次 MISS）
curl -sI "https://radar.suversal.com/latest?category=tutorial" | grep -i x-cache-status

# 管理后台必须永远 BYPASS
curl -sI -H "Cookie: admin_token=x" https://radar.suversal.com/latest | grep -i x-cache-status
```

**回滚**：注释掉 `proxy_cache` 一行 + `docker restart infra-nginx-1`，30 秒回到现状。
Next 那层回滚 = `git revert` 单个 commit。三层互相独立，可以分别回。

---

#### 1.2 问题：`/api/image-proxy` 是开放代理

**证据**：`apps/web/app/api/image-proxy/route.ts:37` 只校验协议，`url` 参数无任何限制。

```bash
curl "https://radar.suversal.com/api/image-proxy?url=<任意外网图片>"   # → 200
```

**三重危害**

1. **带宽白嫖**：任何人都能拿 AR 当图片中转。他那 236 万次图片请求落到我们这是
   **236 万次出站 fetch**——他至少是读本地缓存文件，我们比他贵一个量级。
2. **天然穿透缓存**：每个不同 `url` 就是一个新缓存键，这是现成的"骗缓存"入口，
   而且 1.1 里的参数白名单救不了它（`url` 是它的合法参数）。
3. **SSRF**：可探内网与云元数据。虽然响应被限制成 `image/*`，
   但**状态码与耗时差异足以做端口扫描**。

**修法：四层，全部不改变正常用户的可见行为**

**① 拒绝非公网目标（堵 SSRF）**
解析主机名后校验 IP，命中以下网段一律 400：
`127/8` `10/8` `172.16/12` `192.168/16` `169.254/16`（云元数据）`::1` `fc00::/7` `fe80::/10`，
以及 `localhost` 等本地名。**跟随重定向时每一跳都要重新校验**（否则 302 到内网就绕过了）。

**② 软性域名分级（不是硬白名单，避免误伤）**

- 从数据里派生一份「已知图床」清单，写进 `apps/web/lib/image-hosts.ts`；
  当前样本：`img.ithome.com` `s3.ifanr.com` `imgopt.infoq.com` `static001.geekbang.org`
  `mmbiz.qpic.cn` `cdn*.telesco.pe` `aihot.virxact.com` 等。
- **命中清单** → 走宽松限流档；**未命中** → 走严格限流档 + 记一条日志。
- **不直接 403 未知域名**：新信源随时会带来新图床，硬白名单会造成"图片突然全白"的
  产品事故，而且是静默的。分级既抬高了滥用成本，又不会误伤。

> 更强的方案是 HMAC 签名（服务端签，route 验签，彻底杜绝开放代理）。
> **本次不做**：`author-avatar.tsx` `tweet-card.tsx` `article-reading-toggle.tsx`
> 都是 client component，拿不到 secret，要做就得把签名下沉到 `lib/api.ts` 的
> payload 改写层，涉及 `image.url` / `fallback_url` / `poster_url` / media 数组等
> 多个字段，改动面和回归风险都远大于收益。列入「以后可选」。

**③ 收紧资源占用**：超时 15s → 8s；响应体积上限 8MB（超出即断流），拒绝非 GET。

**④ nginx 层给它独立缓存 + 独立限流**（见阶段 2）。
它本来就返回 `Cache-Control: public, max-age=86400, immutable`，
缓存住之后重复请求直接命中，不再出站。

**验证**

```bash
curl -o /dev/null -w "%{http_code}\n" "https://radar.suversal.com/api/image-proxy?url=http://127.0.0.1:8000/"        # 400
curl -o /dev/null -w "%{http_code}\n" "https://radar.suversal.com/api/image-proxy?url=http://169.254.169.254/"       # 400
curl -o /dev/null -w "%{http_code}\n" "https://radar.suversal.com/api/image-proxy?url=https://img.ithome.com/<真图>"  # 200
# 回归：随手翻 /latest /event/xxx /x，图片不能有白块
```

**回滚**：单文件 `git revert`。

---

#### 1.3 问题：反馈接口是"3 万条垃圾"的完全翻版，且我们更脆

**证据**：`apps/api/app/main.py:647` `submit_feedback` —— 无限流、无验证码、无去重，
只校验长度；**第 668 行每条反馈同步 `send_telegram_message`**。

他被打爆的是飞书群。我们更糟：**Telegram Bot API 自己有速率限制**，
被灌到一定量会把整条通知通道打死甚至封 bot——而这条通道还兼着 AR 的其它告警。

**修法**

| 层 | 措施 |
|---|---|
| nginx | `/api/feedback` 单独限流：`rate=6r/m burst=3 nodelay` + `limit_conn 2` |
| web | `apps/web/app/api/feedback/route.ts` 把 `X-Real-IP` 透传给后端（后端现在拿不到真实 IP） |
| api | 同 IP 10 分钟内 > 3 条 → 直接返回 `{ok:true}` 但不入库（**静默丢弃，不给攻击者反馈信号**） |
| api | 内容去重：10 分钟内完全相同的 message 不重复入库 |
| api | Telegram 预算：每小时最多单条推送 20 次；超出后只入库不推送，第 20 条上带一句提醒 |

> **施工时的一处方案调整**：原计划写的是"同 IP 10 分钟 > 3 条"，实现时改成了
> **全局总量上限**（10 分钟 30 条）。原因：`feedback_submissions` 表没有 IP 字段，
> 要做 per-IP 就得加列 + 迁移，而 per-IP 这件事 nginx 那层已经做了（`strict` 档 6r/m）。
> 更关键的是——他文章里第二波攻击的要害正是**多 IP 协同、每个 IP 都压在限流线下**，
> 那种情况下 per-IP 计数天然失效，只有全局总量拦得住。所以这两层是互补的：
> nginx 挡单点高频，API 挡分布式低频。
>
> 计数直接查表（`count_feedback_since`），不引入 Redis 或内存计数器：
> 表本来就在，而且计数天然跨进程、跨重启——攻击者不会因为我们重启一次 api
> 就白拿一个干净的窗口。

> **为什么超限返回 200 而不是 429**：429 是给攻击者的调试信息，他能据此二分出限流阈值——
> 这正是他文章里第二波"每个 IP 精准压在限流红线下"的前提。静默丢弃让对方无法校准。
> 真实用户几乎不可能触发（10 分钟 3 条）。

**验证**：脚本连发 10 条 → 前 3 条入库、后 7 条 200 但库里没有、Telegram 只响 3 次。

---

### 阶段 2 · 画出限流线（P1）

#### 2.1 问题：全站没有任何限流

**证据**：全仓库搜不到 `limit_req` / `limit_conn` / slowapi / 任何 throttle。nginx 只做转发。

他第二波的打法是"多 IP 协同，每个 IP 精准压在限流线下"——**我们连那条线都没有**，
任何频率对我们都是合规的。

**修法**：全部放在 nginx 层。
后端 API 只在 docker 内网可达（`AI_RADAR_API_BASE_URL=http://api:8000`），
所有外部流量必经 nginx，**一层限流就能覆盖全部入口**，不需要在 FastAPI 里再做一套。

`00-hardening.conf`：

```nginx
limit_req_zone  $binary_remote_addr zone=pages:10m  rate=60r/m;
limit_req_zone  $binary_remote_addr zone=api:10m    rate=120r/m;
limit_req_zone  $binary_remote_addr zone=imgproxy:10m rate=300r/m;
limit_req_zone  $binary_remote_addr zone=strict:10m rate=6r/m;    # 反馈 / 登录 / 未知图床
limit_conn_zone $binary_remote_addr zone=perip:10m;
limit_req_status 429;
limit_conn_status 429;
```

**关键前提**：`cloudflare-ips.conf` 已经做了 real_ip 还原，
所以 `$binary_remote_addr` 拿到的是**真实访客 IP 而不是 CF 的 IP**——
否则所有流量会被算成同几个 CF 出口地址，限流要么全放要么全杀。这条是 realip 已有配置带来的红利。

**阈值取值理由**：正常用户浏览一个列表页会连带触发 10~30 个子请求
（图片、`/_next/static`、翻页 API），所以页面档 60r/m 是"每秒 1 页"的量级，
真人手速远达不到；图片档放宽到 300r/m 是因为一屏就可能有几十张图。
`burst` 一律配 `nodelay`，保证突发不误伤首屏加载。

**静态资源完全不挂限流**：一个页面会带出几十个 `/_next/static` 请求，
挂上去只会误伤真实用户，而它们本身既便宜又长缓存。

**返回 429 而不是默认的 503**：503 会让 Cloudflare 以为源站挂了。

**本地实测（每档连发到超限为止）**：

| 档 | 路径 | 连发 | 通过 | 限流 | 与设计值 |
|---|---|---|---|---|---|
| strict | `/api/feedback` | 12 | 4 | 8 | burst 3 + 1 ✓ |
| pages | `/latest` | 45 | 31 | 14 | burst 30 + 1 ✓ |
| api | `/api/all-events` | 80 | 63 | 17 | burst 60 + 补充 ✓ |
| imgproxy | `/api/image-proxy` | 130 | 109 | 21 | burst 100 + 补充 ✓ |
| 无 | `/_next/static/a.js` | 200 | 200 | 0 | 不限流 ✓ |

> **一个差点被误读的结果**：测试里 `/admin/login` 一开始显示"12 发 0 通过"，
> 看着像配置写错了。实际原因是 `limit_req_zone` 的键是 `$binary_remote_addr`，
> **每个 IP 有自己独立的桶**，而前一个用例已经把我这台机器的 strict 配额耗光了。
> 换一个来源 IP 复验，立刻恢复成 4 通过 / 8 限流。
>
> 顺带确认了一条很重要的性质：**攻击者刷爆自己的桶，不会影响其他访客**。
> 但这条性质完全依赖 `cloudflare-ips.conf` 的 real_ip 还原 ——
> 一旦 real_ip 失效，所有人会被算到那十几个 CF 出口 IP 上共用一个桶，
> 结果就是**全站 429**。改动 `cloudflare-ips.conf` 时必须记得这个连带关系。

#### 2.2 问题：`limit` / `days` 的边界处理

> **⚠ 这一条的判断在施工时被推翻了一半，原文保留在下面，作为"只看签名不看函数体"的教训。**
>
> **原判断**：`apps/api/app/main.py:257` 等处是裸 `limit: int = 50`、没有 `Query(le=...)`，
> 所以后端无上限，`?limit=100000` 是廉价放大器。
>
> **实际情况**：后端**每一个**公开端点在函数体里都做了显式校验并抛 400 ——
> `latest`(265)、`events`(313)、`telegram`(377)、`hotspots`(434)、`topics`(458)、
> `tweets`(476)，两个 admin 端点也各自 clamp 过。参数上限一直是有的，
> 只是没写在签名里而是写在函数体第一行，我当时 grep 签名就下了结论。

**那真正的问题是什么**：`?limit=1000` 在线上表现为"页面正常打开、一条内容都没有"。
链路是这样的——

```
?limit=1000
  → apps/web/app/api/all-events/route.ts  原样透传（Number(x) || 50 只挡 NaN）
  → 后端校验不通过，返回 400
  → lib/api.ts 在 !response.ok 时返回一个空 payload（这是它一贯的降级策略）
  → route handler 把空 payload 当成正常结果返回 200
  → 页面渲染成"暂无内容"
```

不是安全问题，是**排障地狱**：没有报错、没有非 200、日志里也看不出异常，
只有一个空列表。真出问题时这种"静默降级"比直接报错难查得多。

**修法**：新增 `apps/web/lib/query-params.ts` 的 `clampInt()`，在 web 层就把值收敛到
与后端一致的区间（`limit` 1–200、`days` 1–90、`offset` ≥ 0），
三个 route handler 全部换掉裸 `Number(x) || N`。越界值收敛而不是透传，
既不会触发后端 400，也就不会变成空页面。

顺带修掉 `Number(x) || N` 自身的毛病：`Number("")` 是 0、`Number("abc")` 是 NaN，
`|| 50` 会把它们**和显式的 `?limit=0` 一起**静默变成 50。

本地跑了 13 条边界用例（缺省 / 空串 / 非数字 / 0 / 负数 / 超上界 / 小数 /
`Infinity` / `NaN` / 科学计数法），全部通过。

#### 2.3 问题：容量天花板

**证据**：nginx `worker_processes auto`（2 核）× `worker_connections 1024` = **2048 并发**。
比他那台的 768 好，但同样是天花板。web 容器限 384MB、api 512MB。

**修法**：`worker_connections` 提到 8192（需要挂一份自定义 `nginx.conf`，
官方镜像默认只挂 `conf.d/`）。**注意这只是把天花板抬高，
真正的解法是阶段 1 把单请求变便宜**——否则连接数上去了只是让更多人一起排队。

优先级低于阶段 1，做完阶段 1 后重新压测再决定要不要动。

---

### 阶段 3 · 看得见 + 出事能查（P2）

#### 3.1 问题：日志不留存、无告警

他能复盘出"4:48 踩点 → 5:30 起量 → 6:05 峰值 87 万/分"这条完整链路，
靠的是访问日志；事后他把留存拉到一年，"为了可能取证需要"。

我们现在：nginx access log → docker 默认 json-file，**无 rotation、无留存策略、无人看**。
真被打了，事后什么都查不到。

**修法**

- `docker-compose.prod.yml` 给每个服务加
  `logging: driver: json-file, options: {max-size: 50m, max-file: "20"}`
  （nginx 约 1GB 日志容量，够存很久）。
- nginx 自定义 `log_format`，补上真实 IP、`$request_time`、`$upstream_cache_status`、
  `CF-Ray`、User-Agent。**没有 `$upstream_cache_status` 就无法判断缓存是否真的在生效**，
  这是阶段 1 的验收依据。
- 一条速查脚本 `scripts/traffic_top.sh`：按 IP / UA / 路径出 Top N，出事时第一时间跑。

#### 3.2 问题：`/admin/login` 无失败限流；cookie 缺 `secure`

- token 比较本身是 constant-time 的（`main.py:226` 用了 `secrets.compare_digest`），**这点没问题**。
- 但登录可无限次尝试 → nginx `strict` 档限流兜住。
- `apps/web/app/admin/login/page.tsx:22` 的 cookie 缺 `secure: true`。
  当前链路全程 HTTPS，实际风险低，但**没有理由不加**。

#### 3.3 问题：我们是"被封的那一方"

他文章最后一段：*"顺道手还挖出了一些长期潜伏的盗采爬虫，无时无刻不在爬我们的数据做了镜像站，
核实完特征以后全封了。"*

AR 的 `aihot_feed` / `aihot_all` 两个信源会抓 `aihot.virxact.com/items/{id}` 的**整页正文
外加他自己做的中英翻译**（`apps/api/app/crawlers/aihot_content.py`），展示在 AR 上。

技术上我们是规矩的：UA 写死 `HotAI/1.0`（`aihot_content.py:53`），
按对方 API 文档"脚本和后端服务必须设置能识别自己的非浏览器 User-Agent"的要求标明了身份，
2026-08-13 实测他的 feed 对我们仍返回 200。

**但风险是真的**，且分两类：

1. **技术风险（本计划处理）**：他已上自动封禁策略。我们一旦被划进去，
   这个 crawler 是 best-effort 设计（**不抛异常、静默降级**成中文-only 甚至空），
   **不会有任何信号**。
   → 修法：pipeline 跑完后检查 `sources.last_crawl_result`，
   对 `aihot_*` 连续失败 / 抓取量骤降的情况推 Telegram 告警。
2. **产品与关系风险（本计划不处理，需要你定）**："抓全文 + 抓译文 + 自己展示"
   离对方眼里的"镜像站"很近。这是取舍不是 bug，我不替你决定。
   可选方向：只取标题+摘要+原文链接、不取他的译文、或主动去打个招呼。

---

### 阶段 4 · Cloudflare 控制台（需要你操作，我改不了）

代码和服务器我能改，CF 控制台的开关只有你能点。
以下配额与能力已于 2026-08-13 逐条核对过 CF 官方文档，均为 **Free 计划**实际可用。

**为什么这一步的收益比 nginx 那层还大**：nginx 缓存只挡到源站门口，
访客的请求仍然要从他所在的 CF 边缘一路跑到圣何塞。实测从国内看站点仍是 1.6~6.1 秒，
而源站自己只花 0.000s —— **时间几乎全花在路上**。而 CF **默认不缓存 HTML**，
必须显式建 Cache Rule，它才会在边缘直接返回。

#### ⚠ 先理解这个坑：CF 缓存 HTML 会撞上 Next.js 的 RSC

同一个 URL，Next 会返回两种完全不同的东西：

- 浏览器直接访问 → HTML
- 站内点链接跳转 → RSC payload（请求带 `RSC: 1` 头）

源站用响应头 `Vary: rsc, next-router-state-tree, ...` 声明了这件事，nginx 认这个头
（所以 §1.1 里 RSC 请求直接 BYPASS）。**但 CF 默认只用 URL 构造缓存键，
忽略源站的 `Vary`** —— 官方文档：缓存键由 URL 加少数几个特定头构成，
Cache Rules 的 `vary` 配置默认关闭。

后果：CF 可能把 HTML 缓存下来，再拿它去响应一个 RSC 请求，**站内跳转会白屏**。

所以下面规则 3 里排除 RSC 的条件不是可选项。

#### ⚠ 免费版 Edge TTL 最小 2 小时 —— 所以时长由源站给，不在 CF 里设

第一版这里写的是"Edge TTL 选 Ignore cache-control → 1 分钟 / 2 分钟"，
**照着做会失败**：Free 计划的 **Minimum Edge Cache TTL 是 2 小时**，
下拉框里根本没有分钟级选项。2026-08-13 实配时才发现，当时规则 2、3 建完，
`cf-cache-status` 依旧是 `DYNAMIC`。

而 2 小时对资讯站太长——新文章两小时才出现。

**解法**：CF 的 **Origin Cache Control** 在 Free/Pro/Business 上**默认开启**，
会严格遵守源站发来的 `Cache-Control`。那个 2 小时下限只约束**控制台下拉框里的档位**，
不约束源站自己给的值。所以时长收回到 nginx 里给：

| 路径 | 源站发的头 | 效果 |
|---|---|---|
| 公开页面 | `public, s-maxage=120, max-age=0, must-revalidate` | CF 边缘缓存 2 分钟；浏览器每次回来问 |
| 公开只读 API | `public, s-maxage=60, max-age=0, must-revalidate` | 同上，1 分钟 |
| 管理员 / RSC 请求 | `private, no-cache, no-store, ...` | CF 绝不缓存 |
| `/_next/static` | 保持 Next 自己的 `immutable` 不动 | 长缓存 |

`s-maxage` 只对共享缓存（CF）生效，浏览器忽略它；`max-age=0, must-revalidate`
则保证浏览器不会攥着一份旧 HTML 刷不掉。实现见
`infra/nginx/edge-cacheable-page.conf` / `edge-cacheable-api.conf`
与 `00-hardening.conf` 第三点五节。

**于是 CF 侧的 Edge TTL 一律选第一项**
「Use cache-control header if present, bypass cache if not」，
不要选「Ignore cache-control header and use this TTL」。

#### 实测：CF 确实按源站的 s-maxage 走（2026-08-13 验证）

"源站发短 TTL 能绕开免费版 2 小时下限"这件事，文档没有明说，所以上线后采了 4 分钟：

    age=88 → 104 → 119 → EXPIRED → 15 → 31 → 46 → ...

`age` 涨到 119 秒就过期回源、然后归零重来，周期正好是 `s-maxage=120`。
**结论：那个"最小 Edge Cache TTL 2 小时"只约束控制台下拉框的档位，
不约束源站自己发的 `Cache-Control`。**

#### 规则 1：缓存图片代理（收益最大，零风险）

`/api/image-proxy` 是全站最贵的接口——每个请求都是一次出站 fetch。
它没有 RSC 变体，缓存它不会有上面那个问题。

- 位置：**Caching → Cache Rules → Create rule**
- 表达式：`starts_with(http.request.uri.path, "/api/image-proxy")`
- Cache eligibility：**Eligible for cache**
- Edge TTL：**Use cache-control header if present, bypass cache if not**
  （源站已经发 `public, max-age=86400, immutable`，CF 照做即可）
- Browser TTL：Respect origin

#### 规则 2：缓存公开只读 API（零风险）

同样没有 RSC 变体。

- 表达式：

      http.request.uri.path in {"/api/latest-events" "/api/all-events" "/api/telegram-events"}

- Eligible for cache；Edge TTL：**Use cache-control header if present, bypass cache if not**
  （源站发 `s-maxage=60`）

#### 规则 3：缓存公开页面 HTML（收益最大，必须带 RSC 排除）

- 表达式（用 **Edit expression** 文本模式粘贴，构建器的下拉不一定能选到请求头字段）：

      (starts_with(http.request.uri.path, "/latest")
       or starts_with(http.request.uri.path, "/all")
       or starts_with(http.request.uri.path, "/daily")
       or starts_with(http.request.uri.path, "/x")
       or starts_with(http.request.uri.path, "/telegram")
       or starts_with(http.request.uri.path, "/topics")
       or starts_with(http.request.uri.path, "/weekly")
       or starts_with(http.request.uri.path, "/monthly")
       or starts_with(http.request.uri.path, "/event/"))
      and not any(http.request.headers["rsc"][*] == "1")

- Cache eligibility：**Eligible for cache**
- Edge TTL：**Use cache-control header if present, bypass cache if not**
  （源站发 `s-maxage=120`；nginx 已经把 Next 那条 `no-store` 换掉了）
- Browser TTL：**Respect origin**
  （源站发的 `max-age=0, must-revalidate` 会让浏览器每次回来问，
  不会攥着旧 HTML 刷不掉）

**故意不包含**：`/admin/*`、`/api/feedback`、`/api/admin-*`、`/bookmarks`、`/search`。
前四个是写操作或带登录态；`/search` 每次查询都不同，缓存命中率低还占空间。

**加完必须验证站内跳转**：打开 `/latest` → 点进任意一篇详情 → 点浏览器后退。
全程正常 = RSC 排除生效；白屏或报错 = 表达式没生效，**立刻停用规则 3**。

#### ⚠ 那唯一的限流坑位可能已经被占了

2026-08-13 实配时发现 zone 里已经有一条名为 **Leaked credential check** 的限流规则，
表达式是 `(cf.waf.credential_check.password_leaked)`，5 次/10 秒、Block。
这是 Cloudflare 的模板规则，不是我们建的。

**它对 AR 永远不会命中**：这个字段只在 CF 从请求里识别出「用户名+密码」
并命中泄露库时才为真，默认扫描位置是 WordPress / Drupal / Joomla / Magento
这类 CMS 的登录表单格式。而 AR 的后台登录只有一个 `token` 字段
（`apps/web/app/admin/login/page.tsx`），没有用户名密码对，也不是那几种格式。

**但它占掉了免费版仅有的 1 条配额**，所以处理方式是**原地改造它**而不是新建：
改名、把表达式换成下面的、阈值 5 → 200。

删掉这条规则**不会关闭泄露凭据检测本身**——检测是独立开关，
这条规则只是"检测到之后做什么"的一个动作。
**什么情况下该换回来**：如果 AR 以后加了真正的用户名密码登录。

#### 规则 4：限流（免费版只有 1 条，能力也受限）

免费版的限制（已核对官方文档）：表达式**只能用 Path**、计数窗口**固定 10 秒**、
封禁时长**固定 10 秒**、按 IP 计数、且**不能排除缓存命中的请求**。

- 位置：**Security → WAF → Rate limiting rules**
- 表达式：`starts_with(http.request.uri.path, "/")`（全站）
- 阈值：**10 秒内 200 次**，动作 **Block**，超时 10 秒

阈值定得高是有意的：这条的定位是"在边缘拦住洪水"，
精细的分路径配额由 nginx 那四档负责（见 §2.1）。CF 缓存开了之后，
一次正常首屏会带出 HTML + 几十个静态资源 + 图片，快速翻三页就可能到 150 次/10 秒，
所以 200 是留了余量的。注意免费版**不能排除缓存命中的请求**，缓存命中同样计数。

**实测（2026-08-13，从一台固定 IP 的机器打）**：

| 场景 | 结果 |
|---|---|
| 正常节奏 40 个请求 | 通过 40 / 拦截 0 —— 零误伤 |
| 9 秒内并发 260 次 | 通过 181 / 429 拦截 79 —— 在 200 附近截断 |

它挡得住文章里第一波那种"单 IP 每分钟 87 万次"的莽夫流量（一秒即封）；
第二波"多 IP 协同、每个都压在限流线下"的打法这条挡不住——
那本来就是 nginx 四档 + 后端全局总量上限负责的，分层设计就是如此。

#### 规则 5：Bot Fight Mode（免费）

**Security → Bots → Bot Fight Mode** 打开。对已验证的搜索引擎爬虫不生效，不影响 SEO。

#### 应急：记住 "I'm Under Attack" 在哪

**Security → Settings → Security Level → I'm Under Attack**。
真被打时第一步就是开它（5 秒 JS 挑战页），再去看日志——见第三节的 5 分钟处置流程。

#### 加完之后怎么确认真的生效

    # 这三个应该从 DYNAMIC 变成 HIT（第二次请求起）
    curl -sI https://radar.suversal.com/latest        | grep -i cf-cache-status
    curl -sI https://radar.suversal.com/api/all-events | grep -i cf-cache-status
    curl -sI "https://radar.suversal.com/api/image-proxy?url=<任意站内图片>" | grep -i cf-cache-status

    # 这个必须仍然是 DYNAMIC（RSC 排除生效的证据）
    curl -sI -H "RSC: 1" https://radar.suversal.com/latest | grep -i cf-cache-status

> 顺带：CF 的 Managed robots.txt 目前默认禁了 GPTBot / ClaudeBot / Google-Extended，
> 这条老待办和本计划无关，但可以一起决定（见 `greenvps-deployment.md` §七）。

---

## 三、被打时的 5 分钟处置流程

真出事的时候没人有心情读长文档，所以单独列一页：

```bash
# 1. 止血（10 秒）——CF 控制台开 "I'm Under Attack"

# 2. 看清楚在打哪儿（1 分钟）
ssh greenvps 'docker logs --since 10m infra-nginx-1' | awk '{print $7}' | sort | uniq -c | sort -rn | head
ssh greenvps 'docker logs --since 10m infra-nginx-1' | grep -oE "^[0-9a-f.:]+" | sort | uniq -c | sort -rn | head

# 3. 看死在哪一层（30 秒）
ssh greenvps 'docker stats --no-stream'
ssh greenvps 'ss -s'                      # 并发连接数 vs 2048 上限

# 4. 精准封禁：把 IP 加进 00-hardening.conf 的 geo 黑名单，重启 nginx
# 5. 事后：从访问日志复盘特征，沉淀成规则，写进本文档第四节
```

**处置原则（抄他的，写得很对）**：
先止血再查因；封禁要有证据不能凭感觉；每一次处置都要沉淀成自动化规则，
否则下一波来了还是手忙脚乱。

---

## 四、验收标准

阶段 1 做完必须同时满足：

- [ ] `/latest` `/all` `/daily` `/x` `/telegram` 第二次请求 `X-Cache-Status: HIT`
- [ ] 带随机参数 `?zzz=xxx` 仍然 `HIT`
- [ ] 带真实过滤参数 `?category=tutorial` 是**独立**的缓存键
- [ ] 带 `admin_token` cookie 恒为 `BYPASS`
- [ ] `/admin` `/api/admin-proxy` `/api/feedback` 恒不缓存
- [ ] image-proxy 对 `127.0.0.1` / `169.254.169.254` / `10.x` 返回 400
- [ ] 正常图片全部照常显示（人工翻 `/latest` `/event/*` `/x`）
- [ ] 反馈接口连发 10 条：入库 3 条，Telegram 响 3 次，其余静默
- [ ] 压测：`/latest` 并发 50 持续 30s，P95 < 500ms（**改造前实测 1.2~3.3s**）

阶段 2 做完：

- [ ] 单 IP 超过阈值返回 429，正常浏览不触发（人工连点 2 分钟不出 429）
- [ ] `?limit=100000` 被夹到 200

---

## 五、明确不做的事，以及为什么

| 不做 | 理由 |
|---|---|
| image-proxy 硬域名白名单 | 新信源随时带来新图床，会造成静默的"图片全白"事故。改用软性分级 + 限流 |
| image-proxy HMAC 签名 | 多个调用方是 client component，要做得把签名下沉到 payload 改写层，改动面和回归风险 >> 收益。列为以后可选 |
| FastAPI 层限流（slowapi 等） | API 只在 docker 内网可达，nginx 一层已覆盖全部入口。多一层就多一套阈值要维护 |
| 引入 Redis 做限流/去重 | 反馈去重用一条 SQL 就够。为一个功能拉一套新的状态存储不划算（Redis 容器在跑，但目前只用于健康检查） |
| 现在就调 `worker_connections` | 阶段 1 做完后连接不再堆积，先测再决定。先抬天花板只是让更多人一起排队 |
| 换 CDN / 上高防 | 现在的瓶颈是单请求成本，不是带宽。花钱买不来 `proxy_cache` 那 10 行配置的效果 |

---

## 六、施工顺序与预估

| 顺序 | 内容 | 影响面 | 可独立上线 |
|---|---|---|---|
| 1 | nginx 缓存 + 缓存键规范化 | 纯 nginx 配置 | ✅ |
| 2 | `lib/api.ts` 的 12 处 `no-store` → `revalidate` | 前端 | ✅ |
| 3 | image-proxy 加固 | 单文件 | ✅ |
| 4 | 反馈接口三件套 | 前后端各一处 | ✅ |
| 5 | nginx 限流 | 纯 nginx 配置 | ✅ |
| 6 | `limit`/`days` 上限 | 后端多处 | ✅ |
| 7 | 日志 + 告警 + 速查脚本 | compose + 脚本 | ✅ |
| 8 | 登录限流 + cookie secure | 两处 | ✅ |
| 9 | aihot 信源失败告警 | pipeline | ✅ |

每一步都能单独发布、单独回滚。发布走 `TARGET=greenvps bash scripts/deploy_to_server.sh`。

**已知施工陷阱**（先写下来，省得踩）：

1. **nginx include 顺序**：`conf.d/*.conf` 按字母序加载，
   `limit_req_zone` / `proxy_cache_path` **必须出现在引用它们的 `limit_req` / `proxy_cache` 之前**，
   否则启动直接报 `unknown zone`。所以新文件命名为 `00-hardening.conf`
   （排在 `cloudflare-ips.conf` 和 `default.conf` 前面）。
2. **新文件必须挂进 `docker-compose.https.yml`**，只放进仓库不挂载等于没写。
3. **发布后 nginx 要重启**：nginx 只在启动时解析一次 upstream，
   部署脚本末尾已有 `docker restart infra-nginx-1`。
4. **验证不能在这台 Mac 上打**：Mac 装了代理软件并开了 DNS 覆写，出口在新加坡，
   会按 SNI 改道到 CF 边缘（详见 `greenvps-deployment.md` §三末尾）。
   缓存头这类经过 CF 的验证在本地打没问题，**源站直连类的验证必须换观察点**。

---

## 七、变更记录

| 日期 | 内容 |
|---|---|
| 2026-08-13 | 立项。起因是 AIHOT 被攻击一文；完成现状实测与全量对照，产出本计划 |
| 2026-08-13 | 阶段 1-1 完成。新增 `infra/nginx/00-hardening.conf`、`proxy-common.conf`、`proxy-cached.conf`，重写 `radar-cf.conf`。本地起 nginx + 假上游跑完全部验收用例；过程中发现并修正两个设计缺陷（缓存投毒、`limit`/`days` 漏白名单），详见 §2.1 |
| 2026-08-13 | 阶段 1-2 完成。`lib/api.ts` 12 处 `no-store` → `cacheFor(60/300/600)`，开发环境与 `AI_RADAR_DISABLE_DATA_CACHE=1` 保持旧行为。构建产物显示 `/`、`/about`、`/topics`、`/weekly`、`/monthly`、`/changelog`、`/feedback` 由动态渲染转为 ISR 静态页 |
| 2026-08-13 | 阶段 1-3 完成。新增 `lib/image-proxy-guard.ts`，重写 image-proxy route：逐跳校验的手动重定向、8s 超时、8MB 体积封顶、未知图床先记日志（`IMAGE_PROXY_ENFORCE_HOSTS=1` 切强制）。25 条 SSRF 用例在 greenvps 真实 DNS 下全通过 |
| 2026-08-13 | 阶段 1-4 完成。反馈接口加内容去重（10 分钟）、全局总量上限（10 分钟 30 条）、Telegram 每小时 20 条预算；web 层透传真实 IP 供日志取证。超限一律返回 200 不返回 429 |
| 2026-08-13 | 阶段 1 代码全部完成，全量 611 个测试通过 |
| 2026-08-13 | 阶段 2-1 完成。nginx 四档限流 + `limit_conn`，本地逐档实测阈值；确认限流桶按 IP 隔离且依赖 real_ip 还原 |
| 2026-08-13 | 阶段 2-2 完成。**原判断被推翻**：后端一直有上限校验（写在函数体里不在签名里）。真问题是 web 层把后端 400 吞成空页面，新增 `lib/query-params.ts` 的 `clampInt()` 在入口收敛，13 条边界用例通过 |
| 2026-08-13 | 阶段 3 完成。nginx `radar` 日志格式（含缓存状态/耗时/CF-Ray）+ compose 日志留存 50m×20；新增 `scripts/traffic_top.sh`；admin cookie 加 `secure`；信源连续失败 ≥3 次单独告警 |
| 2026-08-13 | 追加项完成。周月报对外负载剥掉文章正文：**16.61 MB → 1.12 MB（15 倍）**，重新落回 Next 数据缓存 2MB 上限内 |
| 2026-08-13 | 全部阶段代码完成，全量 615 个测试通过 |
| 2026-08-13 | 发布到 greenvps。过程中出了两次线上问题，均已修复并记录在下面的「发布事故」一节 |
| 2026-08-13 | 线上验收全部通过。**缓存命中的请求服务端耗时 0.723s → 0.000s** |
| 2026-08-13 | 配置 Cloudflare 三条 Cache Rule + 限流 + Bot Fight Mode。发现免费版 Edge TTL 最小 2 小时，改为由源站发 `s-maxage`，实测 CF 严格遵守 |
| 2026-08-13 | 修复管理员判据可被伪造 cookie 绕过的缓存开关（事故三），并解决真 token 超长导致的 `map_hash_bucket_size` 启动失败（事故四） |
| 2026-08-13 | 补第十节「改动全览」：按流量分层，逐项写清做了什么 / 为什么 / 有什么用 / 优缺点，以及总体代价与耦合点清单 |

---

## 八、发布事故（四次，都值得记住）

计划书第六节列了 4 条「已知施工陷阱」，结果发布时踩中了其中一条，
另外撞上三条完全没预料到的。前两条是发布操作出的问题，
后两条（事故三、四）是**设计缺陷**——其中事故三是被一句提问挖出来的："它是怎么判断管理员在看的？" 

### 事故一：漏挂一个文件 → 整站 521，约 2 分钟

**现象**：发布脚本健康检查报 `greenvps(US) /latest 返回 521`。

**根因**：`radar-cf.conf` 里 `include snippets/proxy-cached.conf`，
但 `docker-compose.https.yml` 里只挂了 `proxy-common.conf` ——
新建 snippet 的时候忘了回去补挂载。nginx 启动即 `[emerg] open() ... failed`，
容器进入 `Restarting` 循环，CF 连不上源站于是 521。

**讽刺的是**：这条陷阱**就写在本文第六节第 2 条**——"新文件必须挂进
`docker-compose.https.yml`，只放进仓库不挂载等于没写"。写下来了，还是踩了。

**教训**：`521` → `docker ps` 看容器是不是在 `Restarting` → `docker logs` 看
`[emerg]`。这条链路要背下来，从 521 反查到"少挂了一个文件"否则要绕很大一圈。
现在这个连带关系已经写进 `docker-compose.https.yml` 的注释里，就在挂载列表旁边。

**为什么本地测试没发现**：本地测试是把 `infra/nginx/` 整个目录拷进容器的，
文件都在；而线上是按 compose 里的挂载列表逐个映射的。
**本地验证的是配置内容，验证不了挂载清单**——这两件事得分开测。

### 事故二：错误页被烤进静态 HTML → 三个页面展示"API 服务暂时不可用"

**现象**：发布后 `/weekly`、`/monthly`、`/topics` 三个页面稳定显示
"API 服务暂时不可用"，而后端接口本身完全正常。

**根因**：阶段 1-2 把 `cache: "no-store"` 换成 `revalidate` 之后，
这三个页面不再被判定为动态渲染，Next 于是在**构建期预渲染**了它们。
而 `docker build` 阶段 web 镜像是单独构建的，compose 网络里还没有 `api` 服务
—— 取数失败，`lib/api.ts` 返回降级 payload（"API 服务暂时不可用"），
这段文案就被**烤进了静态 HTML**，然后按 ISR 周期一直发给用户。

改之前这三个页面是动态渲染的，每次请求现取，所以从来不会有这个问题。

**修法**：给这三个页面加 `export const dynamic = "force-dynamic"`。
性能不受影响——HTML 由 nginx 缓存、取数由 Next 数据缓存兜，两层都还在，
只是不再在构建期预渲染。

**判断标准**（对以后同类改动同样适用）：
**内容来自 API 的页面不能被构建期预渲染**，因为我们的 API 在构建期不可达。
`/about`、`/changelog`、`/feedback` 是纯静态内容、不调 API，预渲染没问题。

**排查时的一个岔路**：修完重新发布后，页面**依旧**是旧的错误内容，
而且响应体积一个字节都没变。原因是 nginx 已经把错误页缓存了 180 秒，
且 `docker restart` 不会清掉容器内的缓存目录。
**改动生效后要验证，记得先清缓存**：

```bash
ssh greenvps 'docker exec infra-nginx-1 sh -c "rm -rf /var/cache/nginx/radar/*" \
              && docker exec infra-nginx-1 nginx -s reload'
```

这也是加缓存之后多出来的一条新常识：**"我改了但没生效"从此多了一种可能**。

---

### 事故三：管理员判据是个攻击者可控的缓存开关

**这条不是发布事故，是设计缺陷，由一个提问挖出来的**——"它是怎么判断管理员在看的？"

**原实现**：

    map $cookie_admin_token $skip_cache_admin {
        default 1;    # cookie 非空就当管理员
        ""      0;
    }

**只看 cookie 存不存在，完全不校验值。** 而这个变量同时决定
`proxy_cache_bypass` 和发给 CF 的 `Cache-Control`。于是任何人发一个
`Cookie: admin_token=随便编的`，就能让每个请求**同时绕过 CF 和 nginx 两层缓存**，
强制源站现场渲染。

**实测代价**：缓存命中 0.000s，伪造 cookie 绕过后 0.119~0.163s。
一个 IP 在 pages 档（60r/m）配额下约占 13% 单核，
**十几二十个 IP 就能打满这台 2 核机器**——而不用这个技巧的话，同样这批 IP
全部命中缓存、对我们几乎零成本。等于刚建好的整套缓存防线，加一个 HTTP 头就绕过了。

这正是原文第二波"多 IP 协同"最理想的弹药。

**不是数据泄露**：真正的鉴权在后端（`require_admin` 用 `secrets.compare_digest`）。
实测伪造 cookie 访问 `/admin` 只渲染出一个 22KB 的外壳、内容是 "Invalid admin token"、
零真实数据，所有后台 API 一律 401。这里修的是"攻击者可控的缓存开关"，不是权限。

**修法**：用 nginx 官方镜像的模板机制（`/etc/nginx/templates/*.template` + envsubst）
把真实 `ADMIN_TOKEN` 注入成精确匹配，见 `infra/nginx/00-admin-token.conf.template`。

| 请求 | 修复前 | 修复后 |
|---|---|---|
| 无 cookie | 正常缓存 | 正常缓存 |
| 伪造 `admin_token=xxx` | **BYPASS（可利用）** | **HIT（挡住了）** |
| 空 `admin_token=` | BYPASS | HIT |
| 真 token | BYPASS | BYPASS（保留实时性） |

几个刻意的设计细节：

- `NGINX_ENVSUBST_FILTER: "^ADMIN_TOKEN$"` —— 只替换这一个名字，
  杜绝 envsubst 误伤 nginx 自己的 `$host` / `$uri` / `$arg_*`。已实测：
  渲染后 `00-hardening.conf` 里 21 处 nginx 变量引用完好无损。
- 模板里显式保留 `"" → 0` 一行。万一 token 为空，nginx 会因 map 键重复而
  **启动失败**（响亮地坏掉），而不是把空 cookie 判成管理员、静默让全站缓存失效。
  已实测：`[emerg] conflicting parameter ""`。
- compose 里 `ADMIN_TOKEN: ${ADMIN_TOKEN:?set in .env}` —— 部署期就拦住，
  和 `POSTGRES_PASSWORD` 用的是同一个习惯。
- 把 token 交给 nginx 容器不算新增暴露面：它本来就在同一台机器的 `.env` 里，
  api/web 也都拿着；而真攻破了 nginx，攻击者本来就能看到所有流量里的 cookie。

### 事故四：map 的哈希桶装不下真 token

修完上面那条发布，nginx 直接进入重启循环：

    [emerg] could not build map_hash, you should increase map_hash_bucket_size: 64

nginx 默认 `map_hash_bucket_size` 是 64 字节，而 map 的**键**（这里是整个
ADMIN_TOKEN）必须放得进一个桶。本地测试用的短 token 没事，线上真 token 超长就炸。
加 `map_hash_bucket_size 256;` 解决。

**教训**：拿真实长度的数据测。用 `s3cr3t-real-token-value` 这种玩具值测出来的"通过"，
在这类有长度约束的地方等于没测。

### ⚠ 边缘缓存带来的新盲区：发布健康检查会被缓存糊弄过去

事故四那次，**发布脚本报告"发布完成"，三个页面全是 HTTP 200**——
而 nginx 正处在重启循环里，源站根本没在服务。

原因是 CF 现在缓存了这些页面（`s-maxage=120`），健康检查打到的是**边缘缓存副本**，
和源站死活无关。这是加了边缘缓存之后**新出现**的失败模式，以前不存在。

**修法**：健康检查的 URL 要能穿透 CF 缓存，给它挂一个随机查询参数：

    curl -sS -o /dev/null -w '%{http_code}' "https://radar.suversal.com/latest?healthcheck=$RANDOM"

随机参数会让 CF 的缓存键失配（CF 的键含查询串）从而必然回源；
而 nginx 那边这个参数会被白名单规范化掉，所以仍然命中 nginx 缓存、不会额外增加源站负担。
**这条改动要落在 `scripts/deploy_to_server.sh` 里，那个文件不在 git 中，需要手工改。**

在改之前，发布后请额外确认一次容器状态：

    ssh greenvps 'docker ps --filter name=infra-nginx --format "{{.Status}}"'

## 九、线上验收结果（2026-08-13）

全部通过。数据取自 nginx 自己的 `$request_time`（新日志格式的产物），
不是从 Mac 上量的——这台 Mac 走新加坡代理绕到美国服务器，
网络往返会盖过服务端耗时，量出来的数字没有意义。

**性能**

| 缓存状态 | 服务端耗时 | 说明 |
|---|---|---|
| `cache=MISS` | **0.723s** | 回源做一次完整 SSR，**等同于改造前每一个请求的成本** |
| `cache=HIT` | **0.000s** | 亚毫秒 |
| `cache=BYPASS` | 0.05–0.25s | 管理员路径，Next 数据缓存仍在起作用 |
| 50 并发同一页面 | 总计 502ms | 合单生效，上游只被回源一次 |

日志里已经能看到真实用户吃到缓存（一个 iPhone 用户经 AMS 边缘拿到 `cache=STALE`，0.199s）。

**功能**

| 项 | 结果 |
|---|---|
| 12 个公开页面内容正确、无报错文案 | ✓ |
| `/latest` 二次请求 HIT | ✓ |
| `?zzz=随机` 折叠成同一份缓存 | ✓ |
| `?q=<200 字符非法值>` 不污染干净页 | ✓ |
| `?category=tutorial` 独立缓存键 | ✓ |
| admin cookie / RSC 请求 BYPASS | ✓ |
| `/admin/login`、`/api/image-proxy` 不缓存 | ✓ |
| `?limit=100000` 收敛到 50（原先返回空页） | ✓ |
| image-proxy 对 `127.0.0.1` / `169.254.169.254` / `10.0.0.1` 返回 400 | ✓ |
| 真实文章配图仍正常（多张实测 200 + 正确 MIME） | ✓ |
| strict 档限流生效、pages 档 20 连发零误伤 | ✓ |
| 日志留存 `json-file 50m×20` 已生效 | ✓ |

> **限流的一个观察**：线上打 12 次 `/admin/login` 只被拦下 2 次，
> 比本地测试宽松得多。原因是这台 Mac 的代理出口 IP 会变，
> 日志里能看到同一批请求来自三个不同地址——**每个 IP 一个桶**。
> 这恰好印证了为什么反馈接口还需要后端那层全局总量上限：
> 分布式来源天生能绕开 per-IP 限流，而这正是 AIHOT 第二波攻击的打法。

---

## 十、改动全览：做了什么 / 为什么 / 有什么用 / 代价是什么

前面九节是施工与复盘视角。这一节换个角度，把**每一项改动**按同一套四问过一遍，
方便快速判断"这东西值不值""改它会碰到什么"。

按流量经过的顺序分层：**Cloudflare 边缘 → nginx 源站门口 → Next.js 应用 → 后端 API → 可观测**。
分层是有意的：**任何一层失效，其余层仍然独立生效**，不会一处坏掉就全盘裸奔。

---

### 第 1 层 · Cloudflare 边缘

#### 1.1 三条 Cache Rule（图片代理 / 公开只读 API / 公开页面 HTML）

- **做了什么**：让 CF 在边缘缓存这三类响应。图片代理跟随源站的 `max-age=86400`；
  页面 120 秒；公开 API 60 秒。页面那条额外排除了带 `RSC: 1` 头的请求。
- **为什么这么做**：CF **默认不缓存 HTML**。不配这个，访客的每个请求都要从他所在的
  边缘一路跑到圣何塞——而源站自己只花 0.000s，时间几乎全花在路上。
- **有什么作用**：命中后请求终止在访客最近的边缘节点，源站完全不接触。
  实测同一条链路上 CF 命中 0.812s vs 回源 2.215s，**每次页面加载省约 1.4 秒**。
  被攻击时更关键：打在边缘的流量根本到不了这台 2 核机器。
- **优点**：全套改动里收益最大的一层；免费；挡在最外面。
- **缺点 / 代价**：
  - 数据最多旧 2 分钟（叠加下层后见 §10.6 的总账）。
  - **CF 默认不看源站的 `Vary` 头**，缓存键只有 URL。任何"同一 URL 返回不同内容"的
    场景都得自己在规则里排除——RSC 就是活例子，不排除会导致站内跳转白屏。
    以后若引入按语言/按设备的差异化渲染，必须回来重新审视这条。
  - 免费版 Edge TTL 最小 2 小时，逼得我们把时长放到源站头里给（§10.2.5）。

#### 1.2 限流规则（全站 200 次 / 10 秒 / IP，封 10 秒）

- **做了什么**：把 zone 里原有那条永远不会命中的 `Leaked credential check` 改造成了洪水闸。
- **为什么这么做**：免费版只有 1 条限流配额，而那条模板规则只对
  WordPress/Drupal 那类用户名密码表单生效，AR 的后台登录只有一个 `token` 字段，永不命中。
- **有什么作用**：在边缘拦住单点高频。实测 9 秒内并发 260 次 → 79 个 429；
  正常节奏 40 次请求零拦截。
- **优点**：免费，且拦在最外层，被拦的流量不消耗任何源站资源。
- **缺点 / 代价**：
  - 免费版能力受限：只能按 Path 匹配、窗口固定 10 秒、封禁固定 10 秒、
    **不能排除缓存命中的请求**（缓存命中也计数）。
  - **挡不住多 IP 协同**——每个 IP 都压在线下就完全无效，这正是原文第二波的打法。
    所以它不是主力，nginx 四档和后端全局上限才是。
  - 占用了唯一的配额。若将来 AR 真的加了用户名密码登录，要重新权衡换回去。

#### 1.3 Bot Fight Mode

- **做了什么**：打开免费版的机器人挑战。
- **为什么 / 作用**：挡掉一批脚本化爬取，成本为零。
- **缺点**：可能误伤一些良性自动化访问；对已验证的搜索引擎爬虫不生效，所以不影响 SEO。

---

### 第 2 层 · nginx（源站门口）

#### 2.1 反向代理缓存 `proxy_cache`

- **做了什么**：把公开页面和公开 API 的响应缓存在源站 nginx 里（页面 180s、API 60s）。
- **为什么这么做**：改造前**所有**公开页面都是零缓存——`lib/api.ts` 里 12 处硬写的
  `cache: "no-store"` 把页面钉成动态渲染，每个访客请求 = 一次完整 SSR + 一次 API + 一次查库。
- **有什么作用**：源站侧 **0.723s → 0.000s**（数据来自 nginx 自己的 `$request_time`）。
  CF 未命中回源时，这一层接住。
- **优点**：与 CF 那层完全独立——就算 CF 规则被误删，这层照样保护源站。
- **缺点 / 代价**：
  - 又叠加一层 TTL（见 §10.6）。
  - 缓存留在容器内，`docker restart` 后冷启（代价只是重新预热几秒）。
  - **多出一种"我改了但没生效"的可能**：改动上线后要么等 TTL，要么手动清缓存。

#### 2.2 缓存键规范化 + 剥掉名单外参数再回源

- **做了什么**：只认 13 个白名单查询参数，规范化后的结果**既做缓存键、也做真正发给
  上游的查询串**。名单外参数和非法值在进入 Next 之前就被丢掉。
- **为什么这么做**：在 URL 后挂随机参数制造"每次都是新页面"是应用层 CC 的标准打法，
  直接拿 `$args` 做缓存键正中下怀。
- **有什么作用**：`?_=1731…` 这类随机参数全部折叠到同一份缓存，攻击手法当场失效。
- **优点**：顺手消灭了一个**缓存投毒面**。只规范化键、却把原始参数原样回源，
  会让 `?q=<非法超长串>` 的搜索结果被存进"没有 q 参数"的键里，之后所有人访问
  `/latest` 都看到攻击者的搜索结果（本地测试时发现的，见 §2.1 的警告框）。
  让键和内容同源，这个洞在结构上就不存在。
- **缺点 / 代价**：**这是全套改动里最容易出事的维护点**。
  新增页面参数或 API 参数时必须同步加进白名单，否则那个筛选/翻页条件会被
  **静默丢弃**——页面正常渲染，只是筛选不起作用，很难联想到是 nginx 干的。
  初版就漏了 `limit`/`days`，后果是"加载更多"永远返回第一页。

#### 2.3 合单 `proxy_cache_lock`

- **做了什么**：同一时刻涌进来的相同请求，只放 1 个回源，其余等结果。
- **为什么**：缓存过期的瞬间会有一批请求同时穿透（缓存击穿），这正是攻击者要的效果。
- **作用**：实测 50 并发同一页面 → **上游只被调用 1 次**，总耗时 2 秒（上游单次耗时 2 秒）。
- **缺点**：上游慢的时候后面的请求要排队（配了 10 秒超时兜底，不会无限等）。

#### 2.4 过期兜底 `proxy_cache_use_stale` + `background_update`

- **做了什么**：上游报错或正在更新时，宁可发一份过期内容也不发错误页。
- **作用**：顺带兜住了整库同步时"改名 + 重启 api"的那 2~3 秒窗口，用户完全无感。
  实测停掉上游后，已缓存页面照常 200。
- **缺点**：用户可能看到过期内容而不自知；掩盖了后端故障，所以**告警不能依赖用户反馈**。

#### 2.5 用 `s-maxage` 覆盖 Next 的 `no-store`

- **做了什么**：公开页面/API 的响应头由 nginx 改写成
  `public, s-maxage=120, max-age=0, must-revalidate`；管理员与 RSC 请求仍发 `private, no-store`。
- **为什么这么做**：Next 给动态页一律发 `no-store`，CF 照做就等于边缘不缓存。
  而免费版 Edge TTL 最小 2 小时（对资讯站太长），CF 的 Origin Cache Control 又默认开启、
  严格遵守源站头——**把时长收回源站，既绕开下限，又和 nginx 自己的 TTL 放在同一处维护**。
- **作用**：让第 1 层成为可能。实测 `age` 涨到 119 就过期归零，周期正好是 120 秒。
- **优点**：`s-maxage` 只对 CF 生效、浏览器忽略；`max-age=0` 保证用户不会攥着旧 HTML 刷不掉。
- **缺点 / 代价**：我们在**覆盖框架的意图**。将来若某个公开页真的需要 `no-store`
  （比如加了按人不同的内容），必须记得把它从白名单 location 里摘出去，否则会把
  私有内容发给所有人。这是一个需要人记住的约定，配置本身不会提醒你。

#### 2.6 四档限流 + `limit_conn`

- **做了什么**：按"请求有多贵"分四档——pages 60r/m、api 120r/m、imgproxy 300r/m、
  strict 6r/m（反馈与登录）；静态资源完全不限流。
- **为什么**：改造前全站没有任何限流，任何频率对我们都是合规的。
- **作用**：实测各档都在 burst+1 处截断，正常浏览零误伤。
- **优点**：分档依据是成本而不是路径长相；静态资源不挂限流，避免误伤首屏。
- **缺点 / 代价**：
  - 阈值是估的，需要用真实流量观察后再调。
  - **命中缓存的请求同样消耗配额**（`limit_req` 在缓存查找之前执行）。
  - per-IP 计数挡不住分布式。
  - **强依赖 real_ip 还原**：一旦 `cloudflare-ips.conf` 失效，所有流量会被算到
    十几个 CF 出口 IP 上共用一个桶，结果是**全站 429**。改那个文件时必须想到这里。

#### 2.7 管理员判据改为精确比对 token

- **做了什么**：用 nginx 模板机制把真实 `ADMIN_TOKEN` 注入成 map 的精确匹配。
- **为什么这么做**：原实现只看 cookie 存不存在。而这个变量同时决定
  `proxy_cache_bypass` 和发给 CF 的 `Cache-Control`——**任何人加一个 HTTP 头就能
  同时绕过两层缓存**，我们刚建好的整套缓存防线一个头就废了（详见事故三）。
- **作用**：伪造 cookie 从 BYPASS 变成 HIT；真 token 仍然 BYPASS，实时性保留。
- **优点**：不是靠隐藏而是靠比对；失败方向安全（token 为空时 nginx 响亮地启动失败，
  而不是静默把全站缓存关掉）。
- **缺点 / 代价**：
  - nginx 容器要拿到 `ADMIN_TOKEN`（评估：不算新增暴露面，它本来就在同机 `.env` 里，
    api/web 也都拿着；真攻破 nginx，攻击者本来就能看到流量里的 cookie）。
  - token 超过 64 字符要调 `map_hash_bucket_size`（踩过，见事故四）。
  - 配置从静态文件变成模板，多了一个渲染步骤和一类新的启动失败可能。

---

### 第 3 层 · Next.js 应用

#### 3.1 `cache: "no-store"` → `cacheFor(60/300/600)`

- **做了什么**：`lib/api.ts` 12 处取数改为带 TTL 的数据缓存；开发环境与
  `AI_RADAR_DISABLE_DATA_CACHE=1` 保持旧行为。
- **为什么**：`no-store` 既让 Next 数据缓存失效，又把页面钉成动态渲染、发出 `no-store` 响应头。
- **作用**：省掉每次请求的 API 调用与数据库查询。即使 nginx 缓存未命中，这一层仍在兜底
  （实测 BYPASS 请求 0.119~0.163s，而完全未命中是 0.723s——差值就是这层的贡献）。
- **优点**：本地开发"改完立刻能看到"的手感没有丢。
- **缺点 / 代价**：**一个页面一旦不再是动态渲染，就可能被构建期预渲染**。
  而我们的 API 在 `docker build` 阶段不可达，于是"API 服务暂时不可用"的降级文案
  被烤进了静态 HTML（事故二）。这是个反直觉的连带效应，改缓存要连带检查渲染形态。

#### 3.2 三个数据驱动页面标记 `force-dynamic`

- **做了什么**：`/weekly` `/monthly` `/topics` 显式声明动态渲染。
- **为什么 / 作用**：见上条。判断标准是——**内容来自 API 的页面不能被构建期预渲染**。
- **缺点**：失去 ISR 全路由缓存。但 nginx 缓存 + Next 数据缓存都还在，实际性能几乎不变。

#### 3.3 image-proxy 加固

- **做了什么**：解析后拒绝非公网地址（重定向每一跳都重新校验）、超时 15s→8s、
  响应体积封顶 8MB、只允许 GET、未知图床记日志。
- **为什么**：这个接口原先只校验协议，`url` 可以指向任何地址——既是开放代理
  （谁都能白嫖我们的出口带宽），也是内网扫描器。
- **作用**：25 条 SSRF 用例在真实 DNS 下全部拦截；真实文章配图不受影响。
- **优点**：域名用**软性分级**而不是硬白名单——新信源随时带来新图床，
  硬白名单会造成静默的"图片全白"事故。
- **缺点 / 代价**：
  - 未知图床目前**只记日志不拦截**，还不是硬防护。要等日志攒够再用
    `IMAGE_PROXY_ENFORCE_HOSTS=1` 切换。
  - **DNS rebinding 的 TOCTOU 窗口无法根除**（我们校验的是这一刻的解析结果，
    fetch 会自己再解析一次）。要彻底封死得自己按 IP 建连并手动带 Host + SNI，
    代价远大于收益——这个接口的响应被限制成 `image/*`，拿不回内网服务的正文。
  - 手动跟随重定向让这段代码复杂了不少。

#### 3.4 `clampInt` 收敛查询参数

- **做了什么**：`limit`/`days`/`offset` 在 web 层就收敛到与后端一致的区间。
- **为什么**：原来的 `Number(x) || 50` 会把 `NaN`、空串和显式的 `?limit=0` 一起
  静默变成 50，而超大值原样透传给后端触发 400，再被 `lib/api.ts` 吞成空 payload——
  线上表现是"页面正常打开、一条内容都没有"，**没有报错、没有非 200、日志里也看不出异常**。
- **作用**：越界值收敛而不是变成空页面。13 条边界用例通过。
- **缺点**：上下限要与后端保持一致，是两处需要同步的常量。

#### 3.5 admin cookie 加 `secure`

- **做了什么 / 为什么**：线上全程 HTTPS，没有理由让这个 cookie 有机会明文发出；
  按环境区分，本地开发不受影响。**代价为零。**

---

### 第 4 层 · 后端 API

#### 4.1 反馈接口：内容去重 + 全局总量上限 + Telegram 预算

- **做了什么**：10 分钟内相同内容不重复入库；10 分钟总量超 30 条静默丢弃；
  每小时最多推送 20 条 Telegram，超出只入库。
- **为什么**：原文里攻击者以每秒 5.5 次往反馈接口灌了 3 万多条垃圾，把作者的通知群刷爆。
  我们更脆——每条反馈还会同步推一次 Telegram，而 Bot API 有自己的速率限制，
  被灌爆会把整条通知通道打死，那条通道还兼着别的告警。
- **作用**：nginx 挡单点高频，这层挡**多 IP 协同**——后者 per-IP 限流天生无效。
- **优点**：计数直接查表，不引入 Redis 或内存计数器；跨进程、跨重启都有效，
  攻击者不会因为我们重启一次 api 就白拿一个干净窗口。
- **缺点 / 代价**：
  - **超限返回 200 而不是 429**（故意的：429 等于告诉攻击者阈值在哪，
    他能据此精准压在线下）。代价是**真实用户在极端情况下也会被静默丢弃且毫不知情**。
  - 全局上限是一刀切的，不区分来源。真有一天来了 30 条以上的真实反馈会被误伤。

#### 4.2 周月报负载瘦身

- **做了什么**：对外读取路径剥掉 8 个文章正文字段。
- **为什么**：一份月报 476 条、16.6 MB，其中正文占 96%，而页面一个都不用
  （只渲染标题/理由/标签/来源数，每个板块只展示前 3 条）。是加缓存时被 Next 的
  "items over 2MB can not be cached" 构建警告暴露出来的。
- **作用**：**16.61 MB → 1.12 MB（15 倍）**，也重新落回 Next 数据缓存的 2MB 上限内。
- **优点**：用"剥掉哪些"而不是"保留哪些"——将来加了新字段，页面能直接用上，
  不会因为忘了加白名单而神秘地读不到值。
- **缺点**：将来若新增了别的重字段，要记得补进这份 denylist，否则负载会重新长回去。
- **注意**：只作用于对外读取。生成 AI 摘要那条路径拿的仍是完整数据。

#### 4.3 信源连续失败告警

- **做了什么**：连续失败 ≥3 次的信源单独推一条 Telegram，不淹在 65 行的同步报告里。
- **为什么**：像 `aihot_content` 这类 best-effort 抓取器**不抛异常**，抓不到就降级，
  同步报告里那一行看着仍然是绿的。而 AIHOT 刚上了自动封禁策略，我们一旦被划进去
  会完全无感。
- **作用**：静默失效变成有声失效。
- **缺点 / 代价**：阈值 3 次是估的；而且它**只覆盖"失败"，覆盖不了"成功但内容悄悄变少"**
  这种更隐蔽的降级——那需要对入库量做基线比对，目前没做。

---

### 第 5 层 · 可观测与运维

#### 5.1 nginx 自定义日志格式

- **做了什么**：日志里补上真实 IP、`$request_time`、`$upstream_cache_status`、`CF-Ray`。
- **为什么**：默认的 combined 格式缺的恰恰是出事时唯一有用的三样。
- **作用**：**本次所有性能结论都来自这个字段**——从 Mac 上量的数字全是代理链路噪声，
  从源站本机量的又全是 403 的耗时，只有这里的 `$request_time` 是可信的。
  没有 `$upstream_cache_status` 就无法判断"站点变慢"是缓存失效还是被打了。
- **缺点**：日志行更长，体积增加（已由留存策略兜住）。

#### 5.2 日志留存 `json-file 50m × 20`

- **做了什么 / 为什么**：docker 默认的 json-file **不轮转**，会一直涨到撑爆磁盘；
  而没有留存策略又意味着出事后无从取证。原文作者能复盘出完整攻击链全靠访问日志，
  事后把留存拉到了一年。
- **作用**：每个服务约 1GB，nginx 那份足够回溯很久。
- **缺点**：占磁盘（33G 的机器上可接受）。

#### 5.3 `scripts/traffic_top.sh`

- **做了什么 / 为什么**：把"出事时该看什么"固化成一条命令——按 IP / UA / 路径 / 状态码 /
  缓存命中 / 慢请求出 Top N。真被打的时候没人有心情现敲 awk。
- **缺点**：依赖 5.1 的日志格式，格式改了要同步改。

---

### 10.6 全局账：这套东西的总体代价

**① 数据新鲜度：从"实时"变成"最多约 5 分钟"**

| 层 | TTL |
|---|---|
| CF 边缘 | 120s（API 60s） |
| nginx | 180s（API 60s） |
| Next 数据缓存 | 60~600s |

最坏情况叠加约 5 分钟。AR 的数据本身来自每天几次的 pipeline 推送，这个取舍是划算的；
但**它意味着"改了没生效"从此多了三种可能**。管理员带真 token 访问时三层全绕过，
所以后台校对不受影响。

**② 新增了几个必须人工同步的耦合点** —— 这是长期维护成本的主要来源：

| 耦合点 | 漏了会怎样 |
|---|---|
| 查询参数白名单（§2.2） | 新参数被静默丢弃，筛选/翻页失效 |
| snippet 挂载清单（事故一） | nginx 启动即失败，整站 521 |
| CF 规则 ↔ 源站响应头（§2.5） | 边缘缓存不生效，或私有内容被缓存 |
| ADMIN_TOKEN 长度 ↔ map 桶（事故四） | nginx 启动即失败 |
| 周月报 denylist（§4.2） | 负载重新长回去 |
| 前后端参数上下限（§3.4） | 越界值又变成空页面 |

**③ 发布健康检查出现了新盲区**：CF 缓存会让健康检查在源站已死的情况下照样返回 200。
修法见第八节末尾（给健康检查 URL 挂随机参数）。**这条尚未落实到部署脚本里。**

**④ 调试复杂度上升**：一个响应现在要经过 CF 缓存 → nginx 缓存 → Next 数据缓存三层，
排查"为什么看到的是旧的"需要逐层确认（`cf-cache-status` → `X-Cache-Status` → 数据层）。

---

### 10.7 如果只能保留一项

**§2.2 的缓存键规范化 + 参数剥离。**

不是因为它性能收益最大（那是第 1 层），而是因为它同时消灭了两类问题：
随机参数骗缓存这个标准攻击手法，以及缓存投毒这个隐蔽的正确性问题。
其余各项要么是它的放大器（CF 边缘、nginx 缓存），要么是它的补充（限流、告警）。

---

## 附录：阶段 1-1 的本地验证方法

改 nginx 配置最怕"发上去才发现不对"。这次的做法是**在 Mac 上把整条链路复现一遍**，
所有验收项跑完再发布。可复用：

1. 拷一份 `infra/nginx/` 到临时目录，把 `cloudflare-ips.conf` 换成
   `geo $realip_remote_addr $from_cloudflare { default 1; }`（跳过 CF 白名单），
   **`radar-cf.conf` 保持原样不动** —— 被测对象不能改。
2. 起一个假上游冒充 Next：回显 `$request_uri` + 一个唯一请求 ID，
   并发同样的 `Cache-Control: no-store` 和 `Vary: rsc, ...` 响应头。
   响应体里的唯一 ID 就是判据：**两次请求 ID 相同 = 真的命中了缓存**，
   光看 `X-Cache-Status` 不够（它只说 nginx 认为自己命中了）。
3. 验收清单跑一遍（缓存命中 / 随机参数折叠 / 合法参数独立 / 翻页独立 /
   投毒防护 / admin 与 RSC 绕过 / 各不缓存路径）。
4. 把假上游换成"每次响应耗时 2 秒"的 Python 版本，验合单与宕机兜底。

实测结果：

- **合单**：50 个并发同时请求同一页面 → **上游只被调用 1 次**，总耗时 2s。
  没有这条，就是 50 次并发 SSR —— 这正是缓存击穿时的样子。
- **宕机兜底**：停掉上游后，已缓存页面照常 200 HIT，未缓存路径才 502。
  整库同步那 2~3 秒的重启窗口从此对用户不可见。
