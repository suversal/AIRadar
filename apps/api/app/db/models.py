from __future__ import annotations

try:
    from sqlalchemy import (
        JSON,
        Boolean,
        DateTime,
        Float,
        ForeignKey,
        Integer,
        String,
        Text,
        func,
    )
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard for local stdlib tests
    raise RuntimeError("SQLAlchemy is required for database models.") from exc


class Base(DeclarativeBase):
    pass


class SourceModel(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source_role: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    homepage: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_domains: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    fetch_interval_min: Mapped[int] = mapped_column(Integer, default=60)
    language: Mapped[str] = mapped_column(String, default="en")
    need_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    need_browser: Mapped[bool] = mapped_column(Boolean, default=False)
    can_be_main_source: Mapped[bool] = mapped_column(Boolean, default=True)
    affects_heat_score: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_crawled_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class RawArticleModel(Base):
    __tablename__ = "raw_articles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str | None] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="en")
    published_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    crawled_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    title_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    url_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="raw")
    skipped_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

