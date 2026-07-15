"""One-shot, idempotent repair of legacy rows written before the 2026-07-11
data-quality fixes. Safe to re-run: every step only touches rows that are
still in the legacy shape.

- processed_articles.event_cluster_id cache column: re-derived from the
  membership table (is_main event first, else the most recently joined).
- article_embeddings with embedding_model='unknown': re-embedded with the
  real local model, writing the true model name and a fresh source_hash.
- event_clusters.source_count: recounted from the membership table.
- pipeline_runs.finished_at is deliberately NOT touched: there is no
  trustworthy source for historical finish times, and faking them would be
  worse than NULL.
- raw_articles whose extracted body still duplicates the page title as its
  first paragraph, or still carries a byline avatar image (both fixed in
  extract_article_content on 2026-07-11): re-fetched from the original page
  with a fresh cache dir (the on-disk page cache is immutable and was built
  by the pre-fix extractor, so it must be bypassed here) and, if a
  translation exists, retranslated.

Usage:
    .venv/bin/python scripts/repair_legacy_data.py \
        --database-url postgresql+psycopg://radar:radar@localhost:5432/radar
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.crawlers.base import stable_hash  # noqa: E402
from app.crawlers.article_content import (  # noqa: E402
    CONTENT_EXTRACTION_VERSION,
    profile_for_url,
)
from app.db.models import (  # noqa: E402
    ArticleEmbeddingModel,
    ArticleTranslationModel,
    EventClusterArticleModel,
    EventClusterModel,
    ProcessedArticleModel,
    RawArticleModel,
)
from app.services.ai_service import embedding_input  # noqa: E402

_AVATAR_URL_RE = re.compile(r"avatar", re.IGNORECASE)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w一-鿿]", "", text or "").lower()


def repair_event_links(session) -> int:
    """Point the processed_articles cache column back at the membership
    table's truth. is_main membership wins; otherwise the latest joined."""
    fixed = 0
    processed_rows = session.scalars(select(ProcessedArticleModel)).all()
    for processed in processed_rows:
        memberships = session.scalars(
            select(EventClusterArticleModel).where(
                EventClusterArticleModel.raw_article_id == processed.raw_article_id
            )
        ).all()
        if not memberships:
            continue
        main = next((m for m in memberships if m.is_main), None)
        chosen = main or max(memberships, key=lambda m: (m.joined_at, m.id))
        if processed.event_cluster_id != chosen.event_cluster_id:
            processed.event_cluster_id = chosen.event_cluster_id
            fixed += 1
    return fixed


def reembed_unknown(session, *, embedder) -> int:
    """Recompute every 'unknown' embedding with the real local model so the
    row carries the true model name and a hash of the actual input."""
    fixed = 0
    rows = session.scalars(
        select(ArticleEmbeddingModel).where(ArticleEmbeddingModel.embedding_model == "unknown")
    ).all()
    for row in rows:
        article = session.get(RawArticleModel, row.raw_article_id)
        if article is None:
            continue
        text = embedding_input(article.title, article.content)
        row.content_vector = embedder.embed_text(text)
        row.embedding_model = embedder.model_name
        row.source_hash = stable_hash(text)
        fixed += 1
    return fixed


def recount_source_counts(session) -> int:
    """Recount distinct sources per event from the membership table."""
    fixed = 0
    for cluster in session.scalars(select(EventClusterModel)).all():
        count = len(
            session.execute(
                select(RawArticleModel.source_id)
                .join(
                    EventClusterArticleModel,
                    EventClusterArticleModel.raw_article_id == RawArticleModel.id,
                )
                .where(EventClusterArticleModel.event_cluster_id == cluster.id)
                .distinct()
            ).all()
        )
        if count and cluster.source_count != count:
            cluster.source_count = count
            fixed += 1
    return fixed


def find_articles_needing_reextraction(session) -> list[str]:
    """Rows whose stored original_paragraphs/original_images still show the
    pre-2026-07-11 extraction bugs: first paragraph duplicating the page
    title, or an avatar-pattern image kept as if it were content."""
    ids: list[str] = []
    for row in session.scalars(select(RawArticleModel)).all():
        metadata = row.raw_metadata or {}
        paragraphs = metadata.get("original_paragraphs") or []
        images = metadata.get("original_images") or []
        title_duplicated = bool(paragraphs) and _normalize(paragraphs[0]) == _normalize(row.title)
        has_avatar = any(_AVATAR_URL_RE.search(img.get("url") or "") for img in images)
        if title_duplicated or has_avatar:
            ids.append(row.id)
    return ids


def find_full_page_articles_needing_reextraction(
    session, *, resume_after: str | None = None, limit: int | None = None
) -> list[str]:
    """All full-page rows written by an older extractor, in stable ID order.
    Stable ordering makes --resume-after safe and repeatable."""
    ids = []
    rows = session.scalars(select(RawArticleModel).order_by(RawArticleModel.id)).all()
    for row in rows:
        metadata = row.raw_metadata or {}
        if metadata.get("content_origin") != "full_page":
            continue
        version_is_current = (
            int(metadata.get("content_extraction_version") or 0)
            >= CONTENT_EXTRACTION_VERSION
        )
        profile = profile_for_url(row.source_url)
        profile_is_current = not profile or metadata.get("content_profile") == profile.name
        if version_is_current and profile_is_current:
            continue
        if resume_after and row.id <= resume_after:
            continue
        ids.append(row.id)
        if limit and len(ids) >= limit:
            break
    return ids


def reextract_article_content(
    session,
    article_id: str,
    *,
    fetch_payload: Callable[[str], dict[str, Any] | None],
    translate: Callable[[list[str]], list[str]] | None = None,
    embedder: Any | None = None,
) -> bool:
    """Re-fetch one article's page and overwrite its content/metadata with
    the corrected extraction. Deliberately bypasses the normal upsert's
    "longer content wins" merge: the fix can legitimately produce SHORTER
    (more correct) content, which that merge would otherwise reject."""
    row = session.get(RawArticleModel, article_id)
    if row is None:
        return False
    payload = fetch_payload(row.source_url)
    if not payload:
        return False

    row.content = payload["content"]
    merged = dict(row.raw_metadata or {})
    merged.update(payload["metadata"])
    merged["content_origin"] = "full_page"
    row.raw_metadata = merged

    if translate is not None:
        translation = session.scalar(
            select(ArticleTranslationModel).where(
                ArticleTranslationModel.raw_article_id == article_id
            )
        )
        if translation is not None:
            paragraphs = payload["metadata"].get("original_paragraphs") or [row.content]
            try:
                translation.translated_paragraphs = translate(paragraphs)
                from types import SimpleNamespace
                from app.pipeline.runner import _translated_blocks_for

                translation.translated_blocks = _translated_blocks_for(
                    SimpleNamespace(metadata=merged), translation.translated_paragraphs
                )
                translation.source_hash = stable_hash("\n".join(paragraphs))
                translation.status = "completed"
                translation.error = None
            except Exception as exc:  # one flaky AI response must not kill the whole repair run
                translation.status = "failed"
                translation.error = str(exc)[:200]
    embedding = session.scalar(
        select(ArticleEmbeddingModel).where(ArticleEmbeddingModel.raw_article_id == article_id)
    )
    if embedding is not None and embedder is not None:
        text = embedding_input(row.title, row.content)
        embedding.content_vector = embedder.embed_text(text)
        embedding.embedding_model = embedder.model_name
        embedding.source_hash = stable_hash(text)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="skip the re-embedding step (no local model download needed)",
    )
    parser.add_argument(
        "--reextract-full-page",
        action="store_true",
        help="re-fetch every full_page row whose extractor version or domain profile is stale",
    )
    parser.add_argument("--dry-run", action="store_true", help="report candidate IDs without writing")
    parser.add_argument("--resume-after", help="resume after this raw article ID")
    parser.add_argument("--limit", type=int, help="maximum number of full-page rows this run")
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument("--domain-delay", type=float, default=2.0)
    parser.add_argument(
        "--skip-reextraction",
        action="store_true",
        help="skip re-fetching pages for title-duplication/avatar-image cleanup (no network calls)",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory, session_scope

    session_factory = build_session_factory(args.database_url)
    if args.dry_run:
        with session_scope(session_factory) as session:
            article_ids = (
                find_full_page_articles_needing_reextraction(
                    session, resume_after=args.resume_after, limit=args.limit
                )
                if args.reextract_full_page
                else find_articles_needing_reextraction(session)
            )
        print(f"dry-run: {len(article_ids)} article(s) need re-extraction")
        for article_id in article_ids:
            print(article_id)
        return 0
    with session_scope(session_factory) as session:
        links = repair_event_links(session)
        embeddings = 0
        if not args.skip_embeddings:
            from app.services.ai_service import LocalEmbeddingProvider

            embeddings = reembed_unknown(session, embedder=LocalEmbeddingProvider())
        counts = recount_source_counts(session)

    reextracted = 0
    reextraction_failed = 0
    if not args.skip_reextraction:
        from app.crawlers.page_content import fetch_page_payload
        from app.services.ai_service import LocalEmbeddingProvider, provider_from_env

        provider = provider_from_env()
        with session_scope(session_factory) as session:
            article_ids = (
                find_full_page_articles_needing_reextraction(
                    session, resume_after=args.resume_after, limit=args.limit
                )
                if args.reextract_full_page
                else find_articles_needing_reextraction(session)
            )
        embedder = None if args.skip_embeddings else LocalEmbeddingProvider()
        last_fetch_by_domain: dict[str, float] = {}
        with tempfile.TemporaryDirectory() as tmp:
            fresh_cache = Path(tmp)
            for article_id in article_ids:
                with session_scope(session_factory) as session:
                    row = session.get(RawArticleModel, article_id)
                    url = row.source_url if row else ""
                domain = urlparse(url).netloc.lower()
                elapsed = time.monotonic() - last_fetch_by_domain.get(domain, 0.0)
                if domain and elapsed < args.domain_delay:
                    time.sleep(args.domain_delay - elapsed)
                last_fetch_by_domain[domain] = time.monotonic()

                def fetch_with_retry(target_url: str) -> dict[str, Any] | None:
                    for attempt in range(max(1, args.retry_attempts)):
                        try:
                            payload = fetch_page_payload(target_url, cache_dir=fresh_cache)
                            if payload:
                                return payload
                        except Exception:
                            if attempt + 1 < max(1, args.retry_attempts):
                                time.sleep(min(2 ** attempt, 4))
                    return None

                with session_scope(session_factory) as session:
                    ok = reextract_article_content(
                        session,
                        article_id,
                        fetch_payload=fetch_with_retry,
                        translate=provider.translate_paragraphs,
                        embedder=embedder,
                    )
                if ok:
                    reextracted += 1
                    print(f"reextracted {article_id}")
                else:
                    reextraction_failed += 1
                    print(f"failed {article_id}")

    print(
        f"repaired: event links={links}, unknown embeddings={embeddings}, "
        f"source counts={counts}, reextracted articles={reextracted} "
        f"(failed={reextraction_failed})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
