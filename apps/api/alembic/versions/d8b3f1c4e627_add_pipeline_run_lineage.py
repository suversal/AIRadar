"""add pipeline_run_id lineage to derived tables

Revision ID: d8b3f1c4e627
Revises: c5e8f0a2d316
Create Date: 2026-07-11 14:20:00.000000

Every AI-derived row should be able to answer "which run generated me".
Nullable on purpose: historical rows have no trustworthy run attribution
and stay NULL; the CLI path may also persist without a pre-created run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8b3f1c4e627'
down_revision: Union[str, Sequence[str], None] = 'c5e8f0a2d316'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    'processed_articles',
    'article_embeddings',
    'article_translations',
    'daily_reports',
    'period_reports',
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column('pipeline_run_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            f'fk_{table}_pipeline_run_id', table, 'pipeline_runs',
            ['pipeline_run_id'], ['id'],
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_constraint(f'fk_{table}_pipeline_run_id', table, type_='foreignkey')
        op.drop_column(table, 'pipeline_run_id')
