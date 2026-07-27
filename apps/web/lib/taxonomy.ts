// Mirrors apps/api/app/services/taxonomy.py. Existing report/display
// categories stay intact; only /latest, /all and /topics use reader focus.

export const DISPLAY_CATEGORIES = [
  ["model", "模型"],
  ["product", "产品"],
  ["industry", "行业"],
  ["research", "论文"],
  ["tutorial", "技巧"],
] as const;

export const FOCUS_CATEGORIES = [
  ["model", "模型动态"],
  ["product", "产品工具"],
  ["technology", "技术研究"],
  ["industry", "行业动态"],
  ["tutorial", "教程实践"],
] as const;

export const CATEGORY_FILTER_OPTIONS: readonly (readonly [string, string])[] = [
  ["", "全部"],
  ...DISPLAY_CATEGORIES,
];

export const FOCUS_FILTER_OPTIONS: readonly (readonly [string, string])[] = [
  ["", "全部"],
  ...FOCUS_CATEGORIES,
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

const SCORING_TO_FOCUS: Record<string, string> = {
  model_release: "model",
  product_release: "product",
  open_source: "product",
  research: "technology",
  industry: "industry",
  funding: "industry",
  opinion: "industry",
  tutorial: "tutorial",
};

const DISPLAY_FALLBACK_KEYWORDS: readonly (readonly [string, string])[] = [
  ["model", "model"],
  ["research", "research"],
  ["paper", "research"],
  ["academic", "research"],
  ["product", "product"],
  ["open_source", "product"],
  ["tool", "product"],
  ["framework", "product"],
  ["launch", "product"],
  ["release", "product"],
  ["tutorial", "tutorial"],
  ["opinion", "tutorial"],
  ["technique", "tutorial"],
  ["funding", "industry"],
];

const DISPLAY_LABELS = new Map<string, string>(DISPLAY_CATEGORIES);
const FOCUS_LABELS = new Map<string, string>(FOCUS_CATEGORIES);

export function displayCategory(category?: string | null): string {
  const raw = (category ?? "").trim().toLowerCase();
  if (DISPLAY_LABELS.has(raw)) {
    return raw;
  }
  if (raw in SCORING_TO_DISPLAY) {
    return SCORING_TO_DISPLAY[raw];
  }
  for (const [keyword, display] of DISPLAY_FALLBACK_KEYWORDS) {
    if (raw.includes(keyword)) {
      return display;
    }
  }
  return "industry";
}

export function focusCategory(
  focus?: string | null,
  scoringCategory?: string | null,
): string {
  const explicit = (focus ?? "").trim().toLowerCase();
  if (FOCUS_LABELS.has(explicit)) {
    return explicit;
  }
  const scoring = (scoringCategory ?? "").trim().toLowerCase();
  if (FOCUS_LABELS.has(scoring)) {
    return scoring;
  }
  if (scoring === "research") {
    return "technology";
  }
  return SCORING_TO_FOCUS[scoring] ?? "";
}

export function categoryLabel(category?: string | null): string {
  return DISPLAY_LABELS.get(displayCategory(category)) ?? "行业";
}

export function focusCategoryLabel(category?: string | null): string {
  return FOCUS_LABELS.get((category ?? "").trim().toLowerCase()) ?? "未分类";
}
