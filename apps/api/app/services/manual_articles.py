from __future__ import annotations

import os
import json
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.crawlers.base import canonicalize_url, normalize_article, stable_hash
from app.db.models import ArticleSubmissionModel, RawArticleModel
from app.models.domain import ContentValueDimensions, Source
from app.services.ai_service import embedding_input, provider_from_env
from app.services.manual_article_fetcher import ManualFetchError, fetch_manual_article
from app.services.manual_richtext import (
    RichTextValidationError,
    document_to_blocks,
    normalize_editor_document,
)
from app.services.scoring_service import select_processed_article


MANUAL_SOURCE_ID = "hotai_manual"
MANUAL_SOURCE_NAME = "AI·RADAR 手动添加"


class SubmissionError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def env_enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def submission_to_dict(model: ArticleSubmissionModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "idempotency_key": model.idempotency_key,
        "mode": model.mode,
        "publication_status": model.publication_status,
        "processing_status": model.processing_status,
        "processing_stage": model.processing_stage,
        "original_url": model.original_url,
        "editor_document": dict(model.editor_document or {}),
        "editor_text": model.editor_text or "",
        "manual_fields": dict(model.manual_fields or {}),
        "extracted_fields": dict(model.extracted_fields or {}),
        "ai_fields": dict(model.ai_fields or {}),
        "field_provenance": dict(model.field_provenance or {}),
        "selection_mode": model.selection_mode,
        "raw_article_id": model.raw_article_id,
        "last_error_code": model.last_error_code,
        "last_error_detail": model.last_error_detail,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        "published_at": model.published_at.isoformat() if model.published_at else None,
    }


def ensure_manual_article_source(repository: Any) -> Source:
    source = Source(
        id=MANUAL_SOURCE_ID,
        name=MANUAL_SOURCE_NAME,
        source_role="original",
        tier="T1",
        type="manual_article",
        category="industry",
        url="manual://articles",
        homepage=os.getenv("PUBLIC_SITE_URL", "https://suversal.com"),
        allowed_domains=[],
        language="zh",
        is_active=False,
        config={"system_managed": True, "manual_only": True},
    )
    repository.upsert_sources([source])
    return source


def _manual_fields(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title", "title_zh", "one_line_summary", "summary_zh", "author",
        "published_at", "language", "category", "tags", "source_name",
    }
    result = {key: payload[key] for key in allowed if key in payload}
    if "tags" in result and result["tags"] is not None:
        result["tags"] = [str(tag).strip() for tag in (result["tags"] or []) if str(tag).strip()][:5]
    for key in allowed - {"tags"}:
        if key in result and result[key] is not None:
            result[key] = str(result[key]).strip()
    category = str(result.get("category") or "")
    if category:
        from app.services.ai_service import SCORING_CATEGORIES

        if category not in SCORING_CATEGORIES:
            raise SubmissionError("invalid_category", "unsupported category", 422)
    return result


def _validate_document_size(document: dict[str, Any]) -> None:
    if len(json.dumps(document, ensure_ascii=False)) > 1_000_000:
        raise SubmissionError("invalid_document", "editor document is too large", 422)


def _validate_url_syntax(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SubmissionError("invalid_url", "only HTTP/HTTPS URLs are allowed", 422)
    return parsed.geturl()


def create_submission(repository: Any, payload: dict[str, Any]) -> ArticleSubmissionModel:
    original_url = str(payload.get("original_url") or "").strip() or None
    mode = "url" if original_url else "editor"
    canonical_hash = None
    if original_url:
        original_url = _validate_url_syntax(original_url)
        try:
            canonical_hash = stable_hash(canonicalize_url(original_url))
        except Exception as exc:
            raise SubmissionError("invalid_url", "original_url is invalid", 422) from exc
    idempotency_key = str(payload.get("idempotency_key") or uuid.uuid4()).strip()
    existing = repository.get_submission_by_idempotency_key(idempotency_key)
    if existing is not None:
        return existing
    document = payload.get("editor_document") or {}
    _validate_document_size(document)
    try:
        document, _blocks, editor_text = normalize_editor_document(document)
    except RichTextValidationError as exc:
        raise SubmissionError("invalid_document", str(exc), 422) from exc
    model = ArticleSubmissionModel(
        id=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        mode=mode,
        original_url=original_url,
        canonical_url_hash=canonical_hash,
        editor_document=document,
        editor_text=editor_text,
        manual_fields=_manual_fields(payload.get("manual_fields") or {}),
        selection_mode=str(payload.get("selection_mode") or "auto"),
    )
    if model.selection_mode not in {"auto", "force_selected"}:
        raise SubmissionError("invalid_selection_mode", "invalid selection mode", 422)
    repository.session.add(model)
    repository.session.flush()
    ensure_manual_article_source(repository)
    return model


def update_submission(model: ArticleSubmissionModel, payload: dict[str, Any]) -> None:
    if model.processing_status in {"fetching", "scoring"}:
        raise SubmissionError("processing", "submission is currently processing", 409)
    value = (
        str(payload.get("original_url") or "").strip() or None
        if "original_url" in payload
        else model.original_url
    )
    if value:
        value = _validate_url_syntax(value)
    model.original_url = value
    model.canonical_url_hash = stable_hash(canonicalize_url(value)) if value else None
    model.mode = "url" if value else "editor"
    if "editor_document" in payload:
        document = payload.get("editor_document") or {}
        _validate_document_size(document)
        try:
            document, _blocks, editor_text = normalize_editor_document(document)
        except RichTextValidationError as exc:
            raise SubmissionError("invalid_document", str(exc), 422) from exc
        model.editor_document = document
        model.editor_text = editor_text
    if "manual_fields" in payload:
        merged = dict(model.manual_fields or {})
        merged.update(_manual_fields(payload.get("manual_fields") or {}))
        model.manual_fields = merged
    if "selection_mode" in payload:
        selection_mode = str(payload.get("selection_mode") or "auto")
        if selection_mode not in {"auto", "force_selected"}:
            raise SubmissionError("invalid_selection_mode", "invalid selection mode", 422)
        model.selection_mode = selection_mode
    model.processing_status = "idle"
    model.processing_stage = None
    model.last_error_code = None
    model.last_error_detail = None


def _commit_processing_stage(repository: Any) -> None:
    commit = getattr(getattr(repository, "session", None), "commit", None)
    if callable(commit):
        commit()


def _serialize_scoring(
    scoring: Any, embedding: list[float] | None, embedding_model: str
) -> dict[str, Any]:
    return {
        "ai_focus": scoring.ai_focus,
        "dimensions": asdict(scoring.dimensions),
        "category": scoring.category,
        "focus_category": scoring.focus_category,
        "tags": list(scoring.tags),
        "title_zh": scoring.title_zh,
        "one_line_summary": scoring.one_line_summary,
        "summary_zh": scoring.summary_zh,
        "reason_zh": scoring.reason_zh,
        "action_zh": scoring.action_zh,
        "embedding": embedding,
        "embedding_model": embedding_model,
    }


def process_submission(repository: Any, submission_id: str, *, ai_provider: Any = None) -> ArticleSubmissionModel:
    model = repository.get_submission_model(submission_id, for_update=True)
    if model is None:
        raise SubmissionError("not_found", "submission not found", 404)
    if model.processing_status in {"fetching", "scoring"}:
        raise SubmissionError("processing", "submission is currently processing", 409)
    model.processing_status = "fetching" if model.mode == "url" else "scoring"
    model.processing_stage = model.processing_status
    model.last_error_code = None
    model.last_error_detail = None
    repository.session.flush()
    _commit_processing_stage(repository)
    try:
        if model.mode == "url":
            extracted = fetch_manual_article(str(model.original_url))
            canonical_url = str(extracted.get("canonical_url") or "").strip()
            if canonical_url:
                model.canonical_url_hash = stable_hash(canonicalize_url(canonical_url))
        else:
            blocks, editor_text = document_to_blocks(dict(model.editor_document or {}))
            extracted = {
                "canonical_url": None,
                "title": "",
                "content": editor_text,
                "author": None,
                "published_at": None,
                "language": "zh" if any("\u4e00" <= c <= "\u9fff" for c in editor_text) else "en",
                "original_blocks": blocks,
                "original_paragraphs": [
                    block["text"] for block in blocks if block.get("type") in {"paragraph", "heading"}
                ],
                "original_images": [block for block in blocks if block.get("type") == "image"],
                "content_origin": "manual_editor",
            }
        editor_text = (model.editor_text or "").strip()
        if editor_text:
            editor_blocks, editor_text = document_to_blocks(dict(model.editor_document or {}))
            extracted.update(
                {
                    "content": editor_text,
                    "original_blocks": editor_blocks,
                    "original_paragraphs": [
                        block["text"]
                        for block in editor_blocks
                        if block.get("type") in {"paragraph", "heading"}
                    ],
                    "original_images": [
                        block for block in editor_blocks if block.get("type") == "image"
                    ],
                    "content_origin": (
                        "manual_editor" if model.mode == "editor" else "manual_url_editor"
                    ),
                }
            )
        content = editor_text or str(extracted.get("content") or "").strip()
        factual_chars = sum(char.isalnum() for char in content)
        if factual_chars < int(os.getenv("MANUAL_ARTICLE_MIN_CONTENT_CHARS", "40")):
            raise SubmissionError(
                "insufficient_content",
                "没有抓取或填写到足够的事实正文，不能让 AI 凭链接生成内容",
                422,
            )
        model.extracted_fields = {**extracted, "content": content}
        model.processing_status = "scoring"
        model.processing_stage = "scoring"
        repository.session.flush()
        _commit_processing_stage(repository)
        manual = dict(model.manual_fields or {})
        scoring_title = str(manual.get("title") or extracted.get("title") or content[:80]).strip()
        provider = ai_provider or provider_from_env()
        scoring = provider.score_article(scoring_title, content)
        embedding = None
        embedding_error = None
        try:
            embedding = provider.embed_text(embedding_input(scoring_title, content))
        except Exception as exc:  # embedding failure is explicitly non-blocking
            embedding_error = str(exc)[:300]
        embedding_model = str(getattr(provider, "embedding_model", "manual-provider"))
        ai_fields = _serialize_scoring(scoring, embedding, embedding_model)
        if embedding_error:
            ai_fields["embedding_error"] = embedding_error
        model.ai_fields = ai_fields
        provenance = {}
        for field in ("title_zh", "one_line_summary", "summary_zh", "category", "tags"):
            provenance[field] = "manual" if manual.get(field) else "ai"
        for field in ("author", "published_at", "language"):
            provenance[field] = "manual" if manual.get(field) else "extracted"
        model.field_provenance = provenance
        model.processing_status = "ready"
        model.processing_stage = None
        return model
    except (ManualFetchError, RichTextValidationError, SubmissionError) as exc:
        code = exc.code if isinstance(exc, (ManualFetchError, SubmissionError)) else "invalid_document"
        model.processing_status = "failed"
        model.processing_stage = None
        model.last_error_code = code
        model.last_error_detail = str(exc)[:500]
        return model
    except Exception as exc:
        model.processing_status = "failed"
        model.processing_stage = None
        model.last_error_code = "ai_failed"
        model.last_error_detail = str(exc)[:500]
        return model


def _parse_datetime(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback.replace(tzinfo=timezone.utc) if fallback.tzinfo is None else fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _source_for_submission(repository: Any, model: ArticleSubmissionModel) -> Source:
    # A single inactive source makes every manually added article easy to
    # filter in content management. URL submissions still keep their actual
    # original URL in raw_articles.source_url.
    return ensure_manual_article_source(repository)


def publish_submission(repository: Any, submission_id: str) -> ArticleSubmissionModel:
    model = repository.get_submission_model(submission_id, for_update=True)
    if model is None:
        raise SubmissionError("not_found", "submission not found", 404)
    if model.processing_status != "ready":
        raise SubmissionError("not_ready", "submission must be processed before publishing", 409)
    manual = dict(model.manual_fields or {})
    extracted = dict(model.extracted_fields or {})
    ai = dict(model.ai_fields or {})
    if not ai.get("dimensions"):
        raise SubmissionError("ai_failed", "AI scoring result is missing", 502)
    source = _source_for_submission(repository, model)
    now = datetime.now(timezone.utc)
    source_url = (
        str(extracted.get("canonical_url") or model.original_url)
        if model.mode == "url"
        else f"manual://{model.id}"
    )
    canonical_hash = stable_hash(canonicalize_url(source_url))
    existing = repository.find_raw_article_by_url_hash(canonical_hash)
    if existing is not None and existing.id != model.raw_article_id:
        raise SubmissionError("duplicate_url", f"article already exists: {existing.id}", 409)
    content = str(extracted.get("content") or model.editor_text or "").strip()
    raw_title = str(manual.get("title") or extracted.get("title") or ai.get("title_zh") or "").strip()
    published_at = _parse_datetime(
        manual.get("published_at") or extracted.get("published_at"),
        model.created_at or now,
    )
    metadata = {
        "ingest_origin": "manual_editor" if model.mode == "editor" else "manual_url",
        "submission_id": model.id,
        "content_origin": extracted.get("content_origin"),
        "original_blocks": list(extracted.get("original_blocks") or []),
        "original_paragraphs": list(extracted.get("original_paragraphs") or []),
        "original_images": list(extracted.get("original_images") or []),
        "original_text": content,
        "manual_content_locked": bool(model.editor_text),
    }
    if model.editor_document:
        metadata["editor_document"] = dict(model.editor_document)
    article = normalize_article(
        source=source,
        source_url=source_url,
        title=raw_title,
        content=content,
        author=str(manual.get("author") or extracted.get("author") or "").strip() or None,
        published_at=published_at,
        language=str(manual.get("language") or extracted.get("language") or source.language),
        raw_score={},
        metadata=metadata,
    )
    if model.raw_article_id:
        article.id = model.raw_article_id
    dimensions = ContentValueDimensions(
        **{key: float(value) for key, value in ai["dimensions"].items()}
    )
    ai_focus = str(ai.get("ai_focus") or "contributing")
    processed = select_processed_article(
        article=article,
        source=source,
        ai_focus=ai_focus,
        dimensions=dimensions,
        category=str(ai.get("category") or "industry"),
        tags=list(ai.get("tags") or []),
        generated_fields={
            "title_zh": str(ai.get("title_zh") or raw_title),
            "one_line_summary": str(ai.get("one_line_summary") or ""),
            "summary_zh": str(ai.get("summary_zh") or ""),
            "reason_zh": str(ai.get("reason_zh") or ""),
            "action_zh": str(ai.get("action_zh") or ""),
        },
        focus_category=(
            str(ai.get("focus_category"))
            if ai.get("focus_category")
            else None
        ),
    )
    if model.selection_mode == "force_selected":
        processed = replace(
            processed,
            selected=True,
            status="processed",
            rejection_reason=None,
            selection_origin="admin",
            selection_reason="admin:force_selected",
        )
    if model.raw_article_id:
        raw_model = repository.session.get(RawArticleModel, model.raw_article_id)
        if raw_model is not None:
            raw_model.source_id = article.source_id
            raw_model.source_url = article.source_url
            raw_model.title = article.title
            raw_model.content = article.content
            raw_model.author = article.author
            raw_model.language = article.language
            raw_model.published_at = article.published_at
            raw_model.title_hash = article.title_hash
            raw_model.url_hash = article.url_hash
            raw_model.raw_metadata = metadata
            raw_model.status = "raw"
        else:
            repository.upsert_raw_articles([article])
    else:
        repository.upsert_raw_articles([article])
    if model.selection_mode == "auto":
        repository.release_admin_selection(article.id)
    repository.upsert_processed_articles([processed])
    embedding = ai.get("embedding")
    if embedding:
        repository.upsert_article_embedding(
            article.id,
            embedding_model=str(ai.get("embedding_model") or "manual-provider"),
            vector=[float(value) for value in embedding],
            source_hash=stable_hash(embedding_input(article.title, article.content)),
        )
    override_fields = {
        "title_zh": manual.get("title_zh") or manual.get("title"),
        "one_line_summary": manual.get("one_line_summary"),
        "summary_zh": manual.get("summary_zh"),
        "category": manual.get("category"),
        # Draft tags left blank mean "use AI". Passing None also clears a
        # stale empty override when an existing submission is re-published.
        "tags": manual.get("tags") or None,
    }
    repository.upsert_article_manual_override(article.id, override_fields)
    model.raw_article_id = article.id
    model.publication_status = "published"
    model.published_at = now
    repository.session.flush()
    return model


def process_and_materialize_submission(
    repository: Any,
    submission_id: str,
    *,
    ai_provider: Any = None,
) -> ArticleSubmissionModel:
    """Score a draft, materialize it, and keep it private for editorial review."""
    model = process_submission(repository, submission_id, ai_provider=ai_provider)
    if model.processing_status != "ready":
        return model
    model = publish_submission(repository, submission_id)
    event_id = f"a{str(model.raw_article_id)[:12]}"
    if not repository.update_event_moderation(event_id, {"hidden": True}):
        raise SubmissionError(
            "materialization_failed",
            "AI 评分已完成，但未能创建隐藏文章记录",
            500,
        )
    return model
