// MCP 工具返回的文本格式化。
//
// 只返回 text content，不返回 structuredContent：后者要配 outputSchema
// 才符合规范，而 outputSchema 一旦声明就成了必须严格匹配的合同。对 Agent
// 来说，一段带链接的中文列表已经完全够用——它要的是"能不能引用"，不是
// "能不能反序列化"。

import type { V1Item } from "@/lib/v1/shape";

/** 北京时间。Agent 转述给中文用户时不该出现 UTC 时间戳。 */
export function beijingTime(iso: string | null): string {
  if (!iso) return "时间未知";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function itemLines(item: V1Item, index: number): string {
  const lines = [`${index + 1}. ${item.title}`];
  const summary = item.oneLineSummary ?? item.summary;
  if (summary) {
    lines.push(`   ${summary}`);
  }
  if (item.reason) {
    lines.push(`   为什么值得看：${item.reason}`);
  }

  const meta = [item.source.name];
  if (item.sourceCount > 1) meta.push(`${item.sourceCount} 家报道`);
  meta.push(item.categoryLabel);
  // 只在明确标注时下断言，其余只报时间。
  //
  // 两个方向都试过，都不对：兜底成"发布于"会对个别只有收录时刻的条目
  // （GitHub Trending 那类）撒谎；给每条都加"未标注是发布还是收录"又是另一种
  // 误导——实测 200 条样本里 98% 的 publishedAt 明显早于抓取时刻，确实是原文
  // 发布时间，逐条免责只会让 Agent 的回答啰嗦且低估数据质量。
  // 不加限定词地报时间，既没撒谎也不啰嗦。
  const when = beijingTime(item.publishedAt);
  meta.push(item.timeBasis === "discovered" ? `收录于 ${when}` : when);
  lines.push(`   ${meta.join(" · ")}`);

  lines.push(`   阅读页：${item.links.radar}`);
  if (item.links.original) {
    lines.push(`   第三方原文：${item.links.original}`);
  }
  // 事件 ID 要露出来，否则 Agent 想接着查时间线只能猜
  lines.push(`   事件 ID：${item.id}`);
  return lines.join("\n");
}

export function formatItems(
  heading: string,
  items: V1Item[],
  emptyHint: string,
): string {
  if (items.length === 0) {
    return `${heading}\n\n${emptyHint}`;
  }
  return `${heading}\n\n${items.map(itemLines).join("\n\n")}`;
}

/** 每次工具返回都带上的引用边界。 */
export const ATTRIBUTION_NOTE = [
  "",
  "---",
  "标题与摘要由 AI 基于第三方报道生成，只能当线索。引用具体数字、政策原文或当事人原话前，请打开第三方原文核对。",
].join("\n");
