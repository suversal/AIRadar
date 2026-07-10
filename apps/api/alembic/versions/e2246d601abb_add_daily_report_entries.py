"""add daily_report_entries

Revision ID: e2246d601abb
Revises: 254438b7a6b4
Create Date: 2026-07-11 02:23:57.883871

Hand-trimmed from autogenerate output: only the new table. The rest of
the diff was the same cosmetic TEXT/JSONB-vs-String/JSON noise and the
article_embeddings drop already explained in the baseline revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2246d601abb'
down_revision: Union[str, Sequence[str], None] = '254438b7a6b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'daily_report_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('raw_article_id', sa.String(), nullable=False),
        sa.Column('reason_snapshot', sa.Text(), nullable=False),
        sa.Column('score_at_selection', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['raw_article_id'], ['raw_articles.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_date', 'position', name='uq_daily_report_entries_date_position'),
    )
    op.create_index(
        op.f('ix_daily_report_entries_report_date'),
        'daily_report_entries',
        ['report_date'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_daily_report_entries_report_date'), table_name='daily_report_entries')
    op.drop_table('daily_report_entries')
