"""add joined_at and reshape article_embeddings

Revision ID: 64b8cf211581
Revises: e2246d601abb
Create Date: 2026-07-11 02:38:00.000000

Hand-trimmed from autogenerate output: only article_embeddings (resized
to vector(512) to match the local bge-small-zh embedding model, plus a
source_hash column for skip-if-unchanged recompute, plus a unique index
on raw_article_id) and event_cluster_articles.joined_at (needed for the
sliding-window "how many sources in the last N hours" heat count). The
rest of the diff was the same cosmetic TEXT/JSONB-vs-String/JSON noise
already explained in the baseline revision. article_embeddings is empty
(dead table, no ORM model existed before this), so these are safe
in-place alters with no data to migrate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision: str = '64b8cf211581'
down_revision: Union[str, Sequence[str], None] = 'e2246d601abb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('article_embeddings', sa.Column('source_hash', sa.String(), nullable=False, server_default=''))
    op.alter_column('article_embeddings', 'source_hash', server_default=None)
    op.alter_column(
        'article_embeddings', 'content_vector',
        existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=1536),
        type_=pgvector.sqlalchemy.vector.VECTOR(dim=512),
        nullable=False,
    )
    op.create_index(
        op.f('ix_article_embeddings_raw_article_id'),
        'article_embeddings',
        ['raw_article_id'],
        unique=True,
    )
    op.add_column(
        'event_cluster_articles',
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('event_cluster_articles', 'joined_at')
    op.drop_index(op.f('ix_article_embeddings_raw_article_id'), table_name='article_embeddings')
    op.alter_column(
        'article_embeddings', 'content_vector',
        existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=512),
        type_=pgvector.sqlalchemy.vector.VECTOR(dim=1536),
        nullable=False,
    )
    op.drop_column('article_embeddings', 'source_hash')
