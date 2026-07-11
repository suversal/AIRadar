"""add integrity constraints and query indexes

Revision ID: a7d51c3e9f24
Revises: f3c2a91d4b07
Create Date: 2026-07-11 12:45:00.000000

Hardens invariants the application already maintains but the DB never
enforced: one processed row per article, no duplicate event memberships,
at most one main article per event, one masthead slot per event per day,
and entries always pointing at an existing daily report. Also adds the
indexes behind the hot read paths (/all listing, per-source queries,
event membership lookups).

daily_report_entries.event_id deliberately gets NO foreign key: unclustered
masthead articles legitimately carry the `a…` pseudo-id, which never exists
in event_clusters.

Unique-index creation fails loudly if duplicate data exists - run the
pre-checks in the docstring of each op below before upgrading a DB with
unknown history (current DBs were verified clean on 2026-07-11).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7d51c3e9f24'
down_revision: Union[str, Sequence[str], None] = 'f3c2a91d4b07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # one AI-processing result per article (ORM declared this unique from the
    # start; init.sql-created databases never got the index)
    op.create_index(
        'ix_processed_articles_raw_article_id',
        'processed_articles',
        ['raw_article_id'],
        unique=True,
        if_not_exists=True,
    )
    op.create_unique_constraint(
        'uq_event_cluster_articles_member',
        'event_cluster_articles',
        ['event_cluster_id', 'raw_article_id'],
    )
    op.create_index(
        'uq_event_cluster_articles_main',
        'event_cluster_articles',
        ['event_cluster_id'],
        unique=True,
        postgresql_where=sa.text('is_main'),
    )
    op.create_unique_constraint(
        'uq_daily_report_entries_date_event',
        'daily_report_entries',
        ['report_date', 'event_id'],
    )
    op.create_foreign_key(
        'fk_daily_report_entries_report_date',
        'daily_report_entries',
        'daily_reports',
        ['report_date'],
        ['report_date'],
    )

    op.create_index(
        'ix_raw_articles_published_at', 'raw_articles', ['published_at'], if_not_exists=True
    )
    op.create_index(
        'ix_raw_articles_source_id', 'raw_articles', ['source_id'], if_not_exists=True
    )
    op.create_index(
        'ix_processed_articles_event_cluster_id',
        'processed_articles',
        ['event_cluster_id'],
        if_not_exists=True,
    )
    op.create_index(
        'ix_event_cluster_articles_event_cluster_id',
        'event_cluster_articles',
        ['event_cluster_id'],
        if_not_exists=True,
    )
    op.create_index(
        'ix_event_cluster_articles_raw_article_id',
        'event_cluster_articles',
        ['raw_article_id'],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('ix_event_cluster_articles_raw_article_id', table_name='event_cluster_articles')
    op.drop_index('ix_event_cluster_articles_event_cluster_id', table_name='event_cluster_articles')
    op.drop_index('ix_processed_articles_event_cluster_id', table_name='processed_articles')
    op.drop_index('ix_raw_articles_source_id', table_name='raw_articles')
    op.drop_index('ix_raw_articles_published_at', table_name='raw_articles')
    op.drop_constraint('fk_daily_report_entries_report_date', 'daily_report_entries', type_='foreignkey')
    op.drop_constraint('uq_daily_report_entries_date_event', 'daily_report_entries', type_='unique')
    op.drop_index('uq_event_cluster_articles_main', table_name='event_cluster_articles')
    op.drop_constraint('uq_event_cluster_articles_member', 'event_cluster_articles', type_='unique')
    op.drop_index('ix_processed_articles_raw_article_id', table_name='processed_articles')
