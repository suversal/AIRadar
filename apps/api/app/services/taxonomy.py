"""Taxonomy helpers for the existing content type and new reader focus.

``category`` keeps the existing eight scoring enums and five legacy display
groups used by reports and older clients. ``focus_category`` is the one new
four-way axis used only by the 精选、动态、主题 browsing experience.
"""

from __future__ import annotations

DISPLAY_CATEGORIES: list[tuple[str, str]] = [
    ("model", "模型"),
    ("product", "产品"),
    ("industry", "行业"),
    ("research", "论文"),
    ("tutorial", "技巧"),
]

FOCUS_CATEGORIES: list[tuple[str, str]] = [
    ("model", "模型动态"),
    ("product", "产品工具"),
    ("technology", "技术研究"),
    ("industry", "行业动态"),
    ("tutorial", "教程实践"),
]

SOURCE_FILTER_KEYS = frozenset({"first_party", "news", "community"})
FIRST_PARTY_SOURCE_CATEGORIES = frozenset({"official", "research"})
COMMUNITY_SOURCE_CATEGORIES = frozenset({"community"})

_DISPLAY_LABELS = dict(DISPLAY_CATEGORIES)
_FOCUS_LABELS = dict(FOCUS_CATEGORIES)

SCORING_CATEGORY_LABELS: dict[str, str] = {
    "model_release": "模型进展",
    "product_release": "产品应用",
    "open_source": "开源项目",
    "research": "研究评测",
    "industry": "行业事件",
    "funding": "资本动态",
    "tutorial": "教程实践",
    "opinion": "观点分析",
}

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

# Compatibility map for rows created before focus_category existed. New rows
# carry an explicit focus and do not depend on these lossy defaults.
SCORING_TO_FOCUS: dict[str, str] = {
    "model_release": "model",
    "product_release": "product",
    "open_source": "product",
    "research": "technology",
    "industry": "industry",
    "funding": "industry",
    "opinion": "industry",
    "tutorial": "tutorial",
}

_DISPLAY_FALLBACK_KEYWORDS: list[tuple[str, str]] = [
    ("model", "model"),
    ("research", "research"),
    ("paper", "research"),
    ("academic", "research"),
    ("product", "product"),
    ("open_source", "product"),
    ("tool", "product"),
    ("framework", "product"),
    ("launch", "product"),
    ("release", "product"),
    ("tutorial", "tutorial"),
    ("opinion", "tutorial"),
    ("technique", "tutorial"),
    ("funding", "industry"),
]

_FOCUS_FALLBACK_KEYWORDS: list[tuple[str, str]] = [
    ("model", "model"),
    ("research", "technology"),
    ("paper", "technology"),
    ("academic", "technology"),
    ("benchmark", "technology"),
    ("technique", "technology"),
    ("tutorial", "tutorial"),
    ("product", "product"),
    ("open_source", "product"),
    ("tool", "product"),
    ("framework", "product"),
    ("launch", "product"),
    ("release", "product"),
    ("funding", "industry"),
    ("policy", "industry"),
    ("regulation", "industry"),
    ("opinion", "industry"),
]

_MODEL_SIGNALS = (
    "model",
    "models",
    "llm",
    "模型",
    "权重",
    "参数",
    "checkpoint",
    "gpt",
    "claude",
    "gemini",
    "llama",
    "deepseek",
    "qwen",
    "mistral",
    "grok",
)
_PRODUCT_SIGNALS = (
    "product",
    "app",
    "tool",
    "platform",
    "assistant",
    "copilot",
    "cursor",
    "chatgpt",
    "claude code",
    "产品",
    "应用",
    "工具",
    "平台",
    "助手",
)
_TECHNOLOGY_SIGNALS = (
    "paper",
    "research",
    "benchmark",
    "dataset",
    "method",
    "algorithm",
    "training",
    "evaluation",
    "论文",
    "研究",
    "评测",
    "数据集",
    "方法",
    "算法",
    "训练",
    "微调",
)


def _valid_focus(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    return raw if raw in _FOCUS_LABELS else None


def infer_focus_category(
    scoring_category: str | None,
    *,
    text: str = "",
) -> str | None:
    """Best-effort compatibility inference for legacy or fallback rows."""
    raw = str(scoring_category or "").strip().lower()
    direct = _valid_focus(raw)
    if direct:
        return direct

    normalized_text = str(text or "").lower()
    if raw == "opinion":
        if any(signal in normalized_text for signal in _PRODUCT_SIGNALS):
            return "product"
        if any(signal in normalized_text for signal in _MODEL_SIGNALS):
            return "model"
        if any(signal in normalized_text for signal in _TECHNOLOGY_SIGNALS):
            return "technology"
        return SCORING_TO_FOCUS[raw]

    if raw == "open_source":
        if any(signal in normalized_text for signal in _MODEL_SIGNALS):
            return "model"
        if any(signal in normalized_text for signal in _PRODUCT_SIGNALS):
            return "product"
        if any(signal in normalized_text for signal in _TECHNOLOGY_SIGNALS):
            return "technology"
        return SCORING_TO_FOCUS[raw]

    mapped = SCORING_TO_FOCUS.get(raw)
    if mapped:
        return mapped
    for keyword, focus in _FOCUS_FALLBACK_KEYWORDS:
        if keyword in raw:
            return focus
    return None


def resolve_focus_category(
    focus_category: str | None,
    scoring_category: str | None = None,
    *,
    text: str = "",
) -> str | None:
    """Prefer the persisted focus and infer only when it is absent/invalid."""
    return _valid_focus(focus_category) or infer_focus_category(
        scoring_category,
        text=text,
    )


def focus_category_label(category: str | None) -> str:
    focus = _valid_focus(category)
    return _FOCUS_LABELS.get(focus, "未分类")


def scoring_categories_for_focus(focus_key: str) -> list[str]:
    """Expand a focus into legacy categories for rows not yet backfilled."""
    normalized = _valid_focus(focus_key)
    if normalized is None:
        return []
    return [
        scoring
        for scoring, focus in SCORING_TO_FOCUS.items()
        if focus == normalized
    ]


def display_category(scoring_category: str | None) -> str:
    """Map a scoring category (or provider free-form value) to old display."""
    raw = str(scoring_category or "").strip().lower()
    if raw in _DISPLAY_LABELS:
        return raw
    if raw in SCORING_TO_DISPLAY:
        return SCORING_TO_DISPLAY[raw]
    for keyword, display in _DISPLAY_FALLBACK_KEYWORDS:
        if keyword in raw:
            return display
    return "industry"


def scoring_categories_for(display_key: str) -> list[str]:
    """Expand a legacy display category into scoring categories."""
    matches = [
        scoring
        for scoring, display in SCORING_TO_DISPLAY.items()
        if display == display_key
    ]
    return matches or [display_key]


def category_label(category: str | None) -> str:
    return _DISPLAY_LABELS[display_category(category)]


def scoring_category_label(category: str | None) -> str:
    raw = str(category or "").strip().lower()
    return SCORING_CATEGORY_LABELS.get(raw, raw or "未分类")


def source_filter_bucket(source_category: str | None) -> str:
    """Map source-registry categories to the three /all reader buckets."""
    raw = str(source_category or "").strip().lower()
    if raw in FIRST_PARTY_SOURCE_CATEGORIES:
        return "first_party"
    if raw in COMMUNITY_SOURCE_CATEGORIES:
        return "community"
    return "news"
