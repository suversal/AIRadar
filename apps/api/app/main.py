from __future__ import annotations

from datetime import date
from pathlib import Path

from app.api.public import build_daily_payload, build_latest_payload
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


def create_app():
    try:
        from fastapi import FastAPI
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI is not installed. Install requirements.txt first.") from exc

    app = FastAPI(title="Suversal AI Radar API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/public/latest")
    def latest() -> dict:
        return build_latest_payload(load_latest_daily_json())

    @app.get("/api/public/daily/{report_date}")
    def daily(report_date: str) -> dict:
        report_path = DATA_DIR / "reports" / f"{report_date}.json"
        if report_path.exists():
            return build_daily_payload(read_json(report_path))
        return build_daily_payload(load_latest_daily_json())

    return app


try:
    app = create_app()
except RuntimeError:
    app = None
