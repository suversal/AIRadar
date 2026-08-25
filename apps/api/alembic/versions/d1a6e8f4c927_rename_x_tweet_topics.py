"""rename SourcePilot X topic identifiers

SourcePilot renamed the three configured topic values. AIRADAR stores those
values both in the comma-wrapped filter column and in the mirrored JSON
payload, so both representations must move together.

Revision ID: d1a6e8f4c927
Revises: a4f8d2c6e910
Create Date: 2026-08-26
"""
from typing import Mapping, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1a6e8f4c927"
down_revision: Union[str, Sequence[str], None] = "a4f8d2c6e910"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TOPIC_RENAMES = {
    "ai-hot": "AI热点",
    "u-card": "U卡推荐",
    "esim": "eSIM推荐",
}


def _rename_topic_list(values: object, renames: Mapping[str, str]) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    renamed: list[str] = []
    for value in values:
        topic = renames.get(str(value), str(value)).strip()
        if topic and topic not in renamed:
            renamed.append(topic)
    return renamed


def _rename_topic_column(value: object, renames: Mapping[str, str]) -> str:
    topics = [topic for topic in str(value or "").split(",") if topic]
    renamed = _rename_topic_list(topics, renames)
    return f",{','.join(renamed)}," if renamed else ""


def _migrate_topics(renames: Mapping[str, str]) -> None:
    x_tweets = sa.table(
        "x_tweets",
        sa.column("tweet_id", sa.String()),
        sa.column("topics", sa.String()),
        sa.column("payload", sa.JSON()),
    )
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.select(x_tweets.c.tweet_id, x_tweets.c.topics, x_tweets.c.payload)
        ).mappings()
    )

    for row in rows:
        old_topics = row["topics"] or ""
        new_topics = _rename_topic_column(old_topics, renames)
        old_payload = row["payload"]
        new_payload = old_payload

        if isinstance(old_payload, dict) and isinstance(old_payload.get("topics"), list):
            renamed_payload_topics = _rename_topic_list(old_payload["topics"], renames)
            if renamed_payload_topics != old_payload["topics"]:
                new_payload = dict(old_payload)
                new_payload["topics"] = renamed_payload_topics

        values = {}
        if new_topics != old_topics:
            values["topics"] = new_topics
        if new_payload is not old_payload:
            values["payload"] = new_payload
        if values:
            connection.execute(
                x_tweets.update()
                .where(x_tweets.c.tweet_id == row["tweet_id"])
                .values(**values)
            )


def upgrade() -> None:
    _migrate_topics(TOPIC_RENAMES)


def downgrade() -> None:
    _migrate_topics({new: old for old, new in TOPIC_RENAMES.items()})
