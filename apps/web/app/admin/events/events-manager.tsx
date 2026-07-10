"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

export type AdminEvent = {
  event_id: string;
  title: string;
  category: string;
  category_label?: string;
  tags?: string[];
  final_score?: number;
  selected?: boolean;
  hidden?: boolean;
  published_at?: string;
  main_source?: { name: string };
  original_url?: string;
};

const CATEGORY_OPTIONS = [
  ["model_release", "模型发布"],
  ["product_release", "产品发布"],
  ["open_source", "开源"],
  ["research", "论文"],
  ["industry", "行业"],
  ["funding", "融资"],
  ["opinion", "观点"],
  ["tutorial", "技巧"],
] as const;

type Filter = "all" | "selected" | "hidden";

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

export function EventsManager({ initialEvents }: { initialEvents: AdminEvent[] }) {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminEvent | null>(null);

  const events = useMemo(() => {
    if (filter === "selected") return initialEvents.filter((event) => event.selected);
    if (filter === "hidden") return initialEvents.filter((event) => event.hidden);
    return initialEvents;
  }, [filter, initialEvents]);

  async function run(eventId: string, action: () => Promise<void>) {
    setBusy(eventId);
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

  async function toggleHidden(event: AdminEvent) {
    await run(event.event_id, async () => {
      await api(`events/${event.event_id}`, {
        method: "PATCH",
        body: JSON.stringify({ hidden: !event.hidden }),
      });
    });
  }

  async function saveEdit(form: FormData) {
    if (!editing) return;
    const payload = {
      title_zh: String(form.get("title_zh") ?? "").trim(),
      category: String(form.get("category") ?? ""),
      tags: String(form.get("tags") ?? "")
        .split(/[,，\s]+/)
        .map((tag) => tag.trim())
        .filter(Boolean),
    };
    await run(editing.event_id, async () => {
      await api(`events/${editing.event_id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setEditing(null);
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-md border border-line bg-panel p-1 text-sm font-semibold">
          {(
            [
              ["all", `全部 ${initialEvents.length}`],
              ["selected", `精选 ${initialEvents.filter((event) => event.selected).length}`],
              ["hidden", `已隐藏 ${initialEvents.filter((event) => event.hidden).length}`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              className={`rounded px-4 py-1.5 ${
                filter === key ? "bg-signal/15 text-signal" : "text-ink-mid hover:text-ink"
              }`}
              onClick={() => setFilter(key)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-xs text-ink-dim">
          隐藏立即从全部动态与详情页消失；影响精选日报需再点仪表盘"刷新最新日报"
        </p>
      </div>

      {message ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 px-4 py-3 text-sm text-red-200">
          {message}
        </div>
      ) : null}

      <div className="divide-y divide-line rounded-md border border-line bg-panel">
        {events.map((event) => (
          <div key={event.event_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                {event.hidden ? (
                  <span className="rounded border border-red-400/40 px-2 py-0.5 text-xs text-red-300">
                    已隐藏
                  </span>
                ) : null}
                {event.selected ? (
                  <span className="rounded border border-signal/40 px-2 py-0.5 text-xs text-signal">
                    精选
                  </span>
                ) : null}
                <span className="rounded bg-panel-soft px-2 py-0.5 text-xs text-ink-mid">
                  {event.category_label ?? event.category}
                </span>
                <span className="readout text-xs text-ink-dim">
                  {event.final_score != null ? Math.round(event.final_score) : "--"}
                </span>
              </div>
              <div className={`mt-1 truncate text-sm font-semibold ${event.hidden ? "text-ink-dim line-through" : "text-ink"}`}>
                {event.title}
              </div>
              <div className="mt-0.5 truncate text-xs text-ink-dim">
                {event.main_source?.name} · {(event.tags ?? []).join(" / ") || "无标签"}
              </div>
            </div>
            <div className="flex shrink-0 gap-2 text-xs font-semibold">
              <button
                className={`rounded border px-3 py-1.5 ${
                  event.hidden
                    ? "border-green-400/40 text-green-300 hover:bg-green-400/10"
                    : "border-line text-ink-mid hover:border-red-400/40 hover:text-red-300"
                }`}
                disabled={busy === event.event_id}
                onClick={() => toggleHidden(event)}
                type="button"
              >
                {event.hidden ? "恢复" : "隐藏"}
              </button>
              <button
                className="rounded border border-line px-3 py-1.5 text-ink-mid hover:border-signal/40 hover:text-signal"
                onClick={() => setEditing(event)}
                type="button"
              >
                编辑
              </button>
            </div>
          </div>
        ))}
        {events.length === 0 ? (
          <div className="px-4 py-8 text-sm text-ink-dim">当前筛选下没有事件。</div>
        ) : null}
      </div>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <form action={saveEdit} className="w-full max-w-lg rounded-md border border-line bg-panel p-6">
            <h2 className="text-lg font-semibold text-ink">编辑事件</h2>
            <label className="mt-4 block text-xs text-ink-dim">
              中文标题
              <input
                className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                defaultValue={editing.title}
                name="title_zh"
              />
            </label>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <label className="block text-xs text-ink-dim">
                分类
                <select
                  className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                  defaultValue={editing.category}
                  name="category"
                >
                  {CATEGORY_OPTIONS.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-ink-dim">
                标签（逗号分隔）
                <input
                  className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                  defaultValue={(editing.tags ?? []).join(", ")}
                  name="tags"
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
