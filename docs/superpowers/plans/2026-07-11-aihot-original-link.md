# AI HOT Original Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the URL following `阅读原文：` in AI HOT RSS descriptions directly in `RawArticle.source_url`.

**Architecture:** Add one opt-in RSS source policy. The parser extracts an HTTP(S) URL from the raw description before normalizing the article; if no match exists, it retains the RSS item link.

**Tech Stack:** Python 3, ElementTree, regular expressions, pytest/unittest.

## Global Constraints

- Do not change other RSS sources.
- Do not add a database field or backfill historical rows.
- Fall back to the RSS item link when extraction fails.

---

### Task 1: Original URL extraction

**Files:**
- Modify: `apps/api/app/crawlers/rss.py`
- Modify: `apps/api/app/data/default_sources.py`
- Modify: `data/sources.json`
- Test: `tests/test_crawlers.py`
- Test: `tests/test_sources_and_storage.py`

**Interfaces:**
- Consumes: `Source.config["original_url_from_description"]: bool`
- Produces: `RawArticle.source_url` containing the extracted original URL.

- [ ] Add a failing parser test using the supplied AI HOT item and assert the CASP URL.
- [ ] Run `.venv/bin/python -m pytest tests/test_crawlers.py -q` and confirm the assertion fails with the AI HOT item URL.
- [ ] Add `_original_url_from_description(description: str) -> str` and apply it only when the source policy is enabled.
- [ ] Add `original_url_from_description: true` to the AI HOT default and checked-in source configuration.
- [ ] Run the focused tests, then the complete Python test suite.
