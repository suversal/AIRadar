"""add pipeline_runs phase and source_report

Revision ID: e1f7a9c8b432
Revises: f6a1c9d5e302
Create Date: 2026-07-11 18:05:00.000000

Sync monitoring: `phase` shows which stage a running refresh is in
(crawling/scoring/persisting/reports); `source_report` keeps the per-source
crawl outcome ({status, article_count, fetched_count, duration_ms, error})
so the admin dashboard can answer "how did each source actually do" per run
instead of only exposing the sources table's rolling EMA summary.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e1f7a9c8b432'
down_revision: Union[str, Sequence[str], None] = 'f6a1c9d5e302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pipeline_runs', sa.Column('phase', sa.String(), nullable=True))
    op.add_column('pipeline_runs', sa.Column('source_report', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('pipeline_runs', 'source_report')
    op.drop_column('pipeline_runs', 'phase')
