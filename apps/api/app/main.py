from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from app.api.public import (
    build_daily_payload,
    build_daily_payload_from_repository,
    build_events_payload,
    build_events_payload_from_items,
    build_latest_payload,
    build_latest_payload_from_repository,
    build_period_payload,
    month_range,
    week_range,
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

    app = FastAPI(title="Suversal AI Radar API", version="0.1.0")

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
    refresh_jobs: dict[str, dict[str, Any]] = {}
    refresh_jobs_lock = threading.Lock()

    def report_repository_context():
        if report_repository_factory is not None:
            return nullcontext(report_repository_factory())
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            return open_database_report_repository(database_url)
        return None

    def resolve_refresh_params(limit: Optional[int], top_n: Optional[int]) -> tuple[int, int]:
        return (
            _resolve_refresh_int(
                name="limit",
                value=limit,
                default=_env_int("DAILY_CANDIDATE_LIMIT", 100),
                minimum=1,
                maximum=200,
            ),
            _resolve_refresh_int(
                name="top_n",
                value=top_n,
                default=_env_int("DAILY_SELECTED_LIMIT", 12),
                minimum=1,
                maximum=50,
            ),
        )

    def run_refresh(resolved_limit: int, resolved_top_n: int) -> dict[str, Any]:
        if refresh_runner is not None:
            return refresh_runner(limit=resolved_limit, top_n=resolved_top_n)
        from app.services.refresh_service import refresh_latest_report

        return refresh_latest_report(
            data_dir=data_dir,
            database_url=os.getenv("DATABASE_URL"),
            limit=resolved_limit,
            top_n=resolved_top_n,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/public/latest")
    def latest() -> dict:
        repository_context = report_repository_context()
        if repository_context is not None:
            with repository_context as repository:
                return build_latest_payload_from_repository(repository)
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

    def period_report(mode: str, range_start: date, range_end: date) -> dict:
        payloads = load_payloads_between(range_start, range_end)
        return build_period_payload(
            payloads, mode=mode, range_start=range_start, range_end=range_end
        )

    @app.get("/api/public/reports/weekly")
    def weekly_latest() -> dict:
        range_start, range_end = week_range(date.today())
        return period_report("weekly", range_start, range_end)

    @app.get("/api/public/reports/weekly/{report_date}")
    def weekly(report_date: str) -> dict:
        try:
            anchor = date.fromisoformat(report_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid report date") from exc
        range_start, range_end = week_range(anchor)
        return period_report("weekly", range_start, range_end)

    @app.get("/api/public/reports/monthly")
    def monthly_latest() -> dict:
        range_start, range_end = month_range(date.today())
        return period_report("monthly", range_start, range_end)

    @app.get("/api/public/reports/monthly/{month}")
    def monthly(month: str) -> dict:
        try:
            anchor = datetime.strptime(month, "%Y-%m").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid month, expected YYYY-MM") from exc
        range_start, range_end = month_range(anchor)
        return period_report("monthly", range_start, range_end)

    @app.get("/api/admin/ping", dependencies=[admin_guard])
    def admin_ping() -> dict:
        return {"status": "ok"}

    @app.post("/api/admin/refresh-latest", dependencies=[admin_guard])
    def refresh_latest(limit: Optional[int] = None, top_n: Optional[int] = None) -> dict:
        try:
            resolved_limit, resolved_top_n = resolve_refresh_params(limit, top_n)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            return run_refresh(resolved_limit, resolved_top_n)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/admin/refresh-latest-async", dependencies=[admin_guard])
    def refresh_latest_async(limit: Optional[int] = None, top_n: Optional[int] = None) -> dict:
        try:
            resolved_limit, resolved_top_n = resolve_refresh_params(limit, top_n)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        job_id = uuid.uuid4().hex
        with refresh_jobs_lock:
            refresh_jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "created_at": _utc_now_iso(),
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "limit": resolved_limit,
                "top_n": resolved_top_n,
                "result": None,
                "error": None,
            }

        def worker() -> None:
            try:
                result = run_refresh(resolved_limit, resolved_top_n)
                with refresh_jobs_lock:
                    refresh_jobs[job_id].update(
                        {
                            "status": "succeeded",
                            "finished_at": _utc_now_iso(),
                            "result": result,
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

    @app.get("/api/admin/refresh-jobs/{job_id}", dependencies=[admin_guard])
    def refresh_job(job_id: str) -> dict:
        with refresh_jobs_lock:
            job = refresh_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Refresh job not found")
            return dict(job)

    return app


try:
    app = create_app()
except RuntimeError:
    app = None
