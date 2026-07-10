import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "./admin-shell";
import { RefreshReportButton } from "./refresh-report-button";

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

type PipelineRun = {
  id: number;
  started_at: string | null;
  status: string;
  raw_count: number;
  processed_count: number;
  cluster_count: number;
  skipped_reasons: Record<string, number>;
  error: string | null;
};

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

export default async function AdminDashboardPage() {
  const response = await adminFetch("/api/admin/overview");
  const overview: Overview | null = response.ok ? await response.json() : null;

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
              <div key={name} className="rounded-md border border-line bg-panel p-4 text-center">
                <div className="readout text-xl font-semibold text-ink">{value}</div>
                <div className="mt-1 text-xs text-ink-dim">{name}</div>
              </div>
            ))}
          </section>

          <section className="rounded-md border border-line bg-panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <h2 className="text-base font-semibold text-ink">手动刷新</h2>
              <span className="text-xs text-ink-dim">
                触发一轮抓取 + AI 处理 + 日报生成（增量缓存生效，仅新文章产生 AI 调用）
              </span>
            </div>
            <div className="mt-4 max-w-md">
              <RefreshReportButton />
            </div>
          </section>

          <section className="rounded-md border border-line bg-panel p-5">
            <h2 className="text-base font-semibold text-ink">
              信源健康 <span className="ml-2 text-sm font-normal text-ink-dim">{overview.sources.length} 个</span>
            </h2>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {overview.sources.map((source) => {
                const tone = healthTone(source);
                return (
                  <div
                    key={source.id}
                    className="flex items-center justify-between gap-3 rounded-md border border-line bg-canvas px-4 py-3"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`} />
                        <span className="truncate text-sm font-semibold text-ink">{source.name}</span>
                      </div>
                      <div className="readout mt-1 text-xs text-ink-dim">
                        {tone.label} · 成功率 {(source.success_rate * 100).toFixed(0)}% · 最近成功{" "}
                        {formatTime(source.last_success_at)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-md border border-line bg-panel p-5">
            <h2 className="text-base font-semibold text-ink">运行台账</h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-xs text-ink-dim">
                    <th className="py-2 pr-4">#</th>
                    <th className="py-2 pr-4">时间</th>
                    <th className="py-2 pr-4">状态</th>
                    <th className="py-2 pr-4">原始</th>
                    <th className="py-2 pr-4">处理</th>
                    <th className="py-2 pr-4">聚类</th>
                    <th className="py-2">跳过原因</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {overview.runs.map((run) => (
                    <tr key={run.id} className="text-ink-mid">
                      <td className="readout py-2 pr-4">{run.id}</td>
                      <td className="readout py-2 pr-4">{formatTime(run.started_at)}</td>
                      <td className="py-2 pr-4">
                        <span
                          className={
                            run.status === "succeeded" ? "text-green-400" : "text-red-300"
                          }
                        >
                          {run.status}
                        </span>
                      </td>
                      <td className="readout py-2 pr-4">{run.raw_count}</td>
                      <td className="readout py-2 pr-4">{run.processed_count}</td>
                      <td className="readout py-2 pr-4">{run.cluster_count}</td>
                      <td className="py-2 text-xs">
                        {Object.entries(run.skipped_reasons)
                          .map(([reason, count]) => `${reason}:${count}`)
                          .join(" ") || "-"}
                      </td>
                    </tr>
                  ))}
                  {overview.runs.length === 0 ? (
                    <tr>
                      <td className="py-4 text-ink-dim" colSpan={7}>
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
