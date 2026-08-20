// RSS 2.0 生成。
//
// 只出摘要，不内联正文：内联第三方原文等于替信源做再分发，我们没有拿到
// 那份授权。参照站点靠一张"允许再分发"的信源白名单来出全文 feed，我们
// 目前没有这份名单，与其出一个边界不清的全文 feed，不如只给摘要 + 两个
// 入口（站内阅读页、第三方原文）。有了白名单再加 /feed/full.xml 也不迟。

import type { V1Item } from "@/lib/v1/shape";
import { siteUrl } from "@/lib/site";

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** RSS 2.0 要求 RFC 822 日期。toUTCString() 正好是这个格式。 */
function rfc822(iso: string | null): string | null {
  if (!iso) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toUTCString();
}

function absolute(path: string): string {
  return new URL(path, siteUrl).toString();
}

export type FeedChannel = {
  /** 频道标题，会显示在阅读器的订阅列表里 */
  title: string;
  description: string;
  /** 这个 feed 自己的地址，用于 atom:link rel=self */
  selfPath: string;
  /** 阅读器点频道名跳转的站内页面 */
  sitePath: string;
};

/**
 * 摘要正文。
 *
 * 阅读器只渲染 description，所以推荐理由和原文入口必须写进去——否则
 * 订阅者看到的只有一句标题，还得点两次才知道这条为什么值得看。
 */
function describe(item: V1Item): string {
  const parts: string[] = [];
  const summary = item.summary ?? item.oneLineSummary;
  if (summary) {
    parts.push(`<p>${escapeXml(summary)}</p>`);
  }
  if (item.reason) {
    parts.push(`<p><strong>为什么值得看：</strong>${escapeXml(item.reason)}</p>`);
  }
  const meta: string[] = [`来源：${escapeXml(item.source.name)}`];
  if (item.sourceCount > 1) {
    meta.push(`${item.sourceCount} 家报道`);
  }
  // 只在明确标注时提示。给每条都加"未标注"是噪音：实测绝大多数条目的
  // publishedAt 就是原文发布时间。
  if (item.timeBasis === "discovered") {
    meta.push("时间为收录时间");
  }
  parts.push(`<p>${meta.join(" · ")}</p>`);
  if (item.links.original) {
    parts.push(`<p><a href="${escapeXml(item.links.original)}">阅读第三方原文</a></p>`);
  }
  return parts.join("\n");
}

export function renderItemsFeed(channel: FeedChannel, items: V1Item[]): string {
  // lastBuildDate 取最新条目的时间而不是 now：用 now 的话每次生成都不同，
  // ETag 永远变，订阅者的条件请求全部落空。
  const lastBuild = rfc822(items[0]?.publishedAt ?? null);

  const entries = items
    .map((item) => {
      const pubDate = rfc822(item.publishedAt);
      const lines = [
        `      <title>${escapeXml(item.title)}</title>`,
        // link 指向站内阅读页，第三方原文放在 description 里——订阅者
        // 先看到我们的摘要与理由，再决定要不要跳出去。
        `      <link>${escapeXml(item.links.radar)}</link>`,
        // isPermaLink=false：guid 是事件 ID 不是 URL。站内地址若改版，
        // 用 URL 当 guid 会让阅读器把全部旧条目当成新的重推一遍。
        `      <guid isPermaLink="false">${escapeXml(item.id)}</guid>`,
        `      <description><![CDATA[${describe(item)}]]></description>`,
        `      <category>${escapeXml(item.categoryLabel)}</category>`,
      ];
      if (pubDate) {
        lines.push(`      <pubDate>${pubDate}</pubDate>`);
      }
      return `    <item>\n${lines.join("\n")}\n    </item>`;
    })
    .join("\n");

  return renderChannel(channel, lastBuild, entries);
}

export function renderChannel(
  channel: FeedChannel,
  lastBuild: string | null,
  entries: string,
): string {
  const head = [
    `    <title>${escapeXml(channel.title)}</title>`,
    `    <link>${escapeXml(absolute(channel.sitePath))}</link>`,
    `    <description>${escapeXml(channel.description)}</description>`,
    `    <language>zh-cn</language>`,
    // 30 分钟是建议轮询间隔；共享缓存的 TTL 才是真正的新鲜度上限。
    `    <ttl>30</ttl>`,
    `    <atom:link href="${escapeXml(absolute(channel.selfPath))}" rel="self" type="application/rss+xml" />`,
  ];
  if (lastBuild) {
    head.push(`    <lastBuildDate>${lastBuild}</lastBuildDate>`);
  }

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
${head.join("\n")}
${entries}
  </channel>
</rss>
`;
}

export { escapeXml, rfc822, absolute };
