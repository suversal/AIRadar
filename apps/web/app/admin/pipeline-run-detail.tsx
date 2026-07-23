"use client";

import { useState } from "react";
import { Pill, TABLE_HEAD_ROW, TABLE_ROW } from "./ui";

type SourceCrawlResult = {
  status: string;
  accepted_count: number;
  ingested_count?: number;
  fetched_count?: number;
  duration_ms: number;
  error: string | null;
};

function sortedSourceReport(report: Record<string, SourceCrawlResult>) {
  // 失败的信源排最前，其余按新入库文章数降序——一眼看到问题源
  return Object.entries(report).sort(([, a], [, b]) => {
    if ((a.status !== "ok") !== (b.status !== "ok")) {
      return a.status !== "ok" ? -1 : 1;
    }
    return (b.ingested_count ?? b.accepted_count ?? 0) - (a.ingested_count ?? a.accepted_count ?? 0);
  });
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-md border border-line bg-panel">
        <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          <button
            className="rounded border border-line px-3 py-1.5 text-sm text-ink-mid hover:text-ink"
            onClick={onClose}
            type="button"
          >
            关闭
          </button>
        </div>
        <div className="overflow-y-auto px-6 py-4">{children}</div>
      </div>
    </div>
  );
}

export function PipelineRunDetail({
  runId,
  sourceReport,
  error,
  sourceNames,
}: {
  runId: number;
  sourceReport: Record<string, SourceCrawlResult>;
  error: string | null;
  // id→当前名称:信源改名后明细跟着显示新名,id 只是稳定标识
  sourceNames?: Record<string, string>;
}) {
  const [open, setOpen] = useState<"sources" | "error" | null>(null);
  const entries = sortedSourceReport(sourceReport ?? {});
  const successCount = entries.filter(([, item]) => item.status === "ok").length;

  return (
    <>
      <div className="flex flex-col items-start gap-1">
        {entries.length > 0 ? (
          <button
            className="text-info hover:underline"
            onClick={() => setOpen("sources")}
            type="button"
          >
            信源明细（{successCount}/{entries.length} 成功）
          </button>
        ) : null}
        {error ? (
          <button
            className="text-danger hover:underline"
            onClick={() => setOpen("error")}
            type="button"
          >
            查看完整错误
          </button>
        ) : null}
      </div>

      {open === "sources" ? (
        <Modal title={`信源明细 · 运行 #${runId}`} onClose={() => setOpen(null)}>
          <table className="w-full text-xs leading-4">
            <thead>
              <tr className={TABLE_HEAD_ROW}>
                <th className="py-2 pr-2 text-left font-semibold">信源</th>
                <th className="py-2 pr-2 text-left font-semibold">状态</th>
                <th className="py-2 pr-2 text-right font-semibold">入库/抓取（精选）</th>
                <th className="py-2 pr-2 text-right font-semibold">耗时</th>
                <th className="py-2 text-left font-semibold">错误</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50">
              {entries.map(([sourceId, item]) => (
                <tr key={sourceId} className={TABLE_ROW}>
                  <td className="py-1.5 pr-2 text-ink-mid">
                    {sourceNames?.[sourceId] ?? sourceId}
                  </td>
                  <td className="py-1.5 pr-2">
                    <Pill tone={item.status === "ok" ? "success" : "danger"}>
                      {item.status === "ok" ? "成功" : "失败"}
                    </Pill>
                  </td>
                  <td className="readout py-1.5 pr-2 text-right text-ink-mid">
                    {item.ingested_count ?? item.accepted_count}
                    {typeof item.fetched_count === "number" ? `/${item.fetched_count}` : ""}
                    {typeof item.ingested_count === "number" ? ` (${item.accepted_count})` : ""}
                  </td>
                  <td className="readout py-1.5 pr-2 text-right text-ink-mid">
                    {typeof item.duration_ms === "number" ? `${Math.round(item.duration_ms)}ms` : "--"}
                  </td>
                  <td className="max-w-56 break-all py-1.5 text-danger/90">{item.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Modal>
      ) : null}

      {open === "error" ? (
        <Modal title={`完整错误 · 运行 #${runId}`} onClose={() => setOpen(null)}>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-canvas p-3 text-xs leading-5 text-danger">
            {error}
          </pre>
        </Modal>
      ) : null}
    </>
  );
}
