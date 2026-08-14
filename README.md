# Suversal AI Radar

Data-first AI intelligence radar. The first milestone is a reliable local loop:

1. Seed broad but low-risk sources.
2. Crawl public RSS/API/HTML sources.
3. Prefilter, score, cluster, and select AI events.
4. Generate a concise Markdown and JSON daily report.

## Current Scope

This repository intentionally starts data-first. It includes a pure-Python
pipeline that can run with `FakeAIProvider` when no AI key is configured,
or use OpenAI/Kimi/DeepSeek-compatible chat providers for real summaries and scoring.
Docker/PostgreSQL/Redis scaffolding is included for the production-shaped runtime.
The current product includes selected and all-dynamics feeds, daily/weekly/monthly
reports, topics, search, browser-local bookmarks, semantic article reading, and
static Agent/About/Changelog/Feedback pages. The database-backed admin console
covers source operations, pipeline/schedule monitoring, content moderation, and
a feature-gated manual article draft/publish workflow.

Current focus: source quality, source-specific content extraction, manual-publish
acceptance, and multi-day operational stability. Celery/Redis workers, public
RSS/API productization, multi-admin permissions, and MCP remain deferred.

## Local Commands

Create a local virtualenv when you want to run dependency-backed tests such as
SQLAlchemy repository tests:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/seed_sources.py
python3 scripts/run_crawl_once.py --limit 100 --report data/crawl_report.json
python3 scripts/run_pipeline_once.py --limit 100 --fake-ai
python3 scripts/build_daily_report.py --date 2026-07-01 --format markdown
python3 scripts/check_db_once.py
.venv/bin/python scripts/check_api_once.py --base-url http://127.0.0.1:8000 --date 2026-07-02
```

For the Phase 6 web app:

```bash
cd apps/web
npm install
npm run typecheck
npm run build
AI_RADAR_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Open `http://127.0.0.1:3000/latest` for the current homepage, or
`http://127.0.0.1:3000/all` for the all AI dynamics feed. The homepage keeps
search out of the selected feed; `/all` has its own source/category filters and
inline search, backed by `GET /api/public/events`. In database mode, this page
lists processed source articles independently so that related reports from
different publishers remain available instead of being collapsed into one event.

Report pages:

- `http://127.0.0.1:3000/daily`
- `http://127.0.0.1:3000/weekly`
- `http://127.0.0.1:3000/monthly`

Weekly and monthly pages read the dedicated period report APIs
(`GET /api/public/reports/weekly[/{date}]` for the trailing 7 days and
`GET /api/public/reports/monthly[/{YYYY-MM}]` for the calendar month), which
aggregate daily reports over the true period range.

Generated articles, reports, and crawl diagnostics are written under `data/`,
which is ignored by git.

## Admin Console

Set `ADMIN_TOKEN` in `.env`, then open `http://127.0.0.1:3000/admin` and
log in with the token. The console provides source health monitoring and
management (enable/disable/edit/test-fetch), the pipeline run ledger,
manual refresh/scheduling, content moderation (filter/edit/hide/preview/delete),
and safe source deletion. When `ADMIN_MANUAL_ARTICLE_ENABLED=true`, the console
also exposes URL import and rich-text drafts, AI processing, manual field
overrides, optional image upload, and publication. All
`/api/admin/*` endpoints require the token; database mode is required.

## Scheduled Refresh

`scripts/run_scheduled_refresh.sh` runs one crawl + pipeline pass with a lock
against overlapping runs; logs land in `data/logs/refresh.log`. Thanks to
incremental caching only newly crawled articles cost AI calls. To run it every
2 hours via launchd:

```bash
cp infra/launchd/com.suversal.ai-radar.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.suversal.ai-radar.refresh.plist
```

To stop it: `launchctl unload ~/Library/LaunchAgents/com.suversal.ai-radar.refresh.plist`.
Database persistence requires the Docker Postgres to be running; if it is
down, reports still land under `data/reports/` and only the DB write fails.

## Web Analytics

Self-hosted [Umami](https://umami.is) runs as the `umami` service in
`infra/docker-compose.prod.yml` (production only — the local compose file has no
analytics). Selection rationale and the retention caveats below are recorded in
`docs/notes/2026-08-14-analytics-selection.md`.

- Tracker script: `https://radar.suversal.com/s.js`
- Collect endpoint: `POST https://radar.suversal.com/api/collect`
- Dashboard: `https://stats.suversal.com` (default login `admin` / `umami` —
  change it immediately)

Both tracker paths are deliberately non-default and must stay in sync across
three places, or tracking silently 404s: `TRACKER_SCRIPT_NAME` /
`COLLECT_API_ENDPOINT` in the compose file, the two exact-match `location`
blocks in `infra/nginx/radar-cf.conf`, and `SCRIPT_SRC` in
`apps/web/components/analytics-script.tsx`.

First-time setup (the database must be created by hand — `infra/postgres/init.sql`
only runs when the volume is first initialized, and the existing volume is long
past that):

```bash
docker exec infra-postgres-1 psql -U radar -d postgres \
  -c "CREATE DATABASE umami OWNER radar;"
```

Then set `UMAMI_APP_SECRET` (`openssl rand -hex 32`) in the server's `.env`,
deploy, create a website in the dashboard, put its UUID in `UMAMI_WEBSITE_ID`,
and deploy again. Note that `UMAMI_WEBSITE_ID` is a **build arg**: it is inlined
by `next build`, so changing it requires rebuilding the web image, not just a
container restart.

**Retention has a hard limit worth knowing.** Umami's retention report is
`group by session_id`, and `session_id` is derived from a salt that rotates
monthly, so the dashboard's cohort numbers are only valid *within* a calendar
month — a visitor returning across a month boundary is counted as brand new.
For true cross-month retention, query `session.distinct_id` directly; the SQL is
in the note linked above.

## Docker Runtime

Install Docker Desktop first, then:

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d postgres redis
# Alembic owns the whole schema; a fresh database has no tables until:
(cd apps/api && DATABASE_URL=postgresql+psycopg://radar:radar@localhost:5432/radar ../../.venv/bin/alembic upgrade head)
python3 scripts/check_db_once.py
```

To persist one fake-AI pipeline run into the local Docker Postgres from the host:

```bash
.venv/bin/python scripts/run_pipeline_once.py --limit 20 --fake-ai --persist-db --database-url postgresql+psycopg://radar:radar@localhost:5432/radar --date 2026-07-02
```

To build and run the API container after the base database stack is healthy:

```bash
docker compose -f infra/docker-compose.yml up --build api
```

For host-side API smoke checks against Docker Postgres, set:

```bash
DATABASE_URL=postgresql+psycopg://radar:radar@localhost:5432/radar
PYTHONPATH=apps/api .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/bin/python scripts/check_api_once.py --base-url http://127.0.0.1:8000 --date 2026-07-02
```

The public API exposes:

- `GET /health`
- `GET /api/public/latest`
- `GET /api/public/daily/{date}`
- `GET /api/public/events`
- `GET /api/public/events/{id}`
- `GET /api/public/hotspots`
- `GET /api/public/topics`
- daily/weekly/monthly report and archive endpoints

The authenticated admin API additionally exposes source CRUD/test-fetch,
content moderation/delete/preview, refresh/schedule, and manual article
submission routes.

`POST /api/admin/refresh-latest` starts a synchronous refresh without a request
level candidate limit. Each source controls its own lookback through
`recent_days` (`0` means unlimited), while AI scoring concurrency is controlled
by `AI_PIPELINE_CONCURRENCY`, default `1`. Selected report size is dynamic and
has no fixed item count.

Web refreshes use the asynchronous endpoint and poll the job status, so slow
Kimi runs do not depend on a single Next.js request staying open. The report
`updated_at` field is the report generation time; `latest_published_at` records
the newest source article time. Trusted curated sources skip only the
lightweight prefilter and still pass through normal scoring and event
selection; there is no low-score fill.

Event detail pages read structured original article fields from the daily JSON
payload. RSS feeds that include article HTML, such as IT之家 RSS, are parsed into
`original_paragraphs`, `original_images`, and ordered `original_blocks`, so the
detail page can render the source article text and images before linking out to
the original URL. Selected GitHub Trending repositories are enriched with README
content after final report selection. The helper first checks the repository
root for Chinese README files such as `README_zh.md` or `README_CN.md`; if none
works, it falls back to GitHub's default README. GitHub README payloads preserve
bounded `original_markdown` for in-app Markdown rendering (up to 80KB) while
also keeping paragraph/image blocks for translation and fallback display.
Existing reports need to be refreshed before this Markdown field appears. For
selected English main articles, the pipeline can also add `translated_paragraphs`
and ordered `translated_blocks`; Chinese README payloads are shown directly and
skip AI translation.

## Environment

Required for real AI processing, choose one provider:

- `OPENAI_API_KEY`
- `KIMI_API_KEY` or `MOONSHOT_API_KEY`
- `DEEPSEEK_API_KEY`

Optional:

- `AI_PROVIDER=qwen|openai|kimi|deepseek|fake`
- `ALI_API_KEY` (or `DASHSCOPE_API_KEY`) selects Alibaba Bailian (qwen) when
  `AI_PROVIDER` is unset. Bailian speaks the OpenAI-compatible dialect, so it
  reuses the same provider plumbing as DeepSeek — with two differences that
  are measured, not assumed, and both encoded in `QwenProvider`:
  `reasoning_effort` is *silently ignored* by qwen3.7 (only `enable_thinking`
  and `thinking_budget` work), and caching is not automatic — the scoring
  prefix carries an explicit `cache_control` marker.
- `ALI_BASE_URL`, default `https://dashscope.aliyuncs.com/compatible-mode/v1`;
  a workspace-specific `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
  host is faster and more stable.
- `QWEN_MODEL`, default `qwen3.7-flash`
- `QWEN_MAX_TOKENS`, default `4096`
- `QWEN_THINKING_BUDGET`, default `50`; caps reasoning tokens on scoring calls
  only. Measured across 0/50/100/200 on 64 stratified articles: category
  agreement does not improve with budget (73–80%, no trend), but run-to-run
  stability does (90% → 94%, against DeepSeek's 84%). 50 scored highest on
  agreement with zero failures. `0` disables scoring thinking entirely for
  another ~1.5%.
- `KIMI_MODEL`
- `KIMI_BASE_URL`, default `https://api.moonshot.cn/v1`
- `DEEPSEEK_MODEL`, default `deepseek-v4-flash`
- `DEEPSEEK_BASE_URL`, default `https://api.deepseek.com`
- `DEEPSEEK_USER_ID`, optional isolation id for DeepSeek requests
- `DEEPSEEK_MAX_TOKENS`, default `2048`
- `DEEPSEEK_SCORING_REASONING_EFFORT`, default `low`; one of `off|low|high|max`.
  DeepSeek defaults to thinking mode at `high` effort and bills every thinking
  token at the output rate, so prefilter, same-event verification and
  translation always run with thinking disabled — they return one determinate
  structured answer, where deliberation buys nothing. Only article scoring
  thinks, at this effort. Measured against 50 real articles, dropping from the
  API default to `low` cut spend ~46% with no quality change beyond the model's
  own run-to-run noise. Raise it if scoring quality regresses; `off` disables
  thinking there too.
- `AI_PIPELINE_CONCURRENCY`, default `1`; set higher for providers with high concurrency limits.
- `GITHUB_TOKEN`, optional but recommended for README enrichment to reduce GitHub API rate-limit failures.
- `GITHUB_TOKEN`

Web analytics (production only, see the Web Analytics section above):

- `UMAMI_APP_SECRET`, required by the `umami` service; `openssl rand -hex 32`
- `UMAMI_DB_NAME`, default `umami`
- `UMAMI_WEBSITE_ID`, the dashboard's website UUID. Passed as a **build arg** to
  `next build` and inlined into the output, so changing it needs an image
  rebuild. Empty means the tracking component renders nothing at all, which is
  why local dev never sends analytics.

The scripts and refresh endpoint automatically use `FakeAIProvider` when no AI
key is present or when `--fake-ai` is passed. Kimi and DeepSeek use
OpenAI-compatible chat APIs for prefiltering and scoring; embeddings currently
fall back to deterministic local vectors so the clustering pipeline still runs.
DeepSeek `deepseek-v4-flash` has a high server-side concurrency quota. The
pipeline can process candidate AI scoring concurrently via
`AI_PIPELINE_CONCURRENCY` or `scripts/run_pipeline_once.py --ai-concurrency`.
Host-side API and pipeline runs load missing values from the local ignored
`.env` file, while already-exported environment variables take precedence.
