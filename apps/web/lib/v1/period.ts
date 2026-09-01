// 周报/月报的 v1 共同取数逻辑。

import type { PeriodArchiveEntry, PeriodReport } from "@/lib/api";
import { CACHE, notFound, ok, type V1Success } from "./http";
import { shapePeriod } from "./shape";
import { fetchUpstream } from "./upstream";

export type PeriodKind = "weekly" | "monthly";

export const PERIOD_META = {
  weekly: { collection: "weeklies", page: "weekly", label: "周报" },
  monthly: { collection: "monthlies", page: "monthly", label: "月报" },
} as const;

export function periodCacheTier(report: PeriodReport): number {
  return report.finalized_at ? CACHE.periodArchived : CACHE.periodLatest;
}

export async function loadPeriod(kind: PeriodKind, key?: string): Promise<V1Success> {
  const path = key
    ? `/api/public/reports/${kind}/${encodeURIComponent(key)}`
    : `/api/public/reports/${kind}`;
  const report = await fetchUpstream<PeriodReport>(path, { revalidate: CACHE.periodLatest });

  if (!report || !report.period_key || (report.article_count ?? 0) === 0) {
    const suffix = key ? ` ${key}` : "";
    throw notFound(`没有找到${PERIOD_META[kind].label}${suffix}。`);
  }

  return ok({ schemaVersion: 1, report: shapePeriod(report) }, periodCacheTier(report));
}

export async function loadPeriodArchive(kind: PeriodKind): Promise<PeriodArchiveEntry[]> {
  const payload = await fetchUpstream<{ entries?: PeriodArchiveEntry[] }>(
    `/api/public/reports/${kind}/archive`,
    { revalidate: CACHE.periodIndex },
  );
  return payload.entries ?? [];
}
