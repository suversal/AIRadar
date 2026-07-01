# Suversal AI Radar Implementation Notes

## Decisions Locked For The First Milestone

- Prioritize data quality before frontend polish.
- Produce a concise Markdown daily report and JSON payload.
- Use OpenAI by default, but keep a fake deterministic provider for local dry runs.
- Use broad first-batch coverage: official sources, HN, arXiv, GitHub, Reddit, and Chinese media.
- Keep source failures isolated and visible instead of blocking the whole run.
- Cap daily candidates at 100 and selected events at 8-12 by default.

## Current Engineering Shape

- `apps/api/app/models/domain.py`: pure domain dataclasses used by tests and scripts.
- `apps/api/app/crawlers`: RSS, HN, and GitHub crawler adapters.
- `apps/api/app/services`: AI boundary, scoring, clustering, and report generation.
- `apps/api/app/pipeline/runner.py`: in-process pipeline orchestration for Phase 0.
- `scripts`: local CLI entrypoints for seed, crawl, pipeline, and report output.
- `infra`: Docker Compose and PostgreSQL schema with pgvector.

## Next Milestone After 7-Day Observation

- Persist pipeline writes into PostgreSQL instead of JSON files.
- Add Celery/Redis async tasks.
- Add frontend MVP pages for latest, daily, and event detail.
- Add admin-only source and event correction tools.

