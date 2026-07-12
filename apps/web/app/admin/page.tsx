import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "./admin-shell";
import { PipelineRunDetail } from "./pipeline-run-detail";
import { RefreshReportButton } from "./refresh-report-button";
import { SchedulePanel } from "./schedule-panel";
import { Pill, TABLE_HEAD_ROW, TABLE_ROW, type Tone } from "./ui";

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
  accepted_count: number;
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
  // 台账漏斗:抓取 = 重复 + 非AI(判定后直接丢弃) + 入库;精选 ⊂ 入库。
  // null = 该行早于指标列上线
  new_raw_count: number | null;
  new_selected_count: number | null;
  non_ai_dropped_count: number | null;
  duplicate_count: number | null;
  skipped_reasons: Record<string, number>;
  error: string | null;
  phase: string | null;
  source_report: Record<string, SourceCrawlResult>;
};

function formatNullableCount(value: number | null | undefined) {
  return typeof value === "number" ? value : "--";
}

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

const STATUS_LABELS: Record<string, string> = {
  succeeded: "成功",
  failed: "失败",
  running: "运行中",
};

const STATUS_TONE: Record<string, Tone> = {
  succeeded: "success",
  failed: "danger",
  running: "warning",
};

const PHASE_LABELS: Record<string, string> = {
  crawling: "抓取中",
  scoring: "AI 处理中",
  persisting: "落库中",
  reports: "生成周期报告",
};

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
                  记录每次数据同步的抓取、重复、非AI 与入库情况
                </p>
              </div>
              <RefreshReportButton />
            </div>
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className={TABLE_HEAD_ROW}>
                    <th className="py-2.5 pr-4 text-right font-semibold">#</th>
                    <th className="py-2.5 pr-4 font-semibold">开始</th>
                    <th className="py-2.5 pr-4 font-semibold">结束</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">耗时</th>
                    <th className="py-2.5 pr-4 font-semibold">状态</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">抓取</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">重复</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">非AI</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">入库</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">精选</th>
                    <th className="py-2.5 font-semibold">信源明细</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {overview.runs.map((run) => (
                    <tr key={run.id} className={`text-ink-mid ${TABLE_ROW}`}>
                      <td className="readout py-2.5 pr-4 text-right text-ink-dim">{run.id}</td>
                      <td className="readout py-2.5 pr-4">{formatTime(run.started_at)}</td>
                      <td className="readout py-2.5 pr-4">{formatTime(run.finished_at)}</td>
                      <td className="readout whitespace-nowrap py-2.5 pr-4 text-right">
                        {formatDuration(run.started_at, run.finished_at, run.status)}
                      </td>
                      <td className="py-2.5 pr-4">
                        <Pill tone={STATUS_TONE[run.status] ?? "neutral"}>
                          {STATUS_LABELS[run.status] ?? run.status}
                          {run.status === "running" && run.phase
                            ? ` · ${PHASE_LABELS[run.phase] ?? run.phase}`
                            : null}
                        </Pill>
                      </td>
                      <td className="readout py-2.5 pr-4 text-right">{run.raw_count}</td>
                      <td className="readout py-2.5 pr-4 text-right">
                        {formatNullableCount(run.duplicate_count)}
                      </td>
                      <td className="readout py-2.5 pr-4 text-right">
                        {formatNullableCount(run.non_ai_dropped_count)}
                      </td>
                      <td className="readout py-2.5 pr-4 text-right">
                        {formatNullableCount(run.new_raw_count)}
                      </td>
                      <td className="readout py-2.5 pr-4 text-right">
                        {formatNullableCount(run.new_selected_count)}
                      </td>
                      <td className="max-w-md py-2.5 text-xs leading-5 text-ink-dim">
                        <PipelineRunDetail
                          error={run.error}
                          runId={run.id}
                          sourceReport={run.source_report ?? {}}
                        />
                      </td>
                    </tr>
                  ))}
                  {overview.runs.length === 0 ? (
                    <tr>
                      <td className="py-4 text-ink-dim" colSpan={11}>
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
