from __future__ import annotations

import asyncio
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from app.api.public import (
    _merge_daily_items,
    build_daily_payload,
    build_daily_payload_from_repository,
    build_events_payload,
    build_events_payload_from_items,
    build_hotspots_payload,
    build_latest_payload,
    build_latest_selected_payload_from_repository,
    build_period_payload,
)
from app.core.config import load_env_file
from app.storage.json_store import read_json

DATA_DIR = Path("data")


def load_latest_daily_json(data_dir: Path = DATA_DIR) -> dict:
    reports_dir = data_dir / "reports"
    if not reports_dir.exists():
        return {
            "report_date": date.today().isoformat(),
            "title": "Suversal AI Radar 日报",
            "summary": "No report generated yet.",
            "updated_at": None,
            "items": [],
            "sections": {},
            "article_count": 0,
        }
    candidates = sorted(reports_dir.glob("*.json"))
    if not candidates:
        return {
            "report_date": date.today().isoformat(),
            "title": "Suversal AI Radar 日报",
            "summary": "No report generated yet.",
            "updated_at": None,
            "items": [],
            "sections": {},
            "article_count": 0,
        }
    return read_json(candidates[-1])


def load_daily_reports_between(data_dir: Path, start_date: date, end_date: date) -> list[dict]:
    reports_dir = data_dir / "reports"
    if not reports_dir.exists():
        return []
    payloads = []
    for report_path in sorted(reports_dir.glob("*.json")):
        try:
            report_date = date.fromisoformat(report_path.stem)
        except ValueError:
            continue
        if start_date <= report_date <= end_date:
            payloads.append(read_json(report_path))
    return payloads


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _resolve_refresh_int(
    *,
    name: str,
    value: int | None,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    resolved = default if value is None else value
    if resolved < minimum or resolved > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return resolved


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def open_database_report_repository(database_url: str) -> Iterator[Any]:
    from app.db.session import build_session_factory
    from app.repositories.radar_repository import RadarRepository

    session_factory = build_session_factory(database_url)
    session = session_factory()
    try:
        yield RadarRepository(session)
    finally:
        session.close()


def run_scheduler_tick(
    repository: Any,
    *,
    now: datetime,
    is_refresh_running: Callable[[], bool],
    trigger_refresh: Callable[[], None],
) -> bool:
    """One evaluation of the in-process scheduler: checks the persisted
    schedule config, and if a refresh is due and none is already running,
    records the trigger time and kicks off the refresh. Returns whether it
    triggered, for observability/testing."""
    from app.services.refresh_service import should_trigger_refresh

    config = repository.get_schedule_config()
    if not should_trigger_refresh(config, now):
        return False
    if is_refresh_running():
        return False
    repository.record_schedule_triggered(now)
    commit = getattr(getattr(repository, "session", None), "commit", None)
    if callable(commit):
        commit()
    trigger_refresh()
    return True


SCHEDULER_POLL_SECONDS = 60


def create_app(
    *,
    report_repository_factory: Callable[[], Any] | None = None,
    refresh_runner: Callable[[], dict[str, Any]] | None = None,
    data_dir: Path = DATA_DIR,
):
    load_env_file()
    try:
        from fastapi import Cookie, Depends, FastAPI, Header, HTTPException
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI is not installed. Install requirements.txt first.") from exc

    refresh_jobs: dict[str, dict[str, Any]] = {}
    refresh_jobs_lock = threading.Lock()

    def is_refresh_running() -> bool:
        # in-memory jobs catch async triggers from this process; the DB
        # running row is the cross-process truth (sync endpoint, other
        # workers, a refresh surviving a code reload)
        with refresh_jobs_lock:
            if any(job.get("status") == "running" for job in refresh_jobs.values()):
                return True
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return False
        from app.pipeline.persistence import get_active_pipeline_run_in_database

        return get_active_pipeline_run_in_database(database_url) is not None

    def trigger_refresh_job() -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        with refresh_jobs_lock:
            refresh_jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "created_at": _utc_now_iso(),
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "result": None,
                "error": None,
            }

        def worker() -> None:
            from app.services.refresh_service import RefreshAlreadyRunning

            try:
                result = run_refresh()
                with refresh_jobs_lock:
                    refresh_jobs[job_id].update(
                        {
                            "status": "succeeded",
                            "finished_at": _utc_now_iso(),
                            "result": result,
                        }
                    )
            except RefreshAlreadyRunning as exc:
                # another run is in flight - this trigger is redundant, not broken
                with refresh_jobs_lock:
                    refresh_jobs[job_id].update(
                        {
                            "status": "skipped",
                            "finished_at": _utc_now_iso(),
                            "error": str(exc),
                        }
                    )
            except Exception as exc:  # pragma: no cover - exercised through integration
                with refresh_jobs_lock:
                    refresh_jobs[job_id].update(
                        {
                            "status": "failed",
                            "finished_at": _utc_now_iso(),
                            "error": str(exc),
                        }
                    )

        threading.Thread(target=worker, daemon=True).start()
        with refresh_jobs_lock:
            return dict(refresh_jobs[job_id])

    async def scheduler_loop() -> None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return
        while True:
            await asyncio.sleep(SCHEDULER_POLL_SECONDS)
            try:
                with open_database_report_repository(database_url) as repository:
                    run_scheduler_tick(
                        repository,
                        now=datetime.now(timezone.utc),
                        is_refresh_running=is_refresh_running,
                        trigger_refresh=trigger_refresh_job,
                    )
            except Exception:  # pragma: no cover - defensive: scheduler must never die
                continue

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(scheduler_loop())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="Suversal AI Radar API", version="0.1.0", lifespan=lifespan)

    def require_admin(
        authorization: Optional[str] = Header(default=None),
        admin_cookie: Optional[str] = Cookie(default=None, alias="admin_token"),
    ) -> None:
        import secrets

        admin_token = os.getenv("ADMIN_TOKEN")
        if not admin_token:
            raise HTTPException(
                status_code=403,
                detail="Admin console disabled: set the ADMIN_TOKEN environment variable.",
            )
        header_value = authorization or ""
        if header_value.lower().startswith("bearer "):
            provided = header_value[7:].strip()
        else:
            provided = admin_cookie or ""
        if not provided or not secrets.compare_digest(provided, admin_token):
            raise HTTPException(status_code=401, detail="Invalid admin token")

    admin_guard = Depends(require_admin)

    def report_repository_context():
        if report_repository_factory is not None:
            return nullcontext(report_repository_factory())
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            return open_database_report_repository(database_url)
        return None

    def run_refresh() -> dict[str, Any]:
        if refresh_runner is not None:
            return refresh_runner()
        from app.services.refresh_service import refresh_latest_report

        return refresh_latest_report(
            data_dir=data_dir,
            database_url=os.getenv("DATABASE_URL"),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/public/latest")
    def latest(limit: int = 50, offset: int = 0) -> dict:
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                return build_latest_selected_payload_from_repository(
                    repository,
                    end_date=date.today(),
                    limit=limit,
                    offset=offset,
                )
        return build_latest_payload(load_latest_daily_json(data_dir))

    @app.get("/api/public/daily/{report_date}")
    def daily(report_date: str) -> dict:
        try:
            parsed_date = date.fromisoformat(report_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid report date") from exc

        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                return build_daily_payload_from_repository(repository, parsed_date)
        report_path = data_dir / "reports" / f"{report_date}.json"
        if report_path.exists():
            return build_daily_payload(read_json(report_path))
        return build_daily_payload(load_latest_daily_json(data_dir))

    def load_payloads_between(start_date: date, end_date: date) -> list[dict]:
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                return repository.get_daily_report_payloads_between(start_date, end_date)
        return load_daily_reports_between(data_dir, start_date, end_date)

    def load_event_items(days: int) -> list[dict]:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                return repository.get_all_event_items_between(start_date, end_date)
        payloads = load_daily_reports_between(data_dir, start_date, end_date)
        merged: dict[str, dict] = {}
        for payload in sorted(payloads, key=lambda p: p.get("report_date") or ""):
            for item in payload.get("items", []):
                event_id = item.get("event_id") or item.get("original_url") or item.get("title")
                if event_id is not None:
                    merged[str(event_id)] = item
        return list(merged.values())

    @app.get("/api/public/events")
    def events(
        days: int = 30,
        category: Optional[str] = None,
        q: Optional[str] = None,
        topic: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be between 1 and 90")
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                items = repository.get_all_event_items_between(start_date, end_date)
            return build_events_payload_from_items(
                items, category=category, q=q, topic=topic, limit=limit, offset=offset
            )
        payloads = load_daily_reports_between(data_dir, start_date, end_date)
        return build_events_payload(
            payloads, category=category, q=q, topic=topic, limit=limit, offset=offset
        )

    @app.get("/api/public/hotspots")
    def hotspots(
        hours: int = 48,
        limit: int = 5,
        category: Optional[str] = None,
        q: Optional[str] = None,
    ) -> dict:
        if hours < 1 or hours > 168:
            raise HTTPException(status_code=400, detail="hours must be between 1 and 168")
        if limit < 1 or limit > 20:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 20")
        end_date = date.today()
        # query window is day-granular and padded: the precise hour cutoff on
        # last_seen_at/published_at happens inside build_hotspots_payload
        start_date = end_date - timedelta(days=(hours // 24) + 2)
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                items = repository.get_all_event_items_between(
                    start_date, end_date, selected_only=True
                )
            return build_hotspots_payload(
                items, category=category, q=q, hours=hours, limit=limit
            )
        payloads = load_daily_reports_between(data_dir, start_date, end_date)
        merged_items, _report_dates, _updated_at = _merge_daily_items(payloads)
        return build_hotspots_payload(
            merged_items, category=category, q=q, hours=hours, limit=limit
        )

    @app.get("/api/public/topics")
    def topics(days: int = 30) -> dict:
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be between 1 and 90")
        from app.services.topics import build_topics_payload

        return build_topics_payload(load_event_items(days))

    @app.get("/api/public/events/{event_id}")
    def event_detail(event_id: str) -> dict:
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                item = repository.get_event_item(event_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Event not found")
            return item
        end_date = date.today()
        payloads = load_daily_reports_between(data_dir, end_date - timedelta(days=30), end_date)
        for payload in reversed(payloads):
            for item in payload.get("items", []):
                if str(item.get("event_id")) == event_id:
                    return item
        raise HTTPException(status_code=404, detail="Event not found")

    def period_report(mode: str, period_key: str, range_start: date, range_end: date) -> dict:
        # Prefer the persisted masthead (which events, in what order) hydrated
        # to their current live content - same event_id/live-resolve pattern
        # as daily reports. Only fall back to recomputing the period from
        # scratch when no snapshot exists yet (e.g. the period is still in
        # progress and hasn't had a pipeline run persist one, or there is no
        # database repository configured at all).
        repository_context = report_repository_context()
        persisted: Optional[dict[str, Any]] = None
        hydrated_items: Optional[list[dict[str, Any]]] = None
        if repository_context is not None:
            with repository_context as repository:
                persisted = getattr(repository, "get_period_report", lambda *a: None)(
                    mode, period_key
                )
                entries = persisted.get("entries") if persisted else None
                if entries:
                    event_ids = [entry["event_id"] for entry in entries if entry.get("event_id")]
                    hydrated_items = repository.get_event_items_by_ids(event_ids)

        if hydrated_items is not None:
            payload = {
                "mode": mode,
                "range_start": range_start.isoformat(),
                "range_end": range_end.isoformat(),
                "report_dates": persisted.get("report_dates") or [],
                "updated_at": persisted.get("generated_at"),
                "article_count": len(hydrated_items),
                "items": hydrated_items,
            }
        else:
            payloads = load_payloads_between(range_start, range_end)
            payload = build_period_payload(
                payloads, mode=mode, range_start=range_start, range_end=range_end
            )

        payload["period_key"] = period_key
        payload["generated"] = False
        payload["theme_notes"] = []
        if persisted:
            payload.update(
                {
                    "generated": True,
                    "mainline_title": persisted["mainline_title"],
                    "mainline_body": persisted["mainline_body"],
                    "theme_notes": persisted.get("theme_notes") or [],
                    "report_dates": persisted.get("report_dates") or payload["report_dates"],
                    "summary_status": persisted.get("status"),
                    "summary_generated_at": persisted.get("generated_at"),
                    "stats": persisted.get("stats") or {},
                }
            )
        return payload

    def _resolve_period_key(kind: str, raw_key: str) -> str:
        from app.services.period_summary_service import period_key_for, period_range_for_key

        try:
            period_range_for_key(kind, raw_key)
            return raw_key
        except ValueError:
            pass
        try:
            anchor = date.fromisoformat(raw_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid {kind} key") from exc
        return period_key_for(kind, anchor)

    def _serve_period(kind: str, raw_key: Optional[str]) -> dict:
        from app.services.period_summary_service import period_key_for, period_range_for_key

        key = (
            _resolve_period_key(kind, raw_key)
            if raw_key
            else period_key_for(kind, date.today())
        )
        range_start, range_end = period_range_for_key(kind, key)
        return period_report(kind, key, range_start, range_end)

    def _period_archive(kind: str) -> dict:
        repository_context = report_repository_context()
        entries: list[dict] = []
        if repository_context is not None:
            with repository_context as repository:
                entries = getattr(repository, "list_period_reports", lambda *a, **k: [])(kind)
        return {
            "entries": [
                {
                    "period_key": entry["period_key"],
                    "range_start": entry["range_start"],
                    "range_end": entry["range_end"],
                    "mainline_title": entry["mainline_title"],
                    "article_count": entry["article_count"],
                }
                for entry in entries
            ]
        }

    @app.get("/api/public/reports/daily/archive")
    def daily_archive() -> dict:
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                dates = getattr(repository, "list_daily_report_dates", lambda **k: [])()
            return {"dates": dates}
        reports_dir = data_dir / "reports"
        dates = sorted(
            (path.stem for path in reports_dir.glob("*.json")), reverse=True
        ) if reports_dir.exists() else []
        return {"dates": list(dates)}

    @app.get("/api/public/reports/weekly")
    def weekly_latest() -> dict:
        return _serve_period("weekly", None)

    @app.get("/api/public/reports/weekly/archive")
    def weekly_archive() -> dict:
        return _period_archive("weekly")

    @app.get("/api/public/reports/weekly/{report_key}")
    def weekly(report_key: str) -> dict:
        return _serve_period("weekly", report_key)

    @app.get("/api/public/reports/monthly")
    def monthly_latest() -> dict:
        return _serve_period("monthly", None)

    @app.get("/api/public/reports/monthly/archive")
    def monthly_archive() -> dict:
        return _period_archive("monthly")

    @app.get("/api/public/reports/monthly/{report_key}")
    def monthly(report_key: str) -> dict:
        return _serve_period("monthly", report_key)

    @app.get("/api/admin/ping", dependencies=[admin_guard])
    def admin_ping() -> dict:
        return {"status": "ok"}

    @app.get("/api/admin/overview", dependencies=[admin_guard])
    def admin_overview() -> dict:
        repository_context = report_repository_context()
        if repository_context is None:
            raise HTTPException(
                status_code=503,
                detail="Admin overview requires database mode (set DATABASE_URL).",
            )
        with repository_context as repository:
            return {
                "runs": repository.get_recent_pipeline_runs(limit=20),
                "sources": repository.list_sources_with_health(),
                "counts": repository.get_table_counts(),
            }

    def _admin_repository_context():
        repository_context = report_repository_context()
        if repository_context is None:
            raise HTTPException(
                status_code=503,
                detail="This admin feature requires database mode (set DATABASE_URL).",
            )
        return repository_context

    @app.get("/api/admin/sources", dependencies=[admin_guard])
    def admin_sources() -> dict:
        with _admin_repository_context() as repository:
            return {"sources": repository.list_sources_with_health()}

    @app.patch("/api/admin/sources/{source_id}", dependencies=[admin_guard])
    def admin_update_source(source_id: str, payload: dict) -> dict:
        editable = {
            key: value
            for key, value in (payload or {}).items()
            if key in {
                "name", "url", "homepage", "tier", "category", "source_role",
                "type", "language", "fetch_interval_min", "is_active",
                "can_be_main_source", "affects_heat_score", "config",
            }
        }
        if not editable:
            raise HTTPException(status_code=400, detail="No editable fields in payload")
        with _admin_repository_context() as repository:
            found = repository.update_source_fields(source_id, editable)
            if not found:
                raise HTTPException(status_code=404, detail="Source not found")
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "updated": sorted(editable)}

    @app.post("/api/admin/sources", dependencies=[admin_guard])
    def admin_create_source(payload: dict) -> dict:
        from app.models.domain import Source as DomainSource

        required = ["id", "name", "type", "url", "homepage", "tier", "category"]
        missing = [key for key in required if not str((payload or {}).get(key) or "").strip()]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")
        source = DomainSource(
            id=str(payload["id"]).strip(),
            name=str(payload["name"]).strip(),
            source_role=str(payload.get("source_role") or "context"),
            tier=str(payload["tier"]),
            type=str(payload["type"]),
            category=str(payload["category"]),
            url=str(payload["url"]).strip(),
            homepage=str(payload["homepage"]).strip(),
            allowed_domains=list(payload.get("allowed_domains") or []),
            fetch_interval_min=int(payload.get("fetch_interval_min") or 240),
            language=str(payload.get("language") or "en"),
            can_be_main_source=bool(payload.get("can_be_main_source", True)),
            config=dict(payload.get("config") or {}),
        )
        with _admin_repository_context() as repository:
            repository.upsert_sources([source])
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "id": source.id}

    @app.post("/api/admin/sources/{source_id}/test", dependencies=[admin_guard])
    def admin_test_source(source_id: str) -> dict:
        """Manual per-source fetch: crawl this source right now and run each
        article through the exact same content-check/prefilter/score/persist
        steps a real pipeline round would, so the admin can see which
        articles were fetched and which actually passed and got saved -
        not just a connectivity check."""
        from datetime import date as _date, datetime as _datetime, timezone as _timezone

        from app.crawlers import registry as crawler_registry
        from app.crawlers.base import stable_hash
        from app.pipeline.runner import _process_candidate_article, filter_articles_published_on
        from app.services.ai_service import embedding_input, provider_from_env

        with _admin_repository_context() as repository:
            sources = {source.id: source for source in repository.get_all_sources()}
            source = sources.get(source_id)
            if source is None:
                raise HTTPException(status_code=404, detail="Source not found")
            try:
                # 与自动同步同一口径:feed 全量拉元数据,只保留当天发布的
                fetched = crawler_registry.crawler_for_source(source).fetch(limit=None)
                fetched = filter_articles_published_on(fetched, _date.today())
            except Exception as exc:
                result = {
                    "origin": "manual",
                    "at": _datetime.now(_timezone.utc).isoformat(),
                    "status": "failed",
                    "error": str(exc)[:300],
                    "fetched_count": 0,
                    "accepted_count": 0,
                    "articles": [],
                }
                repository.set_last_crawl_result(source_id, result)
                repository.session.commit()
                return result

            ai_provider = provider_from_env()
            now = _datetime.now(_timezone.utc)
            article_results: list[dict[str, Any]] = []
            for article in fetched:
                existing = repository.get_existing_outcome_by_url_hash(article.url_hash)
                if existing is not None:
                    article_results.append(
                        {
                            "title": existing["title"],
                            "url": existing["url"],
                            "outcome": "duplicate",
                            "selected": existing["selected"],
                            "final_score": existing["final_score"],
                            "category": existing["category"],
                            "reason": existing["reason"] or "此前已抓取，本次未重新评分",
                        }
                    )
                    continue
                try:
                    processed, embedding, skipped_reason = _process_candidate_article(
                        article=article,
                        source_by_id=sources,
                        ai_provider=ai_provider,
                        now=now,
                    )
                except Exception as exc:
                    article_results.append(
                        {
                            "title": article.title,
                            "url": article.source_url,
                            "outcome": "rejected",
                            "selected": False,
                            "final_score": None,
                            "category": None,
                            "reason": f"处理出错：{str(exc)[:200]}",
                        }
                    )
                    continue
                repository.upsert_raw_articles([article])
                if processed is None:
                    article_results.append(
                        {
                            "title": article.title,
                            "url": article.source_url,
                            "outcome": "rejected",
                            "selected": False,
                            "final_score": None,
                            "category": None,
                            "reason": skipped_reason,
                        }
                    )
                    continue
                repository.upsert_processed_articles([processed])
                if embedding is not None:
                    repository.upsert_article_embedding(
                        article.id,
                        embedding_model=getattr(ai_provider, "embedding_model", "unknown"),
                        vector=embedding,
                        source_hash=stable_hash(embedding_input(article.title, article.content)),
                    )
                article_results.append(
                    {
                        "title": processed.title_zh or article.title,
                        "url": article.source_url,
                        "outcome": "saved" if processed.selected else "rejected",
                        "selected": processed.selected,
                        "final_score": processed.final_score,
                        "category": processed.category,
                        "reason": processed.selection_reason
                        if processed.selected
                        else processed.rejection_reason,
                    }
                )

            result = {
                "origin": "manual",
                "at": now.isoformat(),
                "status": "ok",
                "error": None,
                "fetched_count": len(fetched),
                "accepted_count": len(article_results),
                "articles": article_results,
            }
            repository.set_last_crawl_result(source_id, result)
            repository.session.commit()
        return result

    @app.get("/api/admin/events", dependencies=[admin_guard])
    def admin_events(
        days: int = 30,
        q: Optional[str] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be between 1 and 90")
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")
        from app.api.public import _item_matches

        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        with _admin_repository_context() as repository:
            items = repository.get_all_event_items_between(
                start_date, end_date, include_hidden=True
            )
        title_query = (title or q or "").strip()
        selected_category = (category or "").strip()
        selected_source_id = (source_id or "").strip()
        if selected_category:
            items = [
                item
                for item in items
                if _item_matches(item, category=selected_category, q=None)
            ]
        if title_query:
            title_needles = [part for part in title_query.lower().split() if part]
            items = [
                item
                for item in items
                if all(
                    needle in str(item.get("title") or "").lower()
                    for needle in title_needles
                )
            ]
        if selected_source_id:
            items = [
                item
                for item in items
                if str((item.get("main_source") or {}).get("id") or "")
                == selected_source_id
            ]
        items.sort(
            key=lambda item: (
                str(item.get("crawled_at") or ""),
                str(item.get("published_at") or ""),
            ),
            reverse=True,
        )
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    @app.patch("/api/admin/events/{event_id}", dependencies=[admin_guard])
    def admin_moderate_event(event_id: str, payload: dict) -> dict:
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import SCORING_CATEGORIES
        from app.services.taxonomy import DISPLAY_CATEGORIES

        allowed_categories = set(SCORING_CATEGORIES) | {key for key, _ in DISPLAY_CATEGORIES}
        fields = {
            key: value
            for key, value in (payload or {}).items()
            if key in RadarRepository.EVENT_MODERATION_FIELDS
        }
        if not fields:
            raise HTTPException(status_code=400, detail="No editable fields in payload")
        if "category" in fields and str(fields["category"]) not in allowed_categories:
            raise HTTPException(
                status_code=400,
                detail=f"category must be one of: {', '.join(sorted(allowed_categories))}",
            )
        with _admin_repository_context() as repository:
            found = repository.update_event_moderation(event_id, fields)
            if not found:
                raise HTTPException(status_code=404, detail="Event not found")
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "updated": sorted(fields)}

    @app.post("/api/admin/refresh-latest", dependencies=[admin_guard])
    def refresh_latest() -> dict:
        from app.services.refresh_service import RefreshAlreadyRunning

        try:
            return run_refresh()
        except RefreshAlreadyRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/admin/refresh-latest-async", dependencies=[admin_guard])
    def refresh_latest_async() -> dict:
        return trigger_refresh_job()

    @app.get("/api/admin/refresh-jobs/{job_id}", dependencies=[admin_guard])
    def refresh_job(job_id: str) -> dict:
        with refresh_jobs_lock:
            job = refresh_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Refresh job not found")
            return dict(job)

    @app.get("/api/admin/schedule", dependencies=[admin_guard])
    def get_schedule() -> dict:
        with _admin_repository_context() as repository:
            return repository.get_schedule_config()

    @app.put("/api/admin/schedule", dependencies=[admin_guard])
    def update_schedule(payload: dict) -> dict:
        enabled = bool((payload or {}).get("enabled", False))
        interval_minutes = (payload or {}).get("interval_minutes")
        try:
            interval_minutes = _resolve_refresh_int(
                name="interval_minutes",
                value=interval_minutes,
                default=120,
                minimum=5,
                maximum=1440,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with _admin_repository_context() as repository:
            result = repository.update_schedule_config(
                enabled=enabled, interval_minutes=interval_minutes
            )
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
            return result

    return app


try:
    app = create_app()
except RuntimeError:
    app = None
