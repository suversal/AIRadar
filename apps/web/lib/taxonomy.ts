// Mirror of apps/api/app/services/taxonomy.py — the single user-facing
// category standard (全部/模型/产品/行业/论文/技巧). Backend payloads already
// emit display keys in `category`; this module exists for filter options and
// for mapping any legacy scoring keys that survive in older payloads.

export const DISPLAY_CATEGORIES = [
  ["model", "模型"],
  ["product", "产品"],
  ["industry", "行业"],
  ["research", "论文"],
  ["tutorial", "技巧"],
] as const;

export const CATEGORY_FILTER_OPTIONS: readonly (readonly [string, string])[] = [
  ["", "全部"],
  ...DISPLAY_CATEGORIES,
];

const SCORING_TO_DISPLAY: Record<string, string> = {
  model_release: "model",
  product_release: "product",
  open_source: "product",
  industry: "industry",
  funding: "industry",
  research: "research",
  opinion: "tutorial",
  tutorial: "tutorial",
};

const DISPLAY_LABELS = new Map<string, string>(DISPLAY_CATEGORIES);

export function displayCategory(category?: string | null): string {
  const raw = (category ?? "").trim().toLowerCase();
  if (DISPLAY_LABELS.has(raw)) {
    return raw;
  }
  if (raw in SCORING_TO_DISPLAY) {
    return SCORING_TO_DISPLAY[raw];
  }
  return "industry";
}

export function categoryLabel(category?: string | null): string {
  return DISPLAY_LABELS.get(displayCategory(category)) ?? "行业";
}
