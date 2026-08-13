"""add ai_usage_stats token ledger

Revision ID: a1b6f3d90c47
Revises: c4d8e2a1f635
Create Date: 2026-08-13

Cost observability: providers previously discarded the `usage` block of every
response, so nothing recorded which stage of a refresh spent the tokens. This
table aggregates per (run, model, operation) - one row per operation per
refresh, not per API call. Token counts only, never a money amount: DeepSeek
switched to peak/off-peak pricing on 2026-08-16, so the same token count costs
a different amount depending on when it was spent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b6f3d90c47"
down_revision: Union[str, Sequence[str], None] = "c4d8e2a1f635"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_miss_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"], ["pipeline_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_stats_recorded_at", "ai_usage_stats", ["recorded_at"])
    op.create_index("ix_ai_usage_stats_operation", "ai_usage_stats", ["operation"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_stats_operation", table_name="ai_usage_stats")
    op.drop_index("ix_ai_usage_stats_recorded_at", table_name="ai_usage_stats")
    op.drop_table("ai_usage_stats")
