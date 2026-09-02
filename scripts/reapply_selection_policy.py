#!/usr/bin/env python3
"""Reapply the deterministic featured-selection policy to stored scores.

This does not call AI and does not change dimensions or final_score. Manual
admin selections are always preserved. The default is a dry run; pass --apply
to update processed_articles.

Examples:
    .venv/bin/python scripts/reapply_selection_policy.py --days 30
    .venv/bin/python scripts/reapply_selection_policy.py --days 30 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db.models import ProcessedArticleModel, RawArticleModel, SourceModel  # noqa: E402
from app.db.session import build_session_factory, session_scope  # noqa: E402
from app.models.domain import ContentValueDimensions, RawArticle, Source  # noqa: E402
from app.services.scoring_service import decide_featured_selection  # noqa: E402


def _domain_article(raw: RawArticleModel, source: SourceModel) -> RawArticle:
    return RawArticle(
        id=raw.id,
        source_id=raw.source_id,
        source_name=source.name,
        source_role=source.source_role,
        source_tier=source.tier,
        source_url=raw.source_url,
        title=raw.title,
        content=raw.content or "",
        author=raw.author,
        published_at=raw.published_at,
        language=raw.language,
        raw_score={},
        metadata=raw.raw_metadata or {},
        title_hash=raw.title_hash,
        url_hash=raw.url_hash,
        status=raw.status,
        skipped_reason=raw.skipped_reason,
    )


def _domain_source(source: SourceModel) -> Source:
    return Source(
        id=source.id,
        name=source.name,
        source_role=source.source_role,
        tier=source.tier,
        type=source.type,
        category=source.category,
        url=source.url,
        homepage=source.homepage,
        allowed_domains=list(source.allowed_domains or []),
        fetch_interval_min=source.fetch_interval_min,
        language=source.language,
        need_proxy=source.need_proxy,
        need_browser=source.need_browser,
        can_be_main_source=source.can_be_main_source,
        affects_heat_score=source.affects_heat_score,
        is_active=source.is_active,
        config=source.config_json or {},
    )


def reapply(session, *, days: int, apply: bool) -> dict[str, object]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.execute(
        select(ProcessedArticleModel, RawArticleModel, SourceModel)
        .join(RawArticleModel, RawArticleModel.id == ProcessedArticleModel.raw_article_id)
        .join(SourceModel, SourceModel.id == RawArticleModel.source_id)
        .where(RawArticleModel.published_at >= cutoff)
        .order_by(RawArticleModel.published_at.desc())
    ).all()

    transitions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    reason_groups: Counter[str] = Counter()
    changed_ids: list[str] = []
    priority_samples: list[dict[str, object]] = []
    preserved_admin = 0
    current_selected = 0
    projected_selected = 0
    now = datetime.now(timezone.utc)

    for processed, raw, source in rows:
        old_selected = processed.status == "processed"
        current_selected += int(old_selected)
        if processed.selection_origin == "admin":
            preserved_admin += 1
            projected_selected += int(old_selected)
            continue

        decision = decide_featured_selection(
            article=_domain_article(raw, source),
            source=_domain_source(source),
            ai_focus=processed.ai_focus,
            dimensions=ContentValueDimensions(
                impact=processed.impact,
                novelty=processed.novelty,
                substance=processed.substance,
            ),
            category=processed.category,
            generated_fields={"title_zh": processed.title_zh},
            final_score=processed.final_score,
        )
        projected_selected += int(decision.selected)
        transitions[f"{old_selected}->{decision.selected}"] += 1
        reason = decision.selection_reason or decision.rejection_reason or "none"
        reasons[reason] += 1
        if reason.startswith("final_score:"):
            reason_groups["score_pass" if decision.selected else "score_reject"] += 1
        elif reason.startswith("ai_focus:"):
            reason_groups["non_selectable_ai_focus"] += 1
        else:
            reason_groups[reason] += 1
        if reason.startswith("priority:") and len(priority_samples) < 20:
            priority_samples.append(
                {
                    "id": raw.id,
                    "title": raw.title,
                    "title_zh": processed.title_zh,
                    "final_score": processed.final_score,
                    "reason": reason,
                }
            )

        changed = (
            old_selected != decision.selected
            or processed.selection_origin != decision.selection_origin
            or processed.selection_reason != decision.selection_reason
            or processed.rejection_reason != decision.rejection_reason
        )
        if not changed:
            continue

        changed_ids.append(raw.id)
        if apply:
            processed.status = "processed" if decision.selected else "rejected"
            processed.selection_origin = decision.selection_origin
            processed.selection_reason = decision.selection_reason
            processed.rejection_reason = decision.rejection_reason
            processed.updated_at = now

    return {
        "days": days,
        "mode": "apply" if apply else "dry-run",
        "examined": len(rows),
        "preserved_admin": preserved_admin,
        "current_selected": current_selected,
        "projected_selected": projected_selected,
        "current_selection_rate": round(current_selected / len(rows), 4) if rows else 0.0,
        "projected_selection_rate": round(projected_selected / len(rows), 4) if rows else 0.0,
        "changed": len(changed_ids),
        "changed_sample_ids": changed_ids[:10],
        "transitions": dict(sorted(transitions.items())),
        "reason_groups": dict(reason_groups.most_common()),
        "priority_samples": priority_samples,
        "top_exact_reasons": dict(reasons.most_common(20)),
        "note": "This script does not regenerate historical daily/weekly/monthly reports.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.days < 1 or args.days > 3650:
        parser.error("--days must be between 1 and 3650")

    session_factory = build_session_factory(args.database_url)
    with session_scope(session_factory) as session:
        result = reapply(session, days=args.days, apply=args.apply)
        if not args.apply:
            session.rollback()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
