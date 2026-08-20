import type { DailyReport } from "@/lib/api";
import { FEED_CONTENT_TYPE } from "@/lib/feed/load";
import { absolute, escapeXml, renderChannel, rfc822 } from "@/lib/feed/rss";
import { dailyCacheTier } from "@/lib/v1/daily";
import { CACHE, conditionalText } from "@/lib/v1/http";
import { fetchUpstream } from "@/lib/v1/upstream";

/**
 * 保留最近 10 期而不是 30 期。
 *
 * 上游没有"只要日报头部"的轻量端点，每期都得整份拉下来（含 50 条正文
 * 摘要），30 期是几 MB 的内网流量换一个订阅者根本不会往下翻的归档。
 * 需要更早的期次请走 /api/v1/dailies 或站内 /daily。
 */
const KEEP_ISSUES = 10;

/**
 * 一期日报的时间戳。
 *
 * 用 generated_at（这一期实际写成的时刻），不要按期次日期编一个固定钟点：
 * 本站没有定时发布，调度是按 interval_minutes 轮询的，实测各期落在
 * 北京时间 16:24 / 22:05 / 23:51 / 19:31——盖一个"每天 08:00"的戳，
 * 等于给每个订阅者的时间线注入假数据。
 *
 * 代价是当天那一期在滚动更新时 ETag 会变，但那本来就该变：内容确实变了。
 * 拿不到时间就不输出 pubDate——RSS 允许缺省，编一个不允许。
 */
function issuedAt(report: DailyReport): string | null {
  return report.generated_at ?? report.updated_at ?? null;
}

function describe(report: DailyReport): string {
  const parts: string[] = [];
  // summary_status 只有 generated 才是 AI 真写出来的，其余取值下
  // mainline_* 是空串，渲染出来就是一个空标题挂在那。
  if (report.summary_status === "generated" && report.mainline_title) {
    parts.push(`<h3>${escapeXml(report.mainline_title)}</h3>`);
    if (report.mainline_body) {
      parts.push(`<p>${escapeXml(report.mainline_body)}</p>`);
    }
  } else if (report.summary) {
    parts.push(`<p>${escapeXml(report.summary)}</p>`);
  }
  for (const note of report.category_notes ?? []) {
    if (note.note) {
      parts.push(`<p><strong>${escapeXml(note.label)}：</strong>${escapeXml(note.note)}</p>`);
    }
  }
  parts.push(`<p>共 ${report.article_count ?? 0} 条。</p>`);
  return parts.join("\n");
}

export async function GET(request: Request) {
  try {
    const archive = await fetchUpstream<{ dates?: string[] }>(
      "/api/public/reports/daily/archive",
      { revalidate: CACHE.dailyIndex },
    );
    const dates = (archive.dates ?? []).slice(0, KEEP_ISSUES);

    const reports = await Promise.all(
      dates.map((date) =>
        fetchUpstream<DailyReport>(`/api/public/daily/${date}`, {
          // 历史期次封版后不变，长缓存；当天那一期仍在滚动，走短档。
          revalidate: dailyCacheTier(date),
        }).catch(() => null),
      ),
    );

    const usable = reports.filter(
      (report): report is DailyReport => report !== null && (report.article_count ?? 0) > 0,
    );

    const entries = usable
      .map((report) => {
        const link = absolute(`/daily?date=${report.report_date}`);
        const pubDate = rfc822(issuedAt(report));
        const lines = [
          `      <title>${escapeXml(report.title)}</title>`,
          `      <link>${escapeXml(link)}</link>`,
          `      <guid isPermaLink="false">daily-${escapeXml(report.report_date)}</guid>`,
          `      <description><![CDATA[${describe(report)}]]></description>`,
        ];
        if (pubDate) {
          lines.push(`      <pubDate>${pubDate}</pubDate>`);
        }
        return `    <item>\n${lines.join("\n")}\n    </item>`;
      })
      .join("\n");

    const body = renderChannel(
      {
        title: "AI·RADAR 日报",
        description: "每天一期的 AI 精编日报，含 AI 主线综述与分类简述。",
        selfPath: "/feed/daily.xml",
        sitePath: "/daily",
      },
      usable[0] ? rfc822(issuedAt(usable[0])) : null,
      entries,
    );

    return conditionalText(request, body, FEED_CONTENT_TYPE, CACHE.feed);
  } catch (error) {
    console.error("[feed] daily.xml failed:", error);
    return new Response("数据源暂时不可用，请稍后重试。", {
      status: 503,
      headers: { "Retry-After": "300", "Cache-Control": "no-store" },
    });
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
