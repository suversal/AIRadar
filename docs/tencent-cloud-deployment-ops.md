# HotAI 腾讯云部署与运维手册

> 整理日期：2026-07-24
> 服务器：腾讯云轻量应用服务器（Lighthouse）2C2G，Ubuntu 24.04，公网 IP `175.24.182.233`
> 登录方式：`ssh ubuntu@175.24.182.233`（密钥登录）
> 部署目录：`/home/ubuntu/hotai/`

---

## 一、整体架构

**核心设计：服务器只读展示，数据加工全部在本地 Mac 完成。**

原因：大陆服务器无法直接访问 GitHub、X 等外部数据源，所以爬取、AI 打分等重活由本地跑，跑完把结果写入 / 同步到服务器数据库。

```
┌─────────────── 本地 Mac ───────────────┐
│  爬虫 (run_crawl_once.py)              │
│  AI 打分 / 聚类 pipeline               │
│  本地 Postgres（开发库）               │
└──────────────┬─────────────────────────┘
               │ scripts/sync_db_to_server.sh（pg_dump → scp → 整库替换）
               ▼
┌────────── 腾讯云 175.24.182.233 ──────────┐
│  nginx:80 ──► web (Next.js:3000)          │
│                 │                         │
│                 ▼                         │
│              api (FastAPI:8000)           │
│                 │          │              │
│                 ▼          ▼              │
│         postgres:5432   redis:6379        │
│      (pgvector/pg16, 仅127.0.0.1) (仅内网) │
└───────────────────────────────────────────┘
```

对外暴露的端口只有两个：

| 端口 | 服务 | 说明 |
|---|---|---|
| 80 | nginx | 唯一的 Web 入口，反代到 Next.js |
| 22 | sshd | 密钥登录 |

Postgres 只绑定服务器 127.0.0.1（控制台防火墙也不要放行 5432）；Redis、API(8000)、Web(3000) 均只在 Docker 内网。

---

## 二、本次部署做了哪些事

按实际执行顺序：

### 1. 服务器初始化
- 安装 Docker 29.1.3、Docker Compose v2.40.3、rsync；`ubuntu` 用户加入 docker 组（免 sudo）。
- 配置 `/etc/docker/daemon.json` 镜像加速（按优先级）：`mirror.ccs.tencentyun.com` → `docker.1ms.run` → `docker.m.daocloud.io`。

### 2. 构建配置的国内网络适配
- [Dockerfile.api](../infra/Dockerfile.api)：新增 `PIP_INDEX_URL` 构建参数，生产默认走腾讯 PyPI 镜像 `mirrors.cloud.tencent.com/pypi/simple`。
- [Dockerfile.web](../infra/Dockerfile.web)：`NPM_REGISTRY` 默认走 `registry.npmmirror.com`。
- 新增 [docker-compose.prod.yml](../infra/docker-compose.prod.yml)：5 个服务（postgres/redis/api/web/nginx），每个服务都设了内存上限（合计约 1.6G，适配 2G 内存机器），postgres/redis 带健康检查。
- 新增 [nginx/radar.conf](../infra/nginx/radar.conf)：80 端口反代 web:3000，`client_max_body_size 12m`（大于图片上传上限 10MiB，保证 nginx 不是拒绝上传的那一环）。

### 3. 代码与配置上服务器
- `rsync` 同步源码到 `/home/ubuntu/hotai/`（约 3.3M，排除 .git、node_modules、.next、.venv、data、.env 等）。
- 在服务器上生成 `/home/ubuntu/hotai/.env`（权限 600），包含：
  - 随机生成的 `POSTGRES_PASSWORD`（32 hex）、`JWT_SECRET`（64 hex）、`ADMIN_TOKEN`（48 hex）；
  - `DATABASE_URL` 指向 Docker 内网 `postgres:5432`，`REDIS_URL` 指向 `redis:6379`；
  - LLM API key 留空占位（服务器不跑 pipeline，用不到）；
  - 管理端的手动发文 / 图片上传等功能在生产关闭。

### 4. 构建与启动
- 服务器上 `docker compose -f docker-compose.prod.yml build`（web 构建约 25 秒）。
- `docker compose up -d`，5 个容器全部健康运行。
- 在 api 容器内执行 `alembic upgrade head`，应用了全部 5 个迁移，建好 18 张表。

### 5. 外网联通排障（重要经验）
初次部署后外网访问失败，排查结论：

- **腾讯云对未在防火墙放行的端口不是拒绝连接，而是边缘设备"默默完成 TCP 握手然后吞掉请求"**——表现为 `curl` 能连上但收到 Empty reply，非常像应用层故障，实际是防火墙没放行。**以后遇到"能连上但无响应"，先查 Lighthouse 控制台防火墙。**
- 在控制台放行 80 端口后外网访问即恢复正常。
- 另一个已知怪癖：**服务器无法访问自己的公网 IP**（hairpin 回环被腾讯云 raw PREROUTING 规则挡掉），所以在服务器上 `curl http://175.24.182.233` 失败是正常现象，不代表服务挂了；自检请用 `curl http://localhost`。

### 6. 数据同步与验证
- `.env` 本地配置修复后，本地跑了一次完整爬取（39 个源，3393 篇文章）。
- 用 `pg_dump -Fc` 把本地库导出 → scp 到服务器 → `pg_restore` 恢复 → 重启 api，网站数据正常展示。
- 中途试过把 5432 开到公网让本地 pipeline 直连远程库，最终放弃（公网数据库端口风险 + 本地页面查远程库变慢），回到"本地闭环 + 整库推送"。
- 验证：`/latest`、`/all`、`/daily` 均返回 200，首页响应约 220ms，页面渲染正常。

---

## 三、日常运维手册

### 3.1 常用连接

```bash
ssh ubuntu@175.24.182.233
```

所有 compose 命令都在服务器的 `~/hotai/infra` 目录下执行（下文省略 `-f docker-compose.prod.yml`，实际需要带上，或先 `cd ~/hotai/infra`）：

```bash
ssh ubuntu@175.24.182.233 "cd ~/hotai/infra && docker compose -f docker-compose.prod.yml ps"
```

### 3.2 查看状态与日志

```bash
docker compose -f docker-compose.prod.yml ps
```

```bash
docker compose -f docker-compose.prod.yml logs -f --tail=100 api
```

（服务名可换成 `web` / `nginx` / `postgres` / `redis`）

### 3.3 发布新版本代码（一键脚本）

改完代码后本地执行一条命令，覆盖"rsync → 重建镜像 → 重启 → 迁移 → 健康检查"全流程：

```bash
bash scripts/deploy_to_server.sh
```

只改了一端时可以加参数少等一会儿：`... deploy_to_server.sh web`（仅前端）或 `... deploy_to_server.sh api`（仅后端）。

安全性设计：

- 服务器上**构建失败会直接终止**，旧版本容器继续在线，不会出现"构建到一半线上挂掉"；
- 健康检查会依次探测 `/latest` `/all` `/daily`，任何一个非 200 都以失败退出；
- rsync 排除规则里 `/data` 带前导斜杠（只排除仓库根目录的 data/）——裸写 `data` 会连 `apps/api/app/data/`（默认信源 Python 模块）一起排除，导致线上 `ModuleNotFoundError: No module named 'app.data'`、信源管理页 500，这是踩过的坑。

### 3.4 数据更新流程（核心日常操作）

数据链路完全在本地跑，跑完写远程库：

1. 本地爬取：`run_crawl_once.py`（参数是 `--sources` / `--output` / `--report`，**没有 `--limit`**）。
2. 本地跑 AI 打分 / 聚类 pipeline。
3. 推送到线上（整库覆盖远程数据，本地是唯一数据源）——默认手动执行，也可选启用自动同步：

- 应用内置调度器（`refresh_schedule` 表，每 120 分钟）在本地 API 进程里跑爬取 + 打分，结果写本地库；
- 可选的 launchd 看门狗 `com.suversal.ai-radar.autosync`（每 10 分钟）检查 `pipeline_runs`，发现新完成的运行且无运行中任务时，自动执行 `scripts/sync_db_to_server.sh`；是否启用以本机 `launchctl` 状态为准；
- 状态文件 `data/.last_synced_run` 记录已推送到的运行 id；日志在 `data/logs/autosync.log`。

手动推送随时可用：

```bash
bash scripts/sync_db_to_server.sh
```

脚本内部流程：本地 `pg_dump -Fc` → scp → 服务器 `DROP/CREATE DATABASE` + `pg_restore` → 关闭线上调度器（`UPDATE refresh_schedule SET enabled=false`，防止恢复进来的本地调度配置让服务器自己跑爬取）→ 重启 api → 行数与 HTTP 验证。本地 `DATABASE_URL` 保持指向本地库 `localhost:5432`，与线上无直接连接。

看门狗管理命令：

```bash
launchctl kickstart gui/$(id -u)/com.suversal.ai-radar.autosync   # 立即触发一次
```

```bash
launchctl bootout gui/$(id -u)/com.suversal.ai-radar.autosync    # 停用自动推送
```

### 3.5 备份（已自动化）

**本地库是唯一数据源，备份以本地库为准**（服务器只是它的覆盖副本，不需要单独备份）。

- launchd 任务 `com.suversal.ai-radar.backup` 每天 03:30（睡眠错过则唤醒后补跑）执行 `scripts/backup_local_db.sh`；
- 快照存放在 `~/Backups/hotai/radar-YYYYMMDD.dump`（约 21M/份）；
- 保留策略：每月 1 号的永久保留，其余保留 14 天；
- 脚本自带防护：当天已有备份不重复、产物小于 1M 视为异常丢弃（不会挤掉好备份）；日志在 `data/logs/backup.log`。

**从备份恢复本地库**（灾难时用，会覆盖本地现有数据）：

```bash
docker exec infra-postgres-1 psql -U radar -d postgres -c "DROP DATABASE radar WITH (FORCE);" && docker exec infra-postgres-1 psql -U radar -d postgres -c "CREATE DATABASE radar OWNER radar;" && docker exec -i infra-postgres-1 pg_restore -U radar -d radar --no-owner < ~/Backups/hotai/radar-快照日期.dump
```

恢复后跑一次 `bash scripts/sync_db_to_server.sh` 让线上同步回滚。

数据卷是 Docker named volume（本地与服务器同理），容器重建不丢数据；只有 `docker compose down -v` 才会删卷，**平时不要带 `-v`**。

### 3.6 密钥与凭证

全部在服务器 `~/hotai/.env`（权限 600）：

- `POSTGRES_PASSWORD` —— radar 库密码（仅服务器本机可连，密码用于容器内认证）
- `ADMIN_TOKEN` —— 管理后台登录令牌
- `JWT_SECRET` —— 会话签名

查看方式：

```bash
ssh ubuntu@175.24.182.233 "grep -E 'ADMIN_TOKEN|POSTGRES_PASSWORD' ~/hotai/.env"
```

### 3.7 故障排查速查表

| 现象 | 先查什么 |
|---|---|
| 外网能连上 80 但无响应（Empty reply） | Lighthouse 控制台防火墙是否放行该端口（腾讯云对未放行端口会完成握手再吞包，极易误判为应用故障） |
| 服务器上 curl 自己公网 IP 失败 | 正常现象（hairpin 回环被云侧规则拦截），改用 `curl http://localhost` 自检 |
| 网站 502/超时 | `docker compose ps` 看容器状态 → `logs web` / `logs api` |
| 数据不更新 | 本地 pipeline 是否跑完并成功写入远程库；`logs api` 看查询是否正常 |
| 内存吃紧（2G 机器） | `docker stats`；各容器已设内存上限（pg 512m / api 512m / web 384m / redis 160m / nginx 64m） |
| 镜像拉取慢或失败 | `/etc/docker/daemon.json` 三个国内镜像源是否正常 |

### 3.8 安全注意事项

- **5432 不对公网开放**：compose 里绑定 `127.0.0.1:5432:5432`，控制台防火墙也应删掉 5432 放行规则。数据同步只走 ssh（`scripts/sync_db_to_server.sh`）。若临时需要远程直连排查，用 SSH 隧道：`ssh -L 15432:localhost:5432 ubuntu@175.24.182.233`。
- `.env` 不进 git、不参与 rsync，只存在于服务器上；改动前先备份。
- 暂无 HTTPS。后续绑定域名后，建议在 nginx 容器加 certbot 或换 caddy 自动签发证书，并在控制台放行 443。

---

## 四、待办 / 后续优化

- [ ] Lighthouse 防火墙删除 5432 放行规则（架构已回到仅 ssh 同步，不需要公网 5432）
- [ ] 绑定域名 + HTTPS（放行 443）
- [x] 备份定时化——本地 launchd 每日 03:30 快照 + 14 天/每月留存策略，2026-07-24 完成并验证
- [x] 本地数据管道定时化——应用内置调度器（每 2h 刷新）+ launchd 看门狗（每 10min 自动推送），2026-07-24 完成并验证
