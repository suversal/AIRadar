import type { DailyReport, LatestEvent } from "@/lib/api";
import { focusCategory } from "@/lib/taxonomy";

export type DailySection = {
  key: string;
  label: string;
  items: LatestEvent[];
};

function categoryLabel(key: string, items: LatestEvent[]) {
  return items[0]?.focus_category_label ?? items[0]?.category_label ?? key;
}

export function getDailySections(report: DailyReport): DailySection[] {
  const explicitSections = Object.entries(report.sections ?? {}).filter(([, items]) => items.length > 0);
  if (explicitSections.length > 0) {
    return explicitSections.map(([key, items]) => ({
      key,
      label: categoryLabel(key, items),
      items,
    }));
  }

  const grouped = new Map<string, LatestEvent[]>();
  for (const item of report.items) {
    const key = focusCategory(item.focus_category, item.scoring_category) || "uncategorized";
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }
  return Array.from(grouped.entries()).map(([key, items]) => ({
    key,
    label: categoryLabel(key, items),
    items,
  }));
}

