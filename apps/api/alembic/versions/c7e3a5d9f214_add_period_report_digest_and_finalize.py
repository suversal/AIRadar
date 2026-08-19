"""add period report summary digest and finalization

Two columns with one shared goal: stop the weekly/monthly mainline text from
being rewritten a dozen times a day.

summary_digest is the same mechanism daily_reports gained in b4e7c2a91f38:
a fingerprint of exactly what the AI was shown. A pipeline run whose top-N
input is unchanged reuses the stored text instead of re-buying it - measured
2026-08-18, summarize_period was called 23 times in one day against
summarize_daily's 6, all for a page whose material barely moved.

finalized_at is the stronger guarantee digest alone cannot give: once a
period has rolled over and its closing pass succeeded, the report is frozen
outright - no later run may rewrite its text or its entries/stats snapshot.
NULL means the period is still live (or its closing pass has not succeeded
yet). Existing rows all start NULL: history stays untouched by refresh
anyway, and the backfill script decides their finalization explicitly.

Revision ID: c7e3a5d9f214
Revises: b4e7c2a91f38
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e3a5d9f214"
down_revision: Union[str, Sequence[str], None] = "b4e7c2a91f38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "period_reports",
        sa.Column("summary_digest", sa.String(), nullable=True),
    )
    op.add_column(
        "period_reports",
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("period_reports", "finalized_at")
    op.drop_column("period_reports", "summary_digest")
