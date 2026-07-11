"""make similarity_score nullable, legacy zeros become NULL

Revision ID: c5e8f0a2d316
Revises: a7d51c3e9f24
Create Date: 2026-07-11 14:10:00.000000

similarity_score rows written before clustering evidence was captured all
hold 0.0 - which is indistinguishable from a real low score. NULL now means
"unknown"; the application writes real values (or NULL) going forward.

At migration time every 0.0 row is a legacy row: real clustering scores are
>= the 0.93 threshold, and bucket members always have embeddings, so a true
0.0 cannot have been produced by the current code.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5e8f0a2d316'
down_revision: Union[str, Sequence[str], None] = 'a7d51c3e9f24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'event_cluster_articles', 'similarity_score',
        existing_type=sa.Float(), nullable=True, existing_server_default=sa.text('0'),
    )
    op.alter_column('event_cluster_articles', 'similarity_score', server_default=None)
    op.execute("UPDATE event_cluster_articles SET similarity_score = NULL WHERE similarity_score = 0")


def downgrade() -> None:
    op.execute("UPDATE event_cluster_articles SET similarity_score = 0 WHERE similarity_score IS NULL")
    op.alter_column(
        'event_cluster_articles', 'similarity_score',
        existing_type=sa.Float(), nullable=False, server_default=sa.text('0'),
    )
