from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator

from app.api.public import (
    build_daily_payload,
    build_daily_payload_from_repository,
    build_latest_payload,
    build_latest_payload_from_repository,
)
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
    try:
        from fastapi import FastAPI, HTTPException
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI is not installed. Install requirements.txt first.") from exc

    app = FastAPI(title="Suversal AI Radar API", version="0.1.0")

    def report_repository_context():
        if report_repository_factory is not None:
            return nullcontext(report_repository_factory())
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            return open_database_report_repository(database_url)
        return None

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

    @app.post("/api/admin/refresh-latest")
    def refresh_latest() -> dict:
        if refresh_runner is not None:
            return refresh_runner()
        try:
            from app.services.refresh_service import refresh_latest_report

            return refresh_latest_report(
                data_dir=data_dir,
                database_url=os.getenv("DATABASE_URL"),
                limit=100,
                top_n=12,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


try:
    app = create_app()
except RuntimeError:
    app = None
