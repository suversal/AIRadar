from __future__ import annotations

from app.models.domain import Source


TRUSTED_CURATED_POLICY = "trusted_curated"


def is_trusted_curated_source(source: Source) -> bool:
    return str((source.config or {}).get("selection_policy") or "") == TRUSTED_CURATED_POLICY
