from __future__ import annotations

import os
from dataclasses import dataclass


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
    daily_candidate_limit: int = 100
    daily_selected_limit: int = 12
    cluster_similarity_threshold: float = 0.85
    cluster_window_hours: int = 72

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
            daily_candidate_limit=int(os.getenv("DAILY_CANDIDATE_LIMIT", "100")),
            daily_selected_limit=int(os.getenv("DAILY_SELECTED_LIMIT", "12")),
            cluster_similarity_threshold=float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.85")),
            cluster_window_hours=int(os.getenv("CLUSTER_WINDOW_HOURS", "72")),
        )
