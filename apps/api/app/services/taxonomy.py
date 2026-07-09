"""Single source of truth for the user-facing category taxonomy.

Scoring keeps its 8 fine-grained categories (their thresholds differ), but
every user-facing surface filters and labels by the 5 display categories
below, matching the reference site's 全部/模型/产品/行业/论文/技巧 filters.
"""

from __future__ import annotations

DISPLAY_CATEGORIES: list[tuple[str, str]] = [
    ("model", "模型"),
    ("product", "产品"),
    ("industry", "行业"),
    ("research", "论文"),
    ("tutorial", "技巧"),
]

_DISPLAY_LABELS = dict(DISPLAY_CATEGORIES)

SCORING_TO_DISPLAY: dict[str, str] = {
    "model_release": "model",
    "product_release": "product",
    "open_source": "product",
    "industry": "industry",
    "funding": "industry",
    "research": "research",
    "opinion": "tutorial",
    "tutorial": "tutorial",
}

_FALLBACK_KEYWORDS: list[tuple[str, str]] = [
    ("model", "model"),
    ("research", "research"),
    ("paper", "research"),
    ("product", "product"),
    ("open_source", "product"),
    ("tutorial", "tutorial"),
    ("opinion", "tutorial"),
    ("funding", "industry"),
]

DEFAULT_DISPLAY_CATEGORY = "industry"


def display_category(scoring_category: str | None) -> str:
    """Map a scoring category (or provider free-form value) to a display key."""
    raw = str(scoring_category or "").strip().lower()
    if raw in _DISPLAY_LABELS:
        return raw
    if raw in SCORING_TO_DISPLAY:
        return SCORING_TO_DISPLAY[raw]
    # providers occasionally emit off-enum values like "research_insight"
    for keyword, display in _FALLBACK_KEYWORDS:
        if keyword in raw:
            return display
    return DEFAULT_DISPLAY_CATEGORY


def scoring_categories_for(display_key: str) -> list[str]:
    """Expand a display category into the scoring categories it covers."""
    matches = [
        scoring
        for scoring, display in SCORING_TO_DISPLAY.items()
        if display == display_key
    ]
    return matches or [display_key]


def category_label(category: str | None) -> str:
    return _DISPLAY_LABELS[display_category(category)]
