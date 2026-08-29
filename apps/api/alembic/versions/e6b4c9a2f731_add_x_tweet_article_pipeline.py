"""add X tweet article-pipeline eligibility

Revision ID: e6b4c9a2f731
Revises: d1a6e8f4c927
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6b4c9a2f731"
down_revision: Union[str, Sequence[str], None] = "d1a6e8f4c927"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "x_tweets",
        sa.Column(
            "article_pipeline_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "x_tweets",
        sa.Column("article_pipeline_source_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_x_tweets_article_pipeline_eligible",
        "x_tweets",
        ["article_pipeline_eligible"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_x_tweets_article_pipeline_eligible", table_name="x_tweets")
    op.drop_column("x_tweets", "article_pipeline_source_id")
    op.drop_column("x_tweets", "article_pipeline_eligible")
