# Admin Sync Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix refresh persistence identity, enrich the run ledger, add button timing, and filter admin content by configured main source in crawl-time order.

**Architecture:** Reuse the database raw article ID at the pipeline boundary whenever a URL hash is cached. Keep ledger enhancements presentation-only. Add main source identity to event payloads and apply admin-specific filtering/sorting before pagination.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, React/Next.js, TypeScript, pytest.

## Global Constraints

- No new pipeline ledger database columns.
- Source filtering matches only the configured main source.
- Manual refresh progress and result stay inside the button.
- Content management sorts by `crawled_at` descending, then `published_at` descending.

---

### Task 1: Reuse persisted raw article identity

**Files:**
- Modify: `apps/api/app/repositories/radar_repository.py`
- Modify: `apps/api/app/pipeline/runner.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_repositories.py`

**Interfaces:**
- Produces: cached payload key `raw_article_id: str`.
- Consumes: runner assigns `article.id = cached["raw_article_id"]` before downstream processing.

- [ ] Add failing tests proving cached identity becomes the embedding and processed identity.
- [ ] Run focused tests and confirm the generated identity is incorrectly retained.
- [ ] Return and apply `raw_article_id` at the cache boundary.
- [ ] Run focused tests and confirm they pass.

### Task 2: Main-source filter and crawl-time ordering

**Files:**
- Modify: `apps/api/app/repositories/radar_repository.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/web/app/admin/events/page.tsx`
- Modify: `apps/web/app/admin/events/events-manager.tsx`
- Test: `tests/test_api_main.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_web_app_structure.py`

**Interfaces:**
- Produces: `main_source.id` in event payloads.
- Consumes: admin query parameter `source_id` and configured source options.

- [ ] Add failing API and payload tests for source identity, filter, and ordering.
- [ ] Implement payload identity and API filtering/sorting before pagination.
- [ ] Add the source selector and preserve it through all navigation forms.
- [ ] Run API and Web structure tests.

### Task 3: Ledger and timed refresh button

**Files:**
- Modify: `apps/web/app/admin/page.tsx`
- Modify: `apps/web/app/admin/refresh-report-button.tsx`
- Test: `tests/test_web_app_structure.py`

**Interfaces:**
- Consumes: existing run `started_at`, `finished_at`, counts, skipped reasons, and error.
- Produces: duration/error ledger cells and button-local elapsed/result labels.

- [ ] Add failing structure assertions for end time, duration, detailed errors, and button timer labels.
- [ ] Implement ledger duration/error rendering and button-local timer state.
- [ ] Run Web structure tests and TypeScript typecheck.

### Task 4: End-to-end verification

- [ ] Run `.venv/bin/python -m pytest -q` and require zero failures.
- [ ] Run `npm run typecheck` and `npm run build` under `apps/web`.
- [ ] Trigger one manual refresh and verify it finishes without an embedding foreign-key violation.
- [ ] Verify the admin events endpoint filters by `source_id` and returns descending crawl timestamps.
