"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Pill, TABLE_HEAD_ROW, TABLE_ROW, TableShell } from "../ui";

export type ArticleDraft = {
  id: string;
  mode: "url" | "editor";
  processing_status: string;
  original_url?: string | null;
  manual_fields?: Record<string, unknown>;
  extracted_fields?: Record<string, unknown>;
  ai_fields?: Record<string, unknown>;
  last_error_detail?: string | null;
  updated_at?: string | null;
};

function titleOf(draft: ArticleDraft) {
  return String(
    draft.manual_fields?.title
      ?? draft.manual_fields?.title_zh
      ?? draft.ai_fields?.title_zh
      ?? draft.extracted_fields?.title
      ?? "未命名草稿",
  );
}

function stamp(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function DraftsManager({ initialDrafts }: { initialDrafts: ArticleDraft[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function deleteDraft(id: string) {
    if (!window.confirm("确定删除这份草稿吗？此操作不可恢复。")) return;
    setBusy(id);
    setMessage(null);
    try {
      const response = await fetch(`/api/admin-proxy/article-submissions/${id}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail?.message ?? payload.detail ?? "删除失败");
      }
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <a className="rounded-md bg-signal px-4 py-2 text-sm font-semibold text-canvas hover:bg-signal-bright" href="/admin/drafts/new">
          新增文章草稿
        </a>
      </div>
      {message ? <div className="rounded border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{message}</div> : null}
      <TableShell>
        <table className="w-full table-fixed text-left text-sm">
          <thead><tr className={TABLE_HEAD_ROW}><th className="w-[40%] px-4 py-3">标题</th><th className="w-[12%] px-4 py-3">类型</th><th className="w-[15%] px-4 py-3">处理状态</th><th className="w-[18%] px-4 py-3">最后保存</th><th className="w-[15%] px-4 py-3">操作</th></tr></thead>
          <tbody className="divide-y divide-line">
            {initialDrafts.map((draft) => (
              <tr key={draft.id} className={TABLE_ROW}>
                <td className="px-4 py-3"><a className="block truncate font-semibold text-ink hover:text-signal" href={`/admin/drafts/new?id=${encodeURIComponent(draft.id)}`}>{titleOf(draft)}</a>{draft.last_error_detail ? <p className="mt-1 truncate text-xs text-danger" title={draft.last_error_detail}>{draft.last_error_detail}</p> : null}</td>
                <td className="px-4 py-3 text-xs text-ink-mid">{draft.mode === "url" ? "原文链接" : "富文本创作"}</td>
                <td className="px-4 py-3"><Pill tone={draft.processing_status === "failed" ? "danger" : "signal"}>{draft.processing_status === "failed" ? "处理失败" : "草稿"}</Pill></td>
                <td className="readout px-4 py-3 text-xs text-ink-dim">{stamp(draft.updated_at)}</td>
                <td className="px-4 py-3"><div className="flex gap-2 text-xs font-semibold"><a className="rounded border border-line px-2.5 py-1 text-ink-mid hover:text-signal" href={`/admin/drafts/new?id=${encodeURIComponent(draft.id)}`}>继续编辑</a><button className="rounded border border-line px-2.5 py-1 text-ink-mid hover:text-danger disabled:opacity-40" disabled={busy === draft.id} onClick={() => deleteDraft(draft.id)} type="button">删除</button></div></td>
              </tr>
            ))}
            {!initialDrafts.length ? <tr><td className="px-4 py-8 text-center text-sm text-ink-dim" colSpan={5}>暂无草稿。</td></tr> : null}
          </tbody>
        </table>
      </TableShell>
    </div>
  );
}
