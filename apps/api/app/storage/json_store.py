from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.models.domain import DailyReport, EventCluster, ProcessedArticle, RawArticle, Source


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_to_dict(source: Source) -> dict[str, Any]:
    return asdict(source)


def source_from_dict(payload: dict[str, Any]) -> Source:
    return Source(**payload)


def save_sources(path: Path, sources: list[Source]) -> None:
    write_json(path, [source_to_dict(source) for source in sources])


def load_sources(path: Path) -> list[Source]:
    return [source_from_dict(payload) for payload in read_json(path)]


def article_to_dict(article: RawArticle) -> dict[str, Any]:
    return asdict(article)


def article_from_dict(payload: dict[str, Any]) -> RawArticle:
    payload = dict(payload)
    payload["published_at"] = datetime.fromisoformat(payload["published_at"])
    return RawArticle(**payload)


def save_articles(path: Path, articles: list[RawArticle]) -> None:
    write_json(path, [article_to_dict(article) for article in articles])


def load_articles(path: Path) -> list[RawArticle]:
    return [article_from_dict(payload) for payload in read_json(path)]


def processed_to_dict(processed: ProcessedArticle) -> dict[str, Any]:
    return asdict(processed)


def cluster_to_dict(cluster: EventCluster) -> dict[str, Any]:
    return asdict(cluster)


def report_to_dict(report: DailyReport) -> dict[str, Any]:
    return asdict(report)

