"""add article_translations

Revision ID: b71a84327b4d
Revises: ebf01725fe8c
Create Date: 2026-07-11 03:12:26.185540

Hand-trimmed from autogenerate output: only the new article_translations
table (the rest of the diff is the same cosmetic TEXT/JSONB-vs-String/JSON
noise already explained in the baseline revision).

Translation output used to live inside raw_articles.raw_metadata, mixed in
with genuine crawl-domain fields (original_paragraphs, README enrichment,
etc), requiring a hand-maintained key whitelist (CACHED_METADATA_KEYS /
_EVENT_CONTENT_METADATA_KEYS) to keep the two apart. This migration moves
it to its own table and backfills existing rows from raw_metadata, then
strips those keys out of raw_metadata so there is exactly one place each
piece of data lives.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b71a84327b4d'
down_revision: Union[str, Sequence[str], None] = 'ebf01725fe8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRANSLATION_METADATA_KEYS = (
    "translated_paragraphs",
    "translated_blocks",
    "translation_source_language",
    "translation_target_language",
    "translation_source_hash",
    "translation_status",
    "translation_error",
)


def upgrade() -> None:
    op.create_table(
        'article_translations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('raw_article_id', sa.String(), nullable=False),
        sa.Column('translated_paragraphs', sa.JSON(), nullable=False),
        sa.Column('translated_blocks', sa.JSON(), nullable=False),
        sa.Column('source_language', sa.String(), nullable=True),
        sa.Column('target_language', sa.String(), nullable=False),
        sa.Column('source_hash', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['raw_article_id'], ['raw_articles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_article_translations_raw_article_id'),
        'article_translations',
        ['raw_article_id'],
        unique=True,
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, raw_metadata FROM raw_articles WHERE raw_metadata ? 'translated_paragraphs'")
    ).fetchall()
    for raw_article_id, raw_metadata in rows:
        metadata = dict(raw_metadata or {})
        connection.execute(
            sa.text(
                "INSERT INTO article_translations "
                "(raw_article_id, translated_paragraphs, translated_blocks, source_language, "
                " target_language, source_hash, status, error) "
                "VALUES (:raw_article_id, CAST(:translated_paragraphs AS JSON), CAST(:translated_blocks AS JSON), "
                " :source_language, :target_language, :source_hash, :status, :error)"
            ),
            {
                "raw_article_id": raw_article_id,
                "translated_paragraphs": json.dumps(metadata.get("translated_paragraphs") or []),
                "translated_blocks": json.dumps(metadata.get("translated_blocks") or []),
                "source_language": metadata.get("translation_source_language"),
                "target_language": metadata.get("translation_target_language") or "zh",
                "source_hash": metadata.get("translation_source_hash") or "",
                "status": metadata.get("translation_status") or "completed",
                "error": metadata.get("translation_error"),
            },
        )
        for key in _TRANSLATION_METADATA_KEYS:
            metadata.pop(key, None)
        connection.execute(
            sa.text("UPDATE raw_articles SET raw_metadata = CAST(:metadata AS JSONB) WHERE id = :raw_article_id"),
            {"metadata": json.dumps(metadata), "raw_article_id": raw_article_id},
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT raw_article_id, translated_paragraphs, translated_blocks, source_language, "
            "target_language, source_hash, status, error FROM article_translations"
        )
    ).fetchall()
    for (
        raw_article_id,
        translated_paragraphs,
        translated_blocks,
        source_language,
        target_language,
        source_hash,
        status,
        error,
    ) in rows:
        patch = json.dumps(
            {
                "translated_paragraphs": translated_paragraphs,
                "translated_blocks": translated_blocks,
                "translation_source_language": source_language,
                "translation_target_language": target_language,
                "translation_source_hash": source_hash,
                "translation_status": status,
                "translation_error": error,
            }
        )
        connection.execute(
            sa.text(
                "UPDATE raw_articles SET raw_metadata = raw_metadata || CAST(:patch AS JSONB) "
                "WHERE id = :raw_article_id"
            ),
            {"raw_article_id": raw_article_id, "patch": patch},
        )
    op.drop_index(op.f('ix_article_translations_raw_article_id'), table_name='article_translations')
    op.drop_table('article_translations')
