import type { DailyReport, LatestEvent } from "@/lib/api";

export type DailySection = {
  key: string;
  label: string;
  items: LatestEvent[];
};

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "未评分";
  }
  return score.toFixed(1);
}

function categoryLabel(key: string, items: LatestEvent[]) {
  return items[0]?.category_label ?? items[0]?.category ?? key;
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
    const key = item.category ?? "uncategorized";
    grouped.set(key, [...(grouped.get(key) ?? []), item]);
  }
  return Array.from(grouped.entries()).map(([key, items]) => ({
    key,
    label: categoryLabel(key, items),
    items,
  }));
}

function sourceText(item: LatestEvent) {
  if (!item.main_source) {
    return `来源：相关来源 ${item.source_count ?? 1} 个`;
  }
  return `来源：[${item.main_source.name}](${item.main_source.url})，${item.main_source.tier}，相关来源 ${
    item.source_count ?? 1
  } 个`;
}

export function buildDailyMarkdown(report: DailyReport) {
  const lines = [`# ${report.title}`, "", `> ${report.summary}`, ""];

  for (const section of getDailySections(report)) {
    lines.push(`## ${section.label}`, "");
    section.items.forEach((item, index) => {
      const tags = (item.tags ?? []).map((tag) => `\`${tag}\``).join(" ");
      lines.push(
        `### ${index + 1}. ${item.title} (${formatScore(item.final_score)})`,
        "",
        `- 摘要：${item.one_line_summary ?? item.summary ?? "暂无摘要。"}`,
        `- 核心总结：${item.summary ?? item.one_line_summary ?? "暂无核心总结。"}`,
        `- 为什么重要：${item.reason ?? "暂无推荐理由。"}`,
        `- 下一步：${item.action ?? "阅读原文并评估是否跟进。"}`,
        `- ${sourceText(item)}`,
        `- 标签：${tags || "无"}`,
        "",
      );
    });
  }

  return `${lines.join("\n").trim()}\n`;
}
