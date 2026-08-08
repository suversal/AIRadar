from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger(__name__)

try:
    from starlette.requests import Request as StarletteRequest
except ModuleNotFoundError:  # pragma: no cover - lightweight dependency guard
    StarletteRequest = Any

from app.api.public import (
    build_daily_payload_from_repository,
    build_events_payload_from_items,
    build_hotspots_payload,
    build_latest_selected_payload_from_repository,
    build_period_payload,
)
from app.core.config import load_env_file
from app.services.taxonomy import SOURCE_FILTER_KEYS

DATA_DIR = Path("data")


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
    manual_jobs: set[str] = set()
    manual_jobs_lock = threading.Lock()

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
        if not database_url:
            raise HTTPException(
                status_code=503,
                detail="This endpoint requires database mode (set DATABASE_URL).",
            )
        return open_database_report_repository(database_url)

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
    def latest(
        limit: int = 50,
        offset: int = 0,
        category: Optional[str] = None,
        focus: Optional[str] = None,
        tag: Optional[str] = None,
        q: Optional[str] = None,
    ) -> dict:
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")
        with report_repository_context() as repository:
            return build_latest_selected_payload_from_repository(
                repository,
                end_date=date.today(),
                limit=limit,
                offset=offset,
                category=category,
                focus=focus,
                tag=tag,
                q=q,
            )

    @app.get("/api/public/daily/{report_date}")
    def daily(report_date: str) -> dict:
        try:
            parsed_date = date.fromisoformat(report_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid report date") from exc

        with report_repository_context() as repository:
            return build_daily_payload_from_repository(repository, parsed_date)

    def load_payloads_between(start_date: date, end_date: date) -> list[dict]:
        with report_repository_context() as repository:
            return repository.get_daily_report_payloads_between(start_date, end_date)

    def load_event_items(days: int) -> list[dict]:
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        with report_repository_context() as repository:
            return repository.get_all_event_items_between(start_date, end_date)

    @app.get("/api/public/events")
    def events(
        days: int = 30,
        category: Optional[str] = None,
        focus: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
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
        if source and source not in SOURCE_FILTER_KEYS:
            raise HTTPException(
                status_code=400,
                detail="source must be first_party, news, or community",
            )
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        with report_repository_context() as repository:
            # q/topic/tag matching only exists in Python today (title
            # override precedence, topic keyword and exact-tag rules), so only the
            # filter-free/category-only case - by far the most common
            # /all load - gets the SQL-pushdown fast path; q, topic, or tag
            # falls back to the full materialize-then-filter path.
            if not q and not topic and not category and not tag:
                items, total, updated_at = repository.count_and_get_all_event_items_between(
                    start_date,
                    end_date,
                    category=focus,
                    source=source,
                    limit=limit,
                    offset=offset,
                )
                return {
                    "report_dates": [],
                    "updated_at": updated_at,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "article_count": len(items),
                    "items": items,
                }
            items = repository.get_all_event_items_between(start_date, end_date)
        return build_events_payload_from_items(
            items,
            category=category,
            focus=focus,
            source=source,
            tag=tag,
            q=q,
            topic=topic,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/public/hotspots")
    def hotspots(
        hours: int = 48,
        limit: int = 5,
        category: Optional[str] = None,
        focus: Optional[str] = None,
        tag: Optional[str] = None,
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
        with report_repository_context() as repository:
            items = repository.get_all_event_items_between(
                start_date, end_date, selected_only=True
            )
        return build_hotspots_payload(
            items,
            category=category,
            focus=focus,
            tag=tag,
            q=q,
            hours=hours,
            limit=limit,
        )

    @app.get("/api/public/topics")
    def topics(days: int = 30) -> dict:
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be between 1 and 90")
        from app.services.topics import build_topics_payload

        return build_topics_payload(load_event_items(days))

    _TWEET_KINDS = {"repost", "article", "longform", "link", "quote", "brief"}

    @app.get("/api/public/tweets")
    def public_tweets(
        kind: Optional[str] = None,
        handle: Optional[str] = None,
        topic: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """X 推文流（SourcePilot Phase 4）。数据来自本地 x_tweets 镜像表，
        云端照常只读——同步在本地 refresh 时完成，这里不出网。"""
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")
        if kind and kind not in _TWEET_KINDS:
            raise HTTPException(
                status_code=400,
                detail="kind must be one of " + ", ".join(sorted(_TWEET_KINDS)),
            )
        with report_repository_context() as repository:
            items, total, updated_at = repository.query_x_tweets(
                kind=kind, handle=handle, topic=topic, limit=limit, offset=offset
            )
            available_topics = repository.list_x_tweet_topics()
        return {
            "updated_at": updated_at,
            "total": total,
            "limit": limit,
            "offset": offset,
            "item_count": len(items),
            "topics": available_topics,
            "items": items,
        }

    @app.get("/api/public/tweets/{tweet_id}")
    def public_tweet_detail(tweet_id: str) -> dict:
        with report_repository_context() as repository:
            tweet = repository.get_x_tweet(tweet_id)
        if tweet is None:
            raise HTTPException(status_code=404, detail="tweet not found")
        return {"item": tweet}

    @app.get("/api/public/events/{event_id}")
    def event_detail(event_id: str) -> dict:
        with report_repository_context() as repository:
            item = repository.get_event_item(event_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return item

    def period_report(mode: str, period_key: str, range_start: date, range_end: date) -> dict:
        # Prefer the persisted masthead (which events, in what order) hydrated
        # to their current live content - same event_id/live-resolve pattern
        # as daily reports. Only fall back to recomputing the period from
        # scratch when no snapshot exists yet (the period is still in
        # progress and hasn't had a pipeline run persist one).
        persisted: Optional[dict[str, Any]] = None
        hydrated_items: Optional[list[dict[str, Any]]] = None
        with report_repository_context() as repository:
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

        if raw_key:
            key = _resolve_period_key(kind, raw_key)
        else:
            key = period_key_for(kind, date.today())
            # 2026-07-13 修复:当前自然周期(本周/本月)在第一次同步生成
            # 快照之前没有真实内容——周期刚翻页时不能硬套一个空壳当前
            # 周期，落到最近一个真正生成过快照的期次
            with report_repository_context() as repository:
                has_snapshot = repository.get_period_report(kind, key) is not None
                if not has_snapshot:
                    entries = getattr(
                        repository, "list_period_reports", lambda *a, **k: []
                    )(kind, limit=1)
                    if entries:
                        key = entries[0]["period_key"]
        range_start, range_end = period_range_for_key(kind, key)
        return period_report(kind, key, range_start, range_end)

    def _period_archive(kind: str) -> dict:
        with report_repository_context() as repository:
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
        with report_repository_context() as repository:
            dates = getattr(repository, "list_daily_report_dates", lambda **k: [])()
        return {"dates": dates}

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

    @app.post("/api/public/feedback")
    def submit_feedback(payload: dict) -> dict:
        message = str((payload or {}).get("message") or "").strip()
        email = (payload or {}).get("email")
        email = str(email).strip() if email else None
        if not message:
            raise HTTPException(status_code=422, detail="message is required")
        if len(message) > 2000:
            raise HTTPException(status_code=422, detail="message must be 2000 characters or fewer")
        if email and len(email) > 320:
            raise HTTPException(status_code=422, detail="email is too long")

        with report_repository_context() as repository:
            repository.create_feedback_submission(message=message, email=email)
            repository.session.commit()

        from app.services.telegram_notifier import send_telegram_message

        lines = ["📮 收到新反馈", "", message]
        if email:
            lines.extend(["", f"联系邮箱：{email}"])
        send_telegram_message("\n".join(lines))

        return {"ok": True}

    @app.get("/api/admin/ping", dependencies=[admin_guard])
    def admin_ping() -> dict:
        return {"status": "ok"}

    @app.get("/api/admin/overview", dependencies=[admin_guard])
    def admin_overview() -> dict:
        with report_repository_context() as repository:
            return {
                "runs": repository.get_recent_pipeline_runs(limit=20),
                "sources": repository.list_sources_with_health(),
                "counts": repository.get_table_counts(),
            }

    def _admin_repository_context():
        return report_repository_context()

    def _require_manual_feature(name: str = "ADMIN_MANUAL_ARTICLE_ENABLED") -> None:
        from app.services.manual_articles import env_enabled

        if not env_enabled("ADMIN_MANUAL_ARTICLE_ENABLED") or not env_enabled(name):
            raise HTTPException(status_code=404, detail="Not found")

    def _submission_error(exc: Exception) -> HTTPException:
        from app.services.manual_articles import SubmissionError

        if isinstance(exc, SubmissionError):
            return HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            )
        return HTTPException(status_code=500, detail="manual_article_failed")

    def _process_manual_submission_job(submission_id: str) -> None:
        from app.services.manual_articles import (
            SubmissionError,
            process_and_materialize_submission,
        )

        try:
            with report_repository_context() as repository:
                try:
                    process_and_materialize_submission(repository, submission_id)
                    repository.session.commit()
                except Exception as exc:
                    repository.session.rollback()
                    model = repository.get_submission_model(submission_id)
                    if model is not None:
                        model.processing_status = "failed"
                        model.processing_stage = None
                        model.last_error_code = (
                            exc.code if isinstance(exc, SubmissionError) else "manual_article_failed"
                        )
                        model.last_error_detail = str(exc)[:500]
                        repository.session.commit()
                    logger.exception("manual article processing failed for %s", submission_id)
        finally:
            with manual_jobs_lock:
                manual_jobs.discard(submission_id)

    @app.get("/api/admin/sources", dependencies=[admin_guard])
    def admin_sources() -> dict:
        with _admin_repository_context() as repository:
            from app.services.refresh_service import ensure_auto_seeded_sources

            ensure_auto_seeded_sources(repository)
            return {"sources": repository.list_sources_with_health()}

    @app.post("/api/admin/article-submissions", dependencies=[admin_guard])
    def admin_create_article_submission(payload: dict) -> dict:
        _require_manual_feature()
        from app.services.manual_articles import create_submission, submission_to_dict

        try:
            with _admin_repository_context() as repository:
                model = create_submission(repository, payload or {})
                repository.session.commit()
                return submission_to_dict(model)
        except Exception as exc:
            raise _submission_error(exc) from exc

    @app.get("/api/admin/article-submissions", dependencies=[admin_guard])
    def admin_list_article_submissions(
        limit: int = 100, publication_status: Optional[str] = None
    ) -> dict:
        _require_manual_feature()
        from app.services.manual_articles import submission_to_dict

        resolved_limit = max(1, min(limit, 200))
        if publication_status not in {None, "draft", "published"}:
            raise HTTPException(status_code=422, detail="invalid publication_status")
        with _admin_repository_context() as repository:
            models = repository.list_submission_models(
                resolved_limit, publication_status=publication_status
            )
            return {
                "items": [
                    submission_to_dict(model)
                    for model in models
                ]
            }

    @app.get("/api/admin/article-submissions/{submission_id}", dependencies=[admin_guard])
    def admin_get_article_submission(submission_id: str) -> dict:
        _require_manual_feature()
        from app.services.manual_articles import submission_to_dict

        with _admin_repository_context() as repository:
            model = repository.get_submission_model(submission_id)
            if model is None:
                raise HTTPException(status_code=404, detail="Submission not found")
            return submission_to_dict(model)

    @app.patch("/api/admin/article-submissions/{submission_id}", dependencies=[admin_guard])
    def admin_update_article_submission(submission_id: str, payload: dict) -> dict:
        _require_manual_feature()
        from app.services.manual_articles import submission_to_dict, update_submission

        try:
            with _admin_repository_context() as repository:
                model = repository.get_submission_model(submission_id)
                if model is None:
                    raise HTTPException(status_code=404, detail="Submission not found")
                update_submission(model, payload or {})
                repository.session.commit()
                return submission_to_dict(model)
        except HTTPException:
            raise
        except Exception as exc:
            raise _submission_error(exc) from exc

    @app.delete("/api/admin/article-submissions/{submission_id}", dependencies=[admin_guard])
    def admin_delete_article_submission(submission_id: str) -> dict:
        _require_manual_feature()
        try:
            with _admin_repository_context() as repository:
                if not repository.delete_submission(submission_id):
                    raise HTTPException(status_code=404, detail="Submission not found")
                repository.session.commit()
                return {"deleted": True, "id": submission_id}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "already_published", "message": str(exc)},
            ) from exc

    @app.post(
        "/api/admin/article-submissions/{submission_id}/process",
        dependencies=[admin_guard],
        status_code=202,
    )
    def admin_process_article_submission(submission_id: str) -> dict:
        _require_manual_feature()
        with _admin_repository_context() as repository:
            model = repository.get_submission_model(submission_id)
            if model is None:
                raise HTTPException(status_code=404, detail="Submission not found")
            if model.processing_status in {"fetching", "scoring"}:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "processing", "message": "Submission is processing"},
                )
        with manual_jobs_lock:
            if submission_id in manual_jobs:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "processing", "message": "Submission is processing"},
                )
            manual_jobs.add(submission_id)
        threading.Thread(
            target=_process_manual_submission_job,
            args=(submission_id,),
            daemon=True,
        ).start()
        return {"id": submission_id, "processing_status": "queued"}

    @app.get(
        "/api/admin/article-submissions/{submission_id}/status",
        dependencies=[admin_guard],
    )
    def admin_article_submission_status(submission_id: str) -> dict:
        _require_manual_feature()
        from app.services.manual_articles import submission_to_dict

        with _admin_repository_context() as repository:
            model = repository.get_submission_model(submission_id)
            if model is None:
                raise HTTPException(status_code=404, detail="Submission not found")
            payload = submission_to_dict(model)
            return {
                key: payload[key]
                for key in (
                    "id", "publication_status", "processing_status", "processing_stage",
                    "last_error_code", "last_error_detail", "raw_article_id",
                )
            }

    @app.post(
        "/api/admin/article-submissions/{submission_id}/publish",
        dependencies=[admin_guard],
    )
    def admin_publish_article_submission(submission_id: str) -> dict:
        _require_manual_feature("ADMIN_MANUAL_ARTICLE_PUBLISH_ENABLED")
        from app.services.manual_articles import publish_submission, submission_to_dict

        try:
            with _admin_repository_context() as repository:
                model = publish_submission(repository, submission_id)
                repository.session.commit()
                return submission_to_dict(model)
        except Exception as exc:
            raise _submission_error(exc) from exc

    @app.post("/api/admin/uploads/images", dependencies=[admin_guard])
    async def admin_upload_manual_image(request: StarletteRequest) -> dict:
        _require_manual_feature("ADMIN_MANUAL_IMAGE_UPLOAD_ENABLED")
        from app.services.manual_image_upload import ImageUploadError, upload_image_to_host
        from starlette.concurrency import run_in_threadpool

        try:
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise ImageUploadError("unsupported_image_type", "file is required", 415)
            max_bytes = int(os.getenv("IMAGE_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))
            data = await upload.read(max_bytes + 1)
            src = await run_in_threadpool(
                upload_image_to_host,
                filename=str(getattr(upload, "filename", None) or "image"),
                content_type=str(getattr(upload, "content_type", None) or "application/octet-stream"),
                data=data,
            )
            return {"src": src}
        except ImageUploadError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc

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

    @app.delete("/api/admin/sources/{source_id}", dependencies=[admin_guard])
    def admin_delete_source(source_id: str) -> dict:
        from app.repositories.radar_repository import SourceHasArticlesError

        with _admin_repository_context() as repository:
            try:
                deleted = repository.delete_source(source_id)
            except SourceHasArticlesError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=f"该信源下还有 {exc.count} 篇文章，请先清空文章后再删除",
                ) from exc
            if not deleted:
                raise HTTPException(status_code=404, detail="Source not found")
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "deleted_source_id": source_id}

    @app.post("/api/admin/sources/{source_id}/test", dependencies=[admin_guard])
    def admin_test_source(source_id: str) -> dict:
        """Manual per-source fetch: crawl this source right now and run each
        article through the exact same content-check/prefilter/score/persist
        steps a real pipeline round would, so the admin can see which
        articles were fetched and which actually passed and got saved -
        not just a connectivity check."""
        from datetime import date as _date, datetime as _datetime, timezone as _timezone

        from app.crawlers import registry as crawler_registry
        from app.crawlers.article_content import content_extraction_version_for_url
        from app.crawlers.base import stable_hash
        from app.pipeline.runner import (
            _hydrate_article_from_cache,
            _process_candidate_article,
            _translate_processed_english_articles,
            filter_articles_published_on,
            source_recent_days,
        )
        from app.services.ai_service import embedding_input, provider_from_env
        from app.services.refresh_service import crawl_result_url

        with _admin_repository_context() as repository:
            sources = {source.id: source for source in repository.get_all_sources()}
            source = sources.get(source_id)
            if source is None:
                raise HTTPException(status_code=404, detail="Source not found")
            try:
                # 与自动同步同一口径:feed 全量拉元数据,只保留最近 N 天发布的
                # (N 由信源 config.recent_days 配置,默认 1;ingest_all_dates
                # 源豁免)
                fetched = crawler_registry.crawler_for_source(source).fetch(limit=None)
                fetched = filter_articles_published_on(
                    fetched,
                    _date.today(),
                    exempt_source_ids=(
                        {source.id}
                        if (source.config or {}).get("ingest_all_dates")
                        else frozenset()
                    ),
                    recent_days_by_source={source.id: source_recent_days(source)},
                )
            except Exception as exc:
                result = {
                    "origin": "manual",
                    "at": _datetime.now(_timezone.utc).isoformat(),
                    "status": "failed",
                    "error": str(exc)[:300],
                    "fetched_count": 0,
                    "accepted_count": 0,
                    "ingested_count": 0,
                    "articles": [],
                }
                repository.update_source_health(
                    {
                        source_id: {
                            "status": "skipped",
                            "article_count": 0,
                            "fetched_count": 0,
                            "error": result["error"],
                        }
                    }
                )
                repository.set_last_crawl_result(source_id, result)
                repository.session.commit()
                return result

            ai_provider = provider_from_env()
            now = _datetime.now(_timezone.utc)
            article_results: list[dict[str, Any] | None] = [None] * len(fetched)
            pending: list[tuple[int, Any, Any, Any, Any, Any]] = []
            saved_count = 0
            ingested_count = 0
            cached_results = repository.get_cached_results_by_url_hash(
                [article.url_hash for article in fetched]
            )
            for index, article in enumerate(fetched):
                cached = cached_results.get(article.url_hash)
                if cached:
                    _hydrate_article_from_cache(article, cached)
                existing = repository.get_existing_outcome_by_url_hash(article.url_hash)
                cached_metadata = (cached or {}).get("metadata") or {}
                cached_version = int(cached_metadata.get("content_extraction_version") or 0)
                cached_content_stale = (
                    article.metadata.get("body_fetch") == "deferred"
                    and cached_version < content_extraction_version_for_url(article.source_url)
                )
                if existing is not None and not cached_content_stale:
                    article_results[index] = {
                        "title": existing["title"],
                        "url": existing["url"],
                        "outcome": "duplicate",
                        "selected": existing["selected"],
                        "final_score": existing["final_score"],
                        "category": existing["category"],
                        "reason": existing["reason"] or "此前已抓取，本次未重新评分",
                    }
                    continue
                try:
                    processed, embedding, skipped_reason = _process_candidate_article(
                        article=article,
                        source_by_id=sources,
                        ai_provider=ai_provider,
                        now=now,
                        cached=cached,
                    )
                except Exception as exc:
                    article_results[index] = {
                        "title": article.title,
                        "url": crawl_result_url(article),
                        "outcome": "rejected",
                        "selected": False,
                        "final_score": None,
                        "category": None,
                        "reason": f"处理出错：{str(exc)[:200]}",
                    }
                    continue
                pending.append(
                    (index, article, processed, embedding, skipped_reason, existing)
                )

            _translate_processed_english_articles(
                articles=[article for _, article, processed, _, _, _ in pending if processed],
                ai_provider=ai_provider,
                ai_concurrency=_env_int("AI_PIPELINE_CONCURRENCY", 1),
            )

            for index, article, processed, embedding, skipped_reason, existing in pending:
                repository.upsert_raw_articles([article])
                # 口径对齐自动同步(refresh_service._build_auto_crawl_results):
                # 入库只排除 not_ai_related,未达精选的 raw_articles 行同样保留
                if existing is None and skipped_reason != "not_ai_related":
                    ingested_count += 1
                if processed is None:
                    article_results[index] = {
                        "title": existing["title"] if existing else article.title,
                        "url": existing["url"] if existing else crawl_result_url(article),
                        "outcome": "duplicate" if existing else "rejected",
                        "selected": existing["selected"] if existing else False,
                        "final_score": existing["final_score"] if existing else None,
                        "category": existing["category"] if existing else None,
                        "reason": existing["reason"] if existing else skipped_reason,
                    }
                    continue
                repository.upsert_processed_articles([processed])
                if embedding is not None:
                    repository.upsert_article_embedding(
                        article.id,
                        embedding_model=getattr(ai_provider, "embedding_model", "unknown"),
                        vector=embedding,
                        source_hash=stable_hash(embedding_input(article.title, article.content)),
                    )
                if existing is None and processed.selected:
                    saved_count += 1
                article_results[index] = {
                    "title": existing["title"]
                    if existing
                    else (processed.title_zh or article.title),
                    "url": existing["url"] if existing else crawl_result_url(article),
                    "outcome": "duplicate"
                    if existing
                    else ("saved" if processed.selected else "rejected"),
                    "selected": existing["selected"] if existing else processed.selected,
                    "final_score": existing["final_score"]
                    if existing
                    else processed.final_score,
                    "category": existing["category"] if existing else processed.category,
                    "reason": existing["reason"]
                    if existing
                    else (
                        processed.selection_reason
                        if processed.selected
                        else processed.rejection_reason
                    ),
                }

            result = {
                "origin": "manual",
                "at": now.isoformat(),
                "status": "ok",
                "error": None,
                "fetched_count": len(fetched),
                "accepted_count": saved_count,
                "ingested_count": ingested_count,
                "articles": [article for article in article_results if article is not None],
            }
            # Manual crawling is a real source-health observation just like
            # an automatic round. Keep the health columns and the detailed
            # manual result in sync so a successful fetch never remains at
            # the default 0% and gets mislabeled as a fault in the admin UI.
            repository.update_source_health(
                {
                    source_id: {
                        "status": "ok",
                        "article_count": len(fetched),
                        "fetched_count": len(fetched),
                        "error": None,
                    }
                }
            )
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
        status: str = "all",
        sort_by: str = "published_at",
        sort_dir: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be between 1 and 90")
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset must be non-negative")
        if sort_by not in {"published_at", "crawled_at"}:
            raise HTTPException(
                status_code=400,
                detail="sort_by must be published_at or crawled_at",
            )
        if sort_dir not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="sort_dir must be asc or desc")
        if status not in {"all", "visible", "hidden", "selected", "unselected"}:
            raise HTTPException(status_code=400, detail="invalid status")
        from app.api.public import _item_matches
        from app.services.ai_service import SCORING_CATEGORIES

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
            if selected_category in SCORING_CATEGORIES:
                items = [
                    item
                    for item in items
                    if str(
                        item.get("scoring_category")
                        or item.get("category")
                        or ""
                    )
                    == selected_category
                ]
            else:
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
        if status == "visible":
            items = [item for item in items if not bool(item.get("hidden"))]
        elif status == "hidden":
            items = [item for item in items if bool(item.get("hidden"))]
        elif status == "selected":
            items = [item for item in items if bool(item.get("selected"))]
        elif status == "unselected":
            items = [item for item in items if not bool(item.get("selected"))]
        secondary_sort = "crawled_at" if sort_by == "published_at" else "published_at"

        def sort_key(item: dict) -> tuple:
            primary = str(item.get(sort_by) or "")
            secondary = str(item.get(secondary_sort) or "")
            event_id = str(item.get("event_id") or "")
            # Missing timestamps always stay at the end in either direction.
            if sort_dir == "asc":
                return (not primary, primary, secondary, event_id)
            return (bool(primary), primary, secondary, event_id)

        items.sort(key=sort_key, reverse=sort_dir == "desc")
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        }

    @app.get("/api/admin/events/{event_id}", dependencies=[admin_guard])
    def admin_event_detail(event_id: str) -> dict:
        with _admin_repository_context() as repository:
            item = repository.get_event_item(event_id, include_hidden=True)
            context_loader = getattr(repository, "get_event_editor_context", None)
            editor_context = context_loader(event_id) if callable(context_loader) else None
        if item is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if editor_context:
            item.update(editor_context)
        return item

    @app.patch("/api/admin/events/{event_id}", dependencies=[admin_guard])
    def admin_moderate_event(event_id: str, payload: dict) -> dict:
        from app.services.ai_service import SCORING_CATEGORIES
        from app.services.manual_articles import SubmissionError, _validate_url_syntax
        from app.services.manual_richtext import (
            RichTextValidationError,
            normalize_editor_document,
        )
        from app.services.taxonomy import DISPLAY_CATEGORIES

        allowed_categories = set(SCORING_CATEGORIES) | {key for key, _ in DISPLAY_CATEGORIES}
        editable_fields = {
            "hidden", "title_zh", "one_line_summary", "summary_zh", "category",
            "tags", "author", "published_at", "original_url", "editor_document",
            "selection_mode",
        }
        fields = {
            key: value
            for key, value in (payload or {}).items()
            if key in editable_fields
        }
        if not fields:
            raise HTTPException(status_code=400, detail="No editable fields in payload")
        requested_fields = sorted(fields)
        if "category" in fields and str(fields["category"]) not in allowed_categories:
            raise HTTPException(
                status_code=400,
                detail=f"category must be one of: {', '.join(sorted(allowed_categories))}",
            )
        if "selection_mode" in fields and fields["selection_mode"] not in {
            "auto", "force_selected",
        }:
            raise HTTPException(status_code=422, detail="invalid selection_mode")
        if "original_url" in fields:
            original_url = str(fields.get("original_url") or "").strip()
            if original_url:
                try:
                    fields["original_url"] = _validate_url_syntax(original_url)
                except SubmissionError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            else:
                fields["original_url"] = ""
        if "published_at" in fields:
            value = str(fields.get("published_at") or "").strip()
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="invalid published_at") from exc
            fields["published_at"] = (
                parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            )
        if "editor_document" in fields:
            try:
                document, blocks, plain = normalize_editor_document(
                    fields.get("editor_document") or {}
                )
            except RichTextValidationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            fields["editor_document"] = document
            fields["original_blocks"] = blocks
            fields["original_text"] = plain
        with _admin_repository_context() as repository:
            update_content = getattr(repository, "update_event_content", None)
            found = (
                update_content(event_id, fields)
                if callable(update_content)
                else repository.update_event_moderation(event_id, fields)
            )
            if not found:
                raise HTTPException(status_code=404, detail="Event not found")
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "updated": requested_fields}

    @app.delete("/api/admin/events/{event_id}", dependencies=[admin_guard])
    def admin_delete_event(event_id: str) -> dict:
        with _admin_repository_context() as repository:
            deleted = repository.delete_raw_article(event_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Event not found")
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "deleted_raw_article_id": event_id}

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
