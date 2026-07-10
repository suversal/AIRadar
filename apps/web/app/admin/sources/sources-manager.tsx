"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export type AdminSource = {
  id: string;
  name: string;
  type: string;
  tier: string;
  category: string;
  url: string;
  is_active: boolean;
  fetch_interval_min: number;
  language: string;
  last_success_at: string | null;
  success_rate: number;
  error_count: number;
};

type TestResult = {
  status: "ok" | "failed";
  error?: string | null;
  articles?: { title: string; url: string }[];
};

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`/api/admin-proxy/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail ?? `请求失败（${response.status}）`);
  }
  return payload;
}

function healthLabel(source: AdminSource) {
  if (!source.is_active) return { text: "停用", tone: "text-ink-dim" };
  if (source.error_count > 0 || source.success_rate < 0.5)
    return { text: "故障", tone: "text-red-300" };
  if (source.success_rate < 0.9) return { text: "波动", tone: "text-yellow-300" };
  return { text: "正常", tone: "text-green-400" };
}

export function SourcesManager({ initialSources }: { initialSources: AdminSource[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [editing, setEditing] = useState<AdminSource | null>(null);

  async function run(sourceId: string, action: () => Promise<void>) {
    setBusy(sourceId);
    setMessage(null);
    try {
      await action();
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(null);
    }
  }

  async function toggle(source: AdminSource) {
    await run(source.id, async () => {
      await api(`sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !source.is_active }),
      });
    });
  }

  async function testFetch(source: AdminSource) {
    setBusy(source.id);
    setMessage(null);
    try {
      const result = (await api(`sources/${source.id}/test`, { method: "POST" })) as TestResult;
      setTestResults((prev) => ({ ...prev, [source.id]: result }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "试抓失败");
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit(form: FormData) {
    if (!editing) return;
    const payload = {
      name: String(form.get("name") ?? "").trim(),
      url: String(form.get("url") ?? "").trim(),
      tier: String(form.get("tier") ?? "T2"),
      fetch_interval_min: Number(form.get("fetch_interval_min") ?? 240),
    };
    await run(editing.id, async () => {
      await api(`sources/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setEditing(null);
    });
  }

  return (
    <div className="space-y-4">
      {message ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 px-4 py-3 text-sm text-red-200">
          {message}
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-md border border-line bg-panel">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-dim">
              <th className="px-4 py-3">信源</th>
              <th className="px-4 py-3">类型/层级</th>
              <th className="px-4 py-3">健康</th>
              <th className="px-4 py-3">成功率</th>
              <th className="px-4 py-3">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {initialSources.map((source) => {
              const health = healthLabel(source);
              const test = testResults[source.id];
              return (
                <tr key={source.id} className="align-top text-ink-mid">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-ink">{source.name}</div>
                    <div className="readout mt-1 max-w-xs truncate text-xs text-ink-dim">
                      {source.url}
                    </div>
                    {test ? (
                      <div
                        className={`mt-2 rounded border px-3 py-2 text-xs ${
                          test.status === "ok"
                            ? "border-green-400/30 bg-green-400/10 text-green-300"
                            : "border-red-400/30 bg-red-400/10 text-red-200"
                        }`}
                      >
                        {test.status === "ok"
                          ? `试抓成功：${(test.articles ?? []).map((a) => a.title).join("；").slice(0, 120)}`
                          : `试抓失败：${test.error}`}
                      </div>
                    ) : null}
                  </td>
                  <td className="readout px-4 py-3 text-xs">
                    {source.type} · {source.tier}
                  </td>
                  <td className={`px-4 py-3 text-xs font-semibold ${health.tone}`}>
                    {health.text}
                    {source.error_count > 0 ? ` (${source.error_count})` : ""}
                  </td>
                  <td className="readout px-4 py-3 text-xs">
                    {(source.success_rate * 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2 text-xs font-semibold">
                      <button
                        className={`rounded border px-3 py-1.5 ${
                          source.is_active
                            ? "border-line text-ink-mid hover:border-red-400/40 hover:text-red-300"
                            : "border-green-400/40 text-green-300 hover:bg-green-400/10"
                        }`}
                        disabled={busy === source.id}
                        onClick={() => toggle(source)}
                        type="button"
                      >
                        {source.is_active ? "停用" : "启用"}
                      </button>
                      <button
                        className="rounded border border-line px-3 py-1.5 text-ink-mid hover:border-signal/40 hover:text-signal"
                        disabled={busy === source.id}
                        onClick={() => testFetch(source)}
                        type="button"
                      >
                        {busy === source.id ? "…" : "试抓"}
                      </button>
                      <button
                        className="rounded border border-line px-3 py-1.5 text-ink-mid hover:border-signal/40 hover:text-signal"
                        onClick={() => setEditing(source)}
                        type="button"
                      >
                        编辑
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <form
            action={saveEdit}
            className="w-full max-w-lg rounded-md border border-line bg-panel p-6"
          >
            <h2 className="text-lg font-semibold text-ink">编辑信源 · {editing.id}</h2>
            <label className="mt-4 block text-xs text-ink-dim">
              名称
              <input
                className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                defaultValue={editing.name}
                name="name"
              />
            </label>
            <label className="mt-3 block text-xs text-ink-dim">
              Feed URL
              <input
                className="readout mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                defaultValue={editing.url}
                name="url"
              />
            </label>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <label className="block text-xs text-ink-dim">
                层级
                <select
                  className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                  defaultValue={editing.tier}
                  name="tier"
                >
                  {["T1", "T1_5", "T2", "T3"].map((tier) => (
                    <option key={tier} value={tier}>
                      {tier}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-ink-dim">
                抓取间隔（分钟）
                <input
                  className="readout mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                  defaultValue={editing.fetch_interval_min}
                  name="fetch_interval_min"
                  type="number"
                />
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-3 text-sm font-semibold">
              <button
                className="rounded border border-line px-4 py-2 text-ink-mid hover:text-ink"
                onClick={() => setEditing(null)}
                type="button"
              >
                取消
              </button>
              <button
                className="rounded border border-signal bg-signal px-4 py-2 text-canvas hover:bg-signal-bright"
                type="submit"
              >
                保存
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
