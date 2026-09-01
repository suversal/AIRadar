import type { PeriodArchiveEntry, PeriodReport } from "@/lib/api";
import { CACHE, conditionalText } from "@/lib/v1/http";
import { fetchUpstream } from "@/lib/v1/upstream";
import { FEED_CONTENT_TYPE } from "./load";
import { absolute, escapeXml, renderChannel, rfc822 } from "./rss";

type PeriodKind = "weekly" | "monthly";

const META = {
  weekly: { label: "周报", page: "weekly", keep: 8, self: "/feed/weekly.xml" },
  monthly: { label: "月报", page: "monthly", keep: 12, self: "/feed/monthly.xml" },
} as const;

function describe(report: PeriodReport): string {
  const parts: string[] = [];
  if (report.mainline_title) parts.push(`<h3>${escapeXml(report.mainline_title)}</h3>`);
  if (report.mainline_body) parts.push(`<p>${escapeXml(report.mainline_body)}</p>`);
  for (const note of report.theme_notes ?? []) {
    if (note.note) parts.push(`<p><strong>${escapeXml(note.label)}：</strong>${escapeXml(note.note)}</p>`);
  }
  parts.push(`<p>共 ${report.article_count ?? 0} 条入选事件。</p>`);
  return parts.join("\n");
}

/** 周/月 feed 只发布封版期次。当前周期仍会变化，进入阅读器后反复改写会制造假定稿。 */
export async function renderPeriodFeed(request: Request, kind: PeriodKind): Promise<Response> {
  const meta = META[kind];
  try {
    const archive = await fetchUpstream<{ entries?: PeriodArchiveEntry[] }>(
      `/api/public/reports/${kind}/archive`,
      { revalidate: CACHE.periodIndex },
    );
    const candidates = (archive.entries ?? []).slice(0, meta.keep + 2);
    const reports = await Promise.all(
      candidates.map((entry) =>
        fetchUpstream<PeriodReport>(
          `/api/public/reports/${kind}/${encodeURIComponent(entry.period_key)}`,
          { revalidate: CACHE.periodLatest },
        ).catch(() => null),
      ),
    );
    const usable = reports
      .filter((report): report is PeriodReport => Boolean(report?.finalized_at) && (report?.article_count ?? 0) > 0)
      .slice(0, meta.keep);

    const entries = usable.map((report) => {
      const key = report.period_key ?? "";
      const link = absolute(`/${meta.page}/${encodeURIComponent(key)}`);
      const pubDate = rfc822(report.finalized_at ?? null);
      const lines = [
        `      <title>${escapeXml(`AI·RADAR ${meta.label} · ${key}`)}</title>`,
        `      <link>${escapeXml(link)}</link>`,
        `      <guid isPermaLink="false">${kind}-${escapeXml(key)}</guid>`,
        `      <description><![CDATA[${describe(report)}]]></description>`,
      ];
      if (pubDate) lines.push(`      <pubDate>${pubDate}</pubDate>`);
      return `    <item>\n${lines.join("\n")}\n    </item>`;
    }).join("\n");

    const body = renderChannel(
      {
        title: `AI·RADAR ${meta.label}`,
        description: `AI·RADAR 已封版${meta.label}，含主线综述、主题观察与入选事件。`,
        selfPath: meta.self,
        sitePath: `/${meta.page}`,
      },
      usable[0] ? rfc822(usable[0].finalized_at ?? null) : null,
      entries,
    );
    return conditionalText(request, body, FEED_CONTENT_TYPE, CACHE.feed);
  } catch (error) {
    console.error(`[feed] ${kind} feed failed:`, error);
    return new Response("数据源暂时不可用，请稍后重试。", {
      status: 503,
      headers: { "Retry-After": "300", "Cache-Control": "no-store" },
    });
  }
}
