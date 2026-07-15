"""add persistent event-cluster redirects and unique membership

Revision ID: f9b2c4d6e817
Revises: e7c4a9d2b681
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9b2c4d6e817"
down_revision: Union[str, Sequence[str], None] = "e7c4a9d2b681"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_cluster_redirects",
        sa.Column("source_event_id", sa.String(), nullable=False),
        sa.Column("target_event_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["target_event_id"], ["event_clusters.id"]),
        sa.PrimaryKeyConstraint("source_event_id"),
    )
    op.create_index(
        "ix_event_cluster_redirects_target_event_id",
        "event_cluster_redirects",
        ["target_event_id"],
    )
    op.create_unique_constraint(
        "uq_event_cluster_articles_raw_article",
        "event_cluster_articles",
        ["raw_article_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_event_cluster_articles_raw_article",
        "event_cluster_articles",
        type_="unique",
    )
    op.drop_index(
        "ix_event_cluster_redirects_target_event_id",
        table_name="event_cluster_redirects",
    )
    op.drop_table("event_cluster_redirects")
