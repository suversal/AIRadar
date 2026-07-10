"""add editorial_overrides

Revision ID: ebf01725fe8c
Revises: 64b8cf211581
Create Date: 2026-07-11 03:05:36.964380

Hand-trimmed from autogenerate output: only the new editorial_overrides
table (the rest of the diff is the same cosmetic TEXT/JSONB-vs-String/JSON
noise already explained in the baseline revision).

Human moderation used to write hidden/title_zh/category/tags directly onto
processed_articles - AI-owned territory that a later pipeline run
re-scoring the same re-crawled article overwrites unconditionally, silently
undoing the moderation. This migration moves that signal into its own
table and, for the one case that's unambiguously a prior override
(status='hidden' - AI code never sets that value), backfills it and
restores processed_articles.status to what the AI would have set on its
own. Pre-existing manual title_zh/category/tags edits can't be losslessly
separated from AI-generated values after the fact (there was never a flag
distinguishing them), so those aren't backfilled; only hidden status,
which is unambiguous.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ebf01725fe8c'
down_revision: Union[str, Sequence[str], None] = '64b8cf211581'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'editorial_overrides',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('raw_article_id', sa.String(), nullable=False),
        sa.Column('hidden', sa.Boolean(), nullable=False),
        sa.Column('title_zh', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['raw_article_id'], ['raw_articles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_editorial_overrides_raw_article_id'),
        'editorial_overrides',
        ['raw_article_id'],
        unique=True,
    )

    connection = op.get_bind()
    hidden_rows = connection.execute(
        sa.text(
            "SELECT raw_article_id, rejection_reason FROM processed_articles WHERE status = 'hidden'"
        )
    ).fetchall()
    for raw_article_id, rejection_reason in hidden_rows:
        connection.execute(
            sa.text(
                "INSERT INTO editorial_overrides (raw_article_id, hidden, updated_at) "
                "VALUES (:raw_article_id, true, now())"
            ),
            {"raw_article_id": raw_article_id},
        )
        restored_status = "rejected" if rejection_reason else "processed"
        connection.execute(
            sa.text("UPDATE processed_articles SET status = :status WHERE raw_article_id = :raw_article_id"),
            {"status": restored_status, "raw_article_id": raw_article_id},
        )


def downgrade() -> None:
    connection = op.get_bind()
    overridden_hidden = connection.execute(
        sa.text("SELECT raw_article_id FROM editorial_overrides WHERE hidden = true")
    ).fetchall()
    for (raw_article_id,) in overridden_hidden:
        connection.execute(
            sa.text("UPDATE processed_articles SET status = 'hidden' WHERE raw_article_id = :raw_article_id"),
            {"raw_article_id": raw_article_id},
        )
    op.drop_index(op.f('ix_editorial_overrides_raw_article_id'), table_name='editorial_overrides')
    op.drop_table('editorial_overrides')
