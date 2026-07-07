# Suversal AI Radar Implementation Notes

## Decisions Locked For The First Milestone

- Prioritize data quality before frontend polish.
- Produce a concise Markdown daily report and JSON payload.
- Support OpenAI, Kimi/Moonshot, and DeepSeek chat providers, but keep a fake deterministic provider for local dry runs.
- Use broad first-batch coverage: official sources, HN, arXiv, GitHub, Reddit, and Chinese media.
- Keep source failures isolated and visible instead of blocking the whole run.
- Cap daily candidates at 100 and selected events at 8-12 by default.
- Preserve structured original article content when feeds provide it, including paragraph blocks and image URLs for event detail pages.

## Current Engineering Shape

- `apps/api/app/models/domain.py`: pure domain dataclasses used by tests and scripts.
- `apps/api/app/crawlers`: RSS, HN, and GitHub crawler adapters; RSS now extracts original paragraphs, image URLs, and ordered content blocks from feed HTML.
- `apps/api/app/services`: AI boundary, scoring, clustering, and report generation. `ai_service.py` includes OpenAI, Kimi/Moonshot, DeepSeek, and fake providers.
- `apps/api/app/services/daily_report_service.py`: daily JSON includes `original_url`, `original_paragraphs`, `original_images`, and `original_blocks` for the main article in each event.
- `apps/api/app/pipeline/runner.py`: in-process pipeline orchestration for Phase 0. Candidate AI prefiltering, scoring, and embeddings can run concurrently through `ai_concurrency`.
- `apps/web/app/event/[id]/page.tsx`: event detail is an article-reading view with recommendation reason, AI summary, original content, tags, and read-original actions.
- `scripts`: local CLI entrypoints for seed, crawl, pipeline, and report output. `run_pipeline_once.py` supports `--ai-concurrency`; API refresh reads `AI_PIPELINE_CONCURRENCY`.
- `infra`: Docker Compose and PostgreSQL schema with pgvector.

## Next Milestone After 7-Day Observation

- Persist pipeline writes into PostgreSQL instead of JSON files.
- Add Celery/Redis async tasks.
- Add frontend MVP pages for latest, daily, and event detail.
- Add admin-only source and event correction tools.
