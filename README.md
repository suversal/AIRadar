# Suversal AI Radar

Data-first AI intelligence radar. The first milestone is a reliable local loop:

1. Seed broad but low-risk sources.
2. Crawl public RSS/API/HTML sources.
3. Prefilter, score, cluster, and select AI events.
4. Generate a concise Markdown and JSON daily report.

## Current Scope

This repository intentionally starts backend-first. It includes a pure-Python
pipeline that can run with `FakeAIProvider` when `OPENAI_API_KEY` is missing,
plus Docker/PostgreSQL/Redis scaffolding for the production-shaped runtime.

Not in this milestone: full frontend, admin UI, Telegram push, MCP server.

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
```

Generated articles, reports, and crawl diagnostics are written under `data/`,
which is ignored by git.

## Docker Runtime

Install Docker Desktop first, then:

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d postgres redis
python3 scripts/check_db_once.py
```

To persist one fake-AI pipeline run into the local Docker Postgres from the host:

```bash
.venv/bin/python scripts/run_pipeline_once.py --limit 20 --top-n 12 --fake-ai --persist-db --database-url postgresql+psycopg://radar:radar@localhost:5432/radar --date 2026-07-02
```

To build and run the API container after the base database stack is healthy:

```bash
docker compose -f infra/docker-compose.yml up --build api
```

The API exposes:

- `GET /health`
- `GET /api/public/latest`
- `GET /api/public/daily/{date}`

## Environment

Required for real AI processing:

- `OPENAI_API_KEY`

Optional:

- `GITHUB_TOKEN`

The scripts automatically use `FakeAIProvider` when no OpenAI key is present or
when `--fake-ai` is passed.
