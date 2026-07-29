#!/usr/bin/env python3
"""Restore AI tags hidden by the legacy empty manual-tag override bug.

Dry-run is the default. Pass --apply to update only the seven records
confirmed during the 2026-07-29 diagnosis.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import load_env_file  # noqa: E402
from app.db.models import (  # noqa: E402
    ArticleSubmissionModel,
    EditorialOverrideModel,
    ProcessedArticleModel,
)
from app.db.session import build_session_factory  # noqa: E402


CONFIRMED_RAW_ARTICLE_IDS = (
    "768a00d3495efd3e3e94e49a",
    "17b10c5c7b2bd69416687661",
    "6703fdd7621574e13738563c",
    "8d3be6bfc3ba32d4b1404659",
    "179daf8e4f3fcef708e3401b",
    "3138311e8781e940b84af401",
    "f117e47bedb0f839708096cc",
)


@dataclass(frozen=True)
class RepairCandidate:
    raw_article_id: str
    submission_id: str | None
    processed_tags: list[str]
    status: str


def inspect_candidates(
    session: Session,
    raw_article_ids: Iterable[str] = CONFIRMED_RAW_ARTICLE_IDS,
) -> list[RepairCandidate]:
    requested = list(dict.fromkeys(raw_article_ids))
    processed_by_id = {
        model.raw_article_id: model
        for model in session.scalars(
            select(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id.in_(requested)
            )
        )
    }
    overrides_by_id = {
        model.raw_article_id: model
        for model in session.scalars(
            select(EditorialOverrideModel).where(
                EditorialOverrideModel.raw_article_id.in_(requested)
            )
        )
    }
    submissions_by_id: dict[str, ArticleSubmissionModel] = {}
    submissions = session.scalars(
        select(ArticleSubmissionModel)
        .where(ArticleSubmissionModel.raw_article_id.in_(requested))
        .order_by(ArticleSubmissionModel.created_at.desc())
    )
    for submission in submissions:
        submissions_by_id.setdefault(str(submission.raw_article_id), submission)

    result = []
    for raw_article_id in requested:
        processed = processed_by_id.get(raw_article_id)
        override = overrides_by_id.get(raw_article_id)
        submission = submissions_by_id.get(raw_article_id)
        processed_tags = [
            str(tag) for tag in (processed.tags if processed is not None else []) or []
        ]
        if processed is None or override is None or submission is None:
            status = "unexpected_missing_record"
        elif override.tags is None:
            status = "already_repaired"
        elif override.tags != []:
            status = "unexpected_nonempty_override"
        elif not processed_tags:
            status = "unexpected_empty_ai_tags"
        elif (submission.field_provenance or {}).get("tags") != "ai":
            status = "unexpected_non_ai_provenance"
        elif (submission.manual_fields or {}).get("tags") not in (None, []):
            status = "unexpected_manual_tags"
        else:
            status = "eligible"
        result.append(
            RepairCandidate(
                raw_article_id=raw_article_id,
                submission_id=submission.id if submission is not None else None,
                processed_tags=processed_tags,
                status=status,
            )
        )
    return result


def apply_repairs(session: Session, candidates: Iterable[RepairCandidate]) -> int:
    eligible_ids = [
        candidate.raw_article_id
        for candidate in candidates
        if candidate.status == "eligible"
    ]
    if not eligible_ids:
        return 0
    overrides = session.scalars(
        select(EditorialOverrideModel).where(
            EditorialOverrideModel.raw_article_id.in_(eligible_ids)
        )
    )
    repaired = 0
    for override in overrides:
        if override.tags == []:
            override.tags = None
            repaired += 1
    session.flush()
    return repaired


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the repair; without this flag the command is read-only",
    )
    args = parser.parse_args()

    load_env_file(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")

    factory = build_session_factory(database_url)
    with factory() as session:
        before = inspect_candidates(session)
        unexpected = [
            candidate
            for candidate in before
            if candidate.status not in {"eligible", "already_repaired"}
        ]
        if args.apply and unexpected:
            session.rollback()
            print(
                json.dumps(
                    {
                        "mode": "apply",
                        "status": "aborted",
                        "unexpected": [asdict(item) for item in unexpected],
                        "items": [asdict(item) for item in before],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

        repaired = apply_repairs(session, before) if args.apply else 0
        if args.apply:
            session.commit()
        else:
            session.rollback()
        after = inspect_candidates(session)
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "status": "ok",
                    "eligible_before": sum(item.status == "eligible" for item in before),
                    "already_repaired_before": sum(
                        item.status == "already_repaired" for item in before
                    ),
                    "repaired": repaired,
                    "unexpected": len(unexpected),
                    "items": [asdict(item) for item in after],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
