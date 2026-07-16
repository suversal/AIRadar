"""add manual article submissions

Revision ID: 0d4a8c2f7b91
Revises: f9b2c4d6e817
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0d4a8c2f7b91"
down_revision: Union[str, Sequence[str], None] = "f9b2c4d6e817"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("editorial_overrides", sa.Column("one_line_summary", sa.Text(), nullable=True))
    op.add_column("editorial_overrides", sa.Column("summary_zh", sa.Text(), nullable=True))
    op.create_table(
        "article_submissions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("publication_status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("processing_status", sa.String(), nullable=False, server_default="idle"),
        sa.Column("processing_stage", sa.String(), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("canonical_url_hash", sa.String(), nullable=True),
        sa.Column("editor_document", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("editor_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("manual_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("extracted_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ai_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("field_provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("selection_mode", sa.String(), nullable=False, server_default="auto"),
        sa.Column("raw_article_id", sa.String(), nullable=True),
        sa.Column("last_error_code", sa.String(), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["raw_article_id"], ["raw_articles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_article_submissions_idempotency_key", "article_submissions", ["idempotency_key"])
    op.create_index("ix_article_submissions_canonical_url_hash", "article_submissions", ["canonical_url_hash"])
    op.create_index("ix_article_submissions_raw_article_id", "article_submissions", ["raw_article_id"])


def downgrade() -> None:
    op.drop_index("ix_article_submissions_raw_article_id", table_name="article_submissions")
    op.drop_index("ix_article_submissions_canonical_url_hash", table_name="article_submissions")
    op.drop_index("ix_article_submissions_idempotency_key", table_name="article_submissions")
    op.drop_table("article_submissions")
    op.drop_column("editorial_overrides", "summary_zh")
    op.drop_column("editorial_overrides", "one_line_summary")
