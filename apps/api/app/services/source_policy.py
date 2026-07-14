from __future__ import annotations

from typing import Literal

from app.models.domain import Source


TRUSTED_CURATED_POLICY = "trusted_curated"

# separate from TRUSTED_CURATED_POLICY on purpose: that one only controls
# whether the AI-relevance prefilter call runs (source.config
# "selection_policy"); this one controls the later, independent question of
# whether the final selected/精选 flag is forced regardless of score - e.g.
# AI HOT's "全部动态" feed should skip prefilter (already AI-curated
# upstream) but must never be force-selected, while its "每日精选" sibling
# skips prefilter AND should always be force-selected
FORCE_SELECTION_ALWAYS: Literal["always"] = "always"
FORCE_SELECTION_NEVER: Literal["never"] = "never"


def is_trusted_curated_source(source: Source) -> bool:
    return str((source.config or {}).get("selection_policy") or "") == TRUSTED_CURATED_POLICY


def forced_selection(source: Source) -> str | None:
    value = str((source.config or {}).get("force_selection") or "").strip().lower()
    return value if value in (FORCE_SELECTION_ALWAYS, FORCE_SELECTION_NEVER) else None
