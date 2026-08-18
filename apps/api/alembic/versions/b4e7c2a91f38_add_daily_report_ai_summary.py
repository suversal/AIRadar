"""add daily report AI mainline and per-category notes

The daily page gains the same kind of AI-written mainline the weekly/monthly
reports already have, plus one short note per focus category. Both are stored
on daily_reports rather than recomputed at read time, for the same reason the
period reports store theirs: the text is paid for with an AI call and must not
change on every page view.

summary_digest fingerprints the material the summary was written from, so a
pipeline run that did not change which events are in the report can skip the
call instead of re-buying the same paragraphs. The pipeline runs 12-14 times a
day, so this is the difference between ~6 and ~72 long-form calls per day.

Revision ID: b4e7c2a91f38
Revises: a1b6f3d90c47
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e7c2a91f38"
down_revision: Union[str, Sequence[str], None] = "a1b6f3d90c47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_reports",
        sa.Column("mainline_title", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "daily_reports",
        sa.Column("mainline_body", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "daily_reports",
        sa.Column(
            "category_notes",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    # pending: never attempted. generated: AI wrote it. skipped: no material
    # (a day with no multi-source event has no mainline, by design).
    op.add_column(
        "daily_reports",
        sa.Column("summary_status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "daily_reports",
        sa.Column("summary_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("daily_reports", sa.Column("summary_digest", sa.Text(), nullable=True))
    op.alter_column("daily_reports", "category_notes", server_default=None)


def downgrade() -> None:
    op.drop_column("daily_reports", "summary_digest")
    op.drop_column("daily_reports", "summary_generated_at")
    op.drop_column("daily_reports", "summary_status")
    op.drop_column("daily_reports", "category_notes")
    op.drop_column("daily_reports", "mainline_body")
    op.drop_column("daily_reports", "mainline_title")
