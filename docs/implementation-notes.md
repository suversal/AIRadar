# Suversal AI Radar Implementation Notes

## Decisions Locked For The First Milestone

- Prioritize data quality before frontend polish.
- Produce a concise Markdown daily report and JSON payload.
- Support OpenAI, Kimi/Moonshot, and DeepSeek chat providers, but keep a fake deterministic provider for local dry runs.
- Use broad first-batch coverage: official sources, HN, arXiv, GitHub, Reddit, and Chinese media.
- Keep source failures isolated and visible instead of blocking the whole run.
- Cap daily candidates at 100 and selected events at 8-12 by default.
- Preserve structured original article content when feeds provide it, including paragraph blocks and image URLs for event detail pages.
- Enrich selected GitHub Trending repositories with README content after report selection, with short-description fallback on GitHub API errors or rate limits.
- Generate optional Chinese translation blocks only for selected English main articles, so detail pages can offer 原文/译文 comparison without translating every candidate. GitHub README Markdown is treated as canonical original content and is rendered directly instead of being translated into the body view.
- Keep `/latest` as the AIHOT-style selected feed. Search stays out of `/latest`; `/all` owns the all-dynamics filters and inline search. `/daily`, `/weekly`, and `/monthly` own the report-reading flow under the "AI 日报" menu. Sidebar items beyond "精选", "全部 AI 动态", and "AI 日报" remain placeholders until their data contracts are defined.

## Current Engineering Shape

- `apps/api/app/models/domain.py`: pure domain dataclasses used by tests and scripts.
- `apps/api/app/crawlers`: RSS, HN, GitHub, and sitemap crawler adapters. `base.fetch_url_text` is the shared HTTP helper: browser-like User-Agent, retry with backoff on 429/500/502/503/504. `run.crawl_sources` enforces a 6-second politeness delay between sources on the same domain (Reddit rate limits). The sitemap crawler (`sitemap.py`) targets sites without RSS (currently Anthropic News): it reads sitemap.xml, filters URLs by `config.path_prefix`, sorts by lastmod, and extracts each page's title/description; `config.max_pages` bounds page fetches. 机器之心 RSS now returns HTML and was removed from defaults; RSS extracts original paragraphs, image URLs, and ordered content blocks from feed HTML; GitHub README enrichment checks selected repositories for root-level Chinese README files before falling back to the default README, then preserves bounded README Markdown for detail-page rendering.
- `apps/api/app/services`: AI boundary, scoring, clustering, and report generation. `ai_service.py` includes OpenAI, Kimi/Moonshot, DeepSeek, and fake providers.
- `apps/api/app/services/daily_report_service.py`: daily JSON includes `source_language`, `original_url`, optional `original_markdown`, README diagnostics, `original_paragraphs`, `original_images`, `original_blocks`, and optional `translated_paragraphs`/`translated_blocks` for the main article in each event.
- `apps/api/app/pipeline/runner.py`: in-process pipeline orchestration for Phase 0. Candidate AI prefiltering, scoring, and embeddings can run concurrently through `ai_concurrency`; selected GitHub report articles can receive README original content, and selected English report articles can receive bounded paragraph translation before JSON generation unless the selected README is already Chinese. One-off audit runs can set `skip_prefilter=True` to score and report every candidate instead of dropping non-AI-prefiltered items.
- `apps/web/app/latest/page.tsx`: AIHOT-style selected homepage with fixed sidebar, reserved menu labels, category tabs, top hotspots, date-collapsible event stream, and no inline search box in this iteration.
- `apps/web/app/all/page.tsx`: AIHOT-style all AI dynamics page with active sidebar, source-type filters, category filters, inline search, date-collapsible timeline, score badges, optional original image, tags, recommendation reason, and event detail links. It consumes `GET /api/public/events`, which merges daily report payloads over a date range (default 30 days) and dedupes by `event_id`, newest report wins.
- `apps/web/app/reports`: shared AIHOT report shell, report mode tabs, daily digest helpers, and period report helpers.
- `apps/web/app/daily/page.tsx`: AIHOT-style daily report page with today highlights, stats, category sections, and Markdown copy. `/daily/[date]` remains as the dated report compatibility view.
- `apps/web/app/weekly/page.tsx` and `apps/web/app/monthly/page.tsx`: AIHOT-style period report pages with mainline summary, stats, highlights, and theme sections. They consume `GET /api/public/reports/weekly[/{date}]` (trailing 7 days) and `GET /api/public/reports/monthly[/{YYYY-MM}]` (calendar month), which aggregate daily reports over the true period range. Like latest/daily, all new endpoints read the repository when `DATABASE_URL` is set and fall back to `data/reports/*.json` otherwise.
- `apps/web/app/event/[id]/page.tsx`: event detail keeps the AIHOT left navigation visible while reading, with recommendation reason, AI summary, original content, README Markdown rendering when available, optional AI translation/original toggle, tags, and read-original actions.
- `scripts`: local CLI entrypoints for seed, crawl, pipeline, and report output. `run_pipeline_once.py` supports `--ai-concurrency` and `--skip-prefilter`; API refresh reads `AI_PIPELINE_CONCURRENCY`.
- `infra`: Docker Compose and PostgreSQL schema with pgvector.

## Next Milestone After 7-Day Observation

- Persist pipeline writes into PostgreSQL instead of JSON files.
- Add Celery/Redis async tasks.
- Add a true all-events API for `/all`, dedicated period report APIs for `/weekly` and `/monthly`, then implement the remaining reserved sidebar pages: topics, bookmarks, agent access, about, changelog, and feedback.
- Add admin-only source and event correction tools.
