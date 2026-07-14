from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from app.models.domain import Source


TRUSTED_CURATED_POLICY = "trusted_curated"

# WeChat official-account article pages (mp.weixin.qq.com) and the m.qq.com
# mobile portal are known to sit behind an anti-crawler verification wall -
# any body fetched from these hosts is at best a thin meta description, at
# worst the verification page's own text mis-extracted as if it were real
# article content. Articles whose "阅读原文" target resolves to one of these
# hosts should link out only, the same as any other genuinely unscrapable
# source, rather than risk showing fabricated body text.
UNFETCHABLE_ARTICLE_DOMAINS = frozenset({
    "mp.weixin.qq.com",
    "m.qq.com",
})


def is_unfetchable_article_domain(url: str | None) -> bool:
    if not url:
        return False
    return urlparse(url).netloc.lower() in UNFETCHABLE_ARTICLE_DOMAINS

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
