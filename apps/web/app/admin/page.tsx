import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "./admin-shell";
import { RefreshReportButton } from "./refresh-report-button";
import { SchedulePanel } from "./schedule-panel";

export const metadata = {
  title: "仪表盘 · AI·RADAR 管理后台",
};

type SourceHealth = {
  id: string;
  name: string;
  type: string;
  is_active: boolean;
  last_success_at: string | null;
  last_crawled_at: string | null;
  success_rate: number;
  error_count: number;
};

type SourceCrawlResult = {
  status: string;
  article_count: number;
  fetched_count?: number;
  duration_ms: number;
  error: string | null;
};

type PipelineRun = {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  raw_count: number;
  processed_count: number;
  cluster_count: number;
  skipped_reasons: Record<string, number>;
  error: string | null;
  phase: string | null;
  source_report: Record<string, SourceCrawlResult>;
};

function formatDuration(start?: string | null, end?: string | null, status?: string) {
  if (!start) return "--";
  const started = new Date(start).getTime();
  const finished = end ? new Date(end).getTime() : status === "running" ? Date.now() : NaN;
  if (!Number.isFinite(started) || !Number.isFinite(finished)) return "--";
  const totalSeconds = Math.max(0, Math.floor((finished - started) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}分${String(seconds).padStart(2, "0")}秒`;
}

type Overview = {
  runs: PipelineRun[];
  sources: SourceHealth[];
  counts: Record<string, number>;
};

function formatTime(value?: string | null) {
  if (!value) {
    return "从未";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function healthTone(source: SourceHealth) {
  if (!source.is_active) {
    return { dot: "bg-ink-dim", label: "停用" };
  }
  if (source.error_count > 0 || source.success_rate < 0.5) {
    return { dot: "bg-red-400", label: "故障" };
  }
  if (source.success_rate < 0.9) {
    return { dot: "bg-yellow-400", label: "波动" };
  }
  return { dot: "bg-green-400", label: "正常" };
}

const COUNT_LABELS: Record<string, { label: string; help: string }> = {
  sources: { label: "信源", help: "已配置的抓取入口" },
  raw_articles: { label: "原始文章", help: "抓取入库的去重文章" },
  processed_articles: { label: "已处理文章", help: "完成 AI 评分/分类的文章" },
  event_clusters: { label: "事件簇", help: "相似文章合并后的事件" },
  daily_reports: { label: "日报", help: "已生成的日报版本" },
  pipeline_runs: { label: "同步记录", help: "每次数据同步运行记录" },
};

const SKIPPED_REASON_LABELS: Record<string, string> = {
  ai_error: "AI 返回异常",
  below_threshold: "评分未达精选阈值",
  candidate_limit: "超过候选上限",
  not_ai_related: "非 AI 相关",
  cached_not_ai_related: "命中历史非 AI 结果",
};

const STATUS_LABELS: Record<string, string> = {
  succeeded: "成功",
  failed: "失败",
  running: "运行中",
};

const PHASE_LABELS: Record<string, string> = {
  crawling: "抓取中",
  scoring: "AI 处理中",
  persisting: "落库中",
  reports: "生成周期报告",
};

function sortedSourceReport(report: Record<string, SourceCrawlResult>) {
  // 失败的信源排最前，其余按文章数降序——一眼看到问题源
  return Object.entries(report).sort(([, a], [, b]) => {
    if ((a.status !== "ok") !== (b.status !== "ok")) {
      return a.status !== "ok" ? -1 : 1;
    }
    return (b.article_count ?? 0) - (a.article_count ?? 0);
  });
}

function skippedReasonText(reasons: Record<string, number>) {
  const entries = Object.entries(reasons);
  if (entries.length === 0) {
    return "无";
  }
  return entries
    .map(([reason, count]) => `${SKIPPED_REASON_LABELS[reason] ?? reason} ${count}`)
    .join(" · ");
}

export default async function AdminDashboardPage() {
  const [response, scheduleResponse] = await Promise.all([
    adminFetch("/api/admin/overview"),
    adminFetch("/api/admin/schedule"),
  ]);
  const overview: Overview | null = response.ok ? await response.json() : null;
  const scheduleConfig = scheduleResponse.ok ? await scheduleResponse.json() : null;

  return (
    <AdminShell
      active="dashboard"
      title="仪表盘"
      subtitle="抓取健康度、运行台账与数据规模"
    >
      {!overview ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 p-5 text-sm text-red-200">
          概览数据不可用（{response.status}）——数据库模式未启用或认证失效。
        </div>
      ) : (
        <div className="space-y-8">
          <section className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(overview.counts).map(([name, value]) => (
              <div key={name} className="rounded-md border border-line bg-panel p-4">
                <div className="readout text-xl font-semibold text-ink">{value}</div>
                <div className="mt-1 text-sm font-semibold text-ink-mid">
                  {COUNT_LABELS[name]?.label ?? name}
                </div>
                <div className="mt-1 min-h-8 text-xs leading-4 text-ink-dim">
                  {COUNT_LABELS[name]?.help ?? "数据库记录数"}
                </div>
              </div>
            ))}
          </section>

          <section className="rounded-md border border-line bg-panel p-5">
            <SchedulePanel initialConfig={scheduleConfig} />
          </section>

          <section className="rounded-md border border-line bg-panel p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-ink">运行台账</h2>
                <p className="mt-1 text-xs text-ink-dim">
                  记录每次数据同步的抓取、AI 处理、聚类和跳过情况
                </p>
              </div>
              <RefreshReportButton />
            </div>
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-xs text-ink-dim">
                    <th className="py-2 pr-4">#</th>
                    <th className="py-2 pr-4">开始</th>
                    <th className="py-2 pr-4">结束</th>
                    <th className="py-2 pr-4">耗时</th>
                    <th className="py-2 pr-4">状态</th>
                    <th className="py-2 pr-4">抓取文章</th>
                    <th className="py-2 pr-4">AI 处理</th>
                    <th className="py-2 pr-4">事件簇</th>
                    <th className="py-2">跳过说明</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {overview.runs.map((run) => (
                    <tr key={run.id} className="text-ink-mid">
                      <td className="readout py-2 pr-4">{run.id}</td>
                      <td className="readout py-2 pr-4">{formatTime(run.started_at)}</td>
                      <td className="readout py-2 pr-4">{formatTime(run.finished_at)}</td>
                      <td className="readout whitespace-nowrap py-2 pr-4">
                        {formatDuration(run.started_at, run.finished_at, run.status)}
                      </td>
                      <td className="py-2 pr-4">
                        <span
                          className={
                            run.status === "succeeded"
                              ? "text-green-400"
                              : run.status === "running"
                                ? "text-yellow-300"
                                : "text-red-300"
                          }
                        >
                          {STATUS_LABELS[run.status] ?? run.status}
                          {run.status === "running" && run.phase
                            ? ` · ${PHASE_LABELS[run.phase] ?? run.phase}`
                            : null}
                        </span>
                      </td>
                      <td className="readout py-2 pr-4">{run.raw_count}</td>
                      <td className="readout py-2 pr-4">{run.processed_count}</td>
                      <td className="readout py-2 pr-4">{run.cluster_count}</td>
                      <td className="max-w-md py-2 text-xs leading-5 text-ink-dim">
                        <div>{skippedReasonText(run.skipped_reasons)}</div>
                        {Object.keys(run.source_report ?? {}).length > 0 ? (
                          <details className="mt-1 max-w-xl">
                            <summary className="cursor-pointer text-sky-300">
                              信源明细（
                              {
                                Object.values(run.source_report).filter(
                                  (item) => item.status === "ok",
                                ).length
                              }
                              /{Object.keys(run.source_report).length} 成功）
                            </summary>
                            <div className="mt-2 max-h-72 overflow-auto rounded bg-canvas p-2">
                              <table className="w-full text-[11px] leading-4">
                                <thead>
                                  <tr className="text-ink-dim">
                                    <th className="py-1 pr-2 text-left">信源</th>
                                    <th className="py-1 pr-2 text-left">状态</th>
                                    <th className="py-1 pr-2 text-right">入选/抓取</th>
                                    <th className="py-1 pr-2 text-right">耗时</th>
                                    <th className="py-1 text-left">错误</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {sortedSourceReport(run.source_report).map(([sourceId, item]) => (
                                    <tr key={sourceId} className="border-t border-line/50">
                                      <td className="py-1 pr-2">{sourceId}</td>
                                      <td
                                        className={
                                          item.status === "ok"
                                            ? "py-1 pr-2 text-green-400"
                                            : "py-1 pr-2 text-red-300"
                                        }
                                      >
                                        {item.status === "ok" ? "成功" : "失败"}
                                      </td>
                                      <td className="readout py-1 pr-2 text-right">
                                        {item.article_count}
                                        {typeof item.fetched_count === "number"
                                          ? `/${item.fetched_count}`
                                          : ""}
                                      </td>
                                      <td className="readout py-1 pr-2 text-right">
                                        {Math.round(item.duration_ms)}ms
                                      </td>
                                      <td className="max-w-56 break-all py-1 text-red-200">
                                        {item.error ?? ""}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </details>
                        ) : null}
                        {run.error ? (
                          <details className="mt-1 max-w-xl">
                            <summary className="cursor-pointer text-red-300">查看完整错误</summary>
                            <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded bg-canvas p-3 text-[11px] leading-4 text-red-200">
                              {run.error}
                            </pre>
                          </details>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                  {overview.runs.length === 0 ? (
                    <tr>
                      <td className="py-4 text-ink-dim" colSpan={9}>
                        暂无运行记录，触发一次手动刷新后这里会出现台账。
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </AdminShell>
  );
}
