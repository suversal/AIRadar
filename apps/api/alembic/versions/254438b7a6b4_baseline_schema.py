"""baseline schema

Revision ID: 254438b7a6b4
Revises:
Create Date: 2026-07-11 02:19:08.565142

Deliberately a no-op. This project's schema was hand-maintained via
infra/postgres/init.sql (and a few manual psql ALTER/CREATE statements)
before Alembic was adopted; autogenerate against that history produces
a wall of cosmetic diffs (TEXT vs String, JSONB vs JSON, BIGINT vs
Integer - all artifacts of hand-written DDL vs SQLAlchemy's generic
type conventions, not real changes) plus a spurious `DROP TABLE
article_embeddings` for a table that was created in init.sql but never
had an ORM model. None of that belongs in a baseline.

This revision exists only as the anchor everyone's DB gets `alembic
stamp head`ed to. Real schema changes from here on are proper
migrations layered on top - init.sql stays as the from-scratch bootstrap
for a brand new empty database, alembic owns every change after that.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '254438b7a6b4'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
