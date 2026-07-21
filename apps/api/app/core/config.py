from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _find_env_file(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate_dir in [current, *current.parents]:
        candidate = candidate_dir / ".env"
        if candidate.exists():
            return candidate
    return None


def load_env_file(path: Path | str | None = None, *, override: bool = False) -> dict[str, str]:
    env_path = Path(path) if path is not None else _find_env_file()
    if env_path is None or not env_path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        loaded[key] = _strip_env_value(value)
        if override or key not in os.environ:
            os.environ[key] = loaded[key]
    return loaded


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    openai_api_key: str | None
    jwt_secret: str
    github_token: str | None = None
    default_scoring_model: str = "gpt-4.1-mini"
    default_summary_model: str = "gpt-4.1-mini"
    default_embedding_model: str = "text-embedding-3-small"
    # 0.85 was too low for bge-small-zh-v1.5 (the local embedding model in
    # actual use): a real-data check found completely unrelated AI-news
    # articles scoring 0.79-0.89 cosine similarity against each other, so a
    # 0.85 threshold merged unrelated events together.
    # 2026-07-21 recalibration: sampled 14 days of same-day zh-language
    # article pairs. [0.90, 0.93) was ~41 pairs/14d and, on manual review,
    # essentially all genuine same-event duplicates missed by 0.93 (e.g. two
    # outlets both covering the same product launch). [0.85, 0.90) already
    # mixes in real false positives matching the same failure mode as the
    # 0.85 case above (e.g. two unrelated vulnerability-patch stories, or
    # two different facts about the same company) - stayed above that band.
    cluster_similarity_threshold: float = 0.90
    # rolling aggregation scope: an event only absorbs new coverage seen
    # within this window (product decision 2026-07-11: 24h rolling hot set)
    cluster_window_hours: int = 24

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "postgresql+psycopg://radar:radar@db:5432/radar"),
            redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            jwt_secret=os.getenv("JWT_SECRET", "dev-only-change-me"),
            github_token=os.getenv("GITHUB_TOKEN"),
            default_scoring_model=os.getenv("DEFAULT_SCORING_MODEL", "gpt-4.1-mini"),
            default_summary_model=os.getenv("DEFAULT_SUMMARY_MODEL", "gpt-4.1-mini"),
            default_embedding_model=os.getenv(
                "DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            cluster_similarity_threshold=float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.90")),
            cluster_window_hours=int(os.getenv("CLUSTER_WINDOW_HOURS", "24")),
        )
