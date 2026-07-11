"""add event_editorial_overrides

Revision ID: f3c2a91d4b07
Revises: ebf01725fe8c
Create Date: 2026-07-11 12:36:00.000000

Article-level editorial_overrides bind a moderation decision to whichever
raw article happened to be the event's main article at the time. A later
cross-day merge can hand the main slot to a different article, silently
detaching the human title/category/tags/hidden from the event the editor
actually moderated. This table keys those decisions to the event itself.

No backfill: editorial_overrides holds zero rows at migration time, and
article-level rows can't be attributed to an event intent after the fact
anyway. Article-level overrides remain the storage for standalone
(unclustered) articles.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3c2a91d4b07'
down_revision: Union[str, Sequence[str], None] = 'ebf01725fe8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'event_editorial_overrides',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_cluster_id', sa.String(), nullable=False),
        sa.Column('hidden', sa.Boolean(), nullable=False),
        sa.Column('title_zh', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_cluster_id'], ['event_clusters.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_event_editorial_overrides_event_cluster_id'),
        'event_editorial_overrides',
        ['event_cluster_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_event_editorial_overrides_event_cluster_id'),
        table_name='event_editorial_overrides',
    )
    op.drop_table('event_editorial_overrides')
