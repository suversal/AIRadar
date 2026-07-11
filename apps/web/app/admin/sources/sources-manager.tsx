"use client";

import { useState, type MouseEvent as ReactMouseEvent } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Pill, StatusDot, TABLE_HEAD_ROW, TABLE_ROW, TableShell, type Tone } from "../ui";

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
  last_crawled_at: string | null;
  last_success_at: string | null;
  success_rate: number;
  error_count: number;
  config?: Record<string, unknown>;
  last_crawl_result?: CrawlResult | null;
};

type CrawlArticleResult = {
  title: string;
  url: string;
  outcome?: "saved" | "rejected" | "duplicate";
  selected?: boolean | null;
  final_score?: number | null;
  category?: string | null;
  reason?: string | null;
};

type CrawlResult = {
  origin?: "manual" | "auto";
  at?: string;
  status: "ok" | "failed";
  error?: string | null;
  fetched_count?: number;
  accepted_count?: number;
  articles?: CrawlArticleResult[];
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

function healthLabel(source: AdminSource): { text: string; tone: Tone } {
  if (!source.is_active) return { text: "停用", tone: "neutral" };
  if (source.error_count > 0 || source.success_rate < 0.5) return { text: "故障", tone: "danger" };
  if (source.success_rate < 0.9) return { text: "波动", tone: "warning" };
  return { text: "正常", tone: "success" };
}

function formatTime(value?: string | null) {
  if (!value) return "从未";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function resultSummary(result?: CrawlResult | null): { tone: Tone; text: string } {
  if (!result) return { tone: "neutral", text: "尚未抓取" };
  if (result.status === "failed") {
    return { tone: "danger", text: "失败" };
  }
  const origin = result.origin === "auto" ? "自动" : "手动";
  if (!result.articles?.length) {
    return { tone: "neutral", text: `${origin} · 抓到 ${result.fetched_count ?? 0} 篇` };
  }
  const saved = result.articles.filter((article) => article.outcome === "saved").length;
  return { tone: "success", text: `${origin} · 抓到 ${result.articles.length} · 通过 ${saved}` };
}

const RESULT_BUTTON_TONE: Record<Tone, string> = {
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
  signal: "border-signal/30 bg-signal/10 text-signal",
  neutral: "border-line text-ink-dim",
};

const OUTCOME_LABEL: Record<string, { text: string; tone: Tone }> = {
  saved: { text: "已保存", tone: "success" },
  rejected: { text: "未通过", tone: "neutral" },
  duplicate: { text: "已存在", tone: "warning" },
};

export function SourcesManager({ initialSources }: { initialSources: AdminSource[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<{ id: string; kind: "toggle" | "fetch" | "edit" } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, CrawlResult>>(() => {
    const seeded: Record<string, CrawlResult> = {};
    for (const source of initialSources) {
      if (source.last_crawl_result) {
        seeded[source.id] = source.last_crawl_result;
      }
    }
    return seeded;
  });
  const [editing, setEditing] = useState<AdminSource | null>(null);
  const [viewingResultFor, setViewingResultFor] = useState<string | null>(null);
  const [hoverCard, setHoverCard] = useState<{
    source: AdminSource;
    top: number;
    left: number;
    flip: boolean;
  } | null>(null);

  function showHoverCard(event: ReactMouseEvent<HTMLElement>, source: AdminSource) {
    const rect = event.currentTarget.getBoundingClientRect();
    const flip = rect.bottom + 90 > window.innerHeight;
    setHoverCard({
      source,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 340)),
      top: flip ? rect.top - 8 : rect.bottom + 8,
      flip,
    });
  }

  async function run(sourceId: string, kind: "toggle" | "edit", action: () => Promise<void>) {
    setBusy({ id: sourceId, kind });
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
    await run(source.id, "toggle", async () => {
      await api(`sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !source.is_active }),
      });
    });
  }

  async function manualFetch(source: AdminSource) {
    setBusy({ id: source.id, kind: "fetch" });
    setMessage(null);
    try {
      const result = (await api(`sources/${source.id}/test`, { method: "POST" })) as CrawlResult;
      setTestResults((prev) => ({ ...prev, [source.id]: result }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "抓取失败");
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit(form: FormData) {
    if (!editing) return;
    const crawlLimit = Number(form.get("crawl_limit") ?? 0);
    const payload = {
      name: String(form.get("name") ?? "").trim(),
      url: String(form.get("url") ?? "").trim(),
      tier: String(form.get("tier") ?? "T2"),
      fetch_interval_min: Number(form.get("fetch_interval_min") ?? 240),
      config: {
        ...(editing.config ?? {}),
        ...(crawlLimit > 0 ? { crawl_limit: crawlLimit } : { crawl_limit: undefined }),
      },
    };
    if (crawlLimit <= 0 && payload.config) {
      delete (payload.config as Record<string, unknown>).crawl_limit;
    }
    await run(editing.id, "edit", async () => {
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

      <TableShell>
        <table className="w-full table-fixed text-left text-sm">
          <thead>
            <tr className={TABLE_HEAD_ROW}>
              <th className="w-[27%] px-4 py-3 font-semibold">信源</th>
              <th className="w-[17%] px-4 py-3 font-semibold">类型</th>
              <th className="w-[13%] px-4 py-3 font-semibold">状态与健康</th>
              <th className="w-[18%] px-4 py-3 font-semibold">上次抓取结果</th>
              <th className="w-[25%] px-4 py-3 font-semibold">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {initialSources.map((source) => {
              const health = healthLabel(source);
              const test = testResults[source.id];
              const summary = resultSummary(test);
              const crawlLimitLabel =
                Number(source.config?.crawl_limit ?? 0) > 0
                  ? `每轮 ${source.config?.crawl_limit} 条`
                  : "每轮默认 5 条";
              return (
                <tr key={source.id} className={`align-top text-ink-mid ${TABLE_ROW}`}>
                  <td className="min-w-0 px-4 py-3">
                    <div
                      className="w-fit max-w-full"
                      onMouseEnter={(event) => showHoverCard(event, source)}
                      onMouseLeave={() => setHoverCard(null)}
                    >
                      <div className="truncate font-semibold text-ink">{source.name}</div>
                      <div className="readout mt-1 truncate text-xs text-ink-dim">{source.url}</div>
                    </div>
                  </td>
                  <td className="min-w-0 px-4 py-3 text-xs">
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="rounded bg-panel-soft px-1.5 py-0.5 text-[11px] font-semibold text-ink-mid">
                        {source.type}
                      </span>
                      <span className="rounded border border-line-strong px-1.5 py-0.5 text-[11px] font-semibold text-ink-dim">
                        {source.tier}
                      </span>
                    </div>
                    <div className="mt-1.5 truncate text-ink-mid">
                      {source.category} · {source.language}
                    </div>
                    <div className="readout mt-1 truncate text-ink-dim">
                      {source.fetch_interval_min} min · {crawlLimitLabel}
                    </div>
                  </td>
                  <td className="min-w-0 px-4 py-3 text-xs">
                    <StatusDot label={health.text} tone={health.tone} />
                    <div className="readout mt-1.5 text-ink-dim">
                      成功率 {(source.success_rate * 100).toFixed(0)}%
                    </div>
                    <div className="readout text-ink-dim">错误 {source.error_count}</div>
                  </td>
                  <td className="min-w-0 px-4 py-3 text-xs">
                    <button
                      className={`flex w-full flex-col items-start gap-0.5 rounded border px-2.5 py-1.5 text-left font-semibold hover:opacity-80 disabled:cursor-default ${RESULT_BUTTON_TONE[summary.tone]}`}
                      disabled={!test}
                      onClick={() => setViewingResultFor(source.id)}
                      type="button"
                    >
                      <span className="w-full truncate">{summary.text}</span>
                      {test?.at ? (
                        <span className="readout text-[10px] font-normal opacity-75">{formatTime(test.at)}</span>
                      ) : null}
                      {test ? <span className="text-[10px] font-normal underline decoration-dotted opacity-80">查看详情</span> : null}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1.5 text-xs font-semibold">
                      <button
                        className={`flex-1 rounded border px-2 py-1.5 ${
                          source.is_active
                            ? "border-line text-ink-mid hover:border-danger/40 hover:text-danger"
                            : "border-success/40 text-success hover:bg-success/10"
                        }`}
                        disabled={busy?.id === source.id}
                        onClick={() => toggle(source)}
                        type="button"
                      >
                        {busy?.id === source.id && busy.kind === "toggle" ? (
                          <Loader2 aria-hidden className="mx-auto h-3.5 w-3.5 animate-spin" strokeWidth={2.5} />
                        ) : source.is_active ? (
                          "停用"
                        ) : (
                          "启用"
                        )}
                      </button>
                      <button
                        className="flex-1 rounded border border-line px-2 py-1.5 text-ink-mid hover:border-signal/40 hover:text-signal disabled:cursor-wait disabled:opacity-70"
                        disabled={busy?.id === source.id}
                        onClick={() => manualFetch(source)}
                        type="button"
                      >
                        {busy?.id === source.id && busy.kind === "fetch" ? (
                          <Loader2 aria-hidden className="mx-auto h-3.5 w-3.5 animate-spin" strokeWidth={2.5} />
                        ) : (
                          "抓取"
                        )}
                      </button>
                      <button
                        className="flex-1 rounded border border-line px-2 py-1.5 text-ink-mid hover:border-signal/40 hover:text-signal disabled:cursor-wait disabled:opacity-70"
                        disabled={busy?.id === source.id}
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
      </TableShell>

      {hoverCard ? (
        <div
          className="pointer-events-none fixed z-50 max-w-sm rounded-md border border-line-strong bg-panel-soft px-3 py-2 text-xs shadow-lg"
          style={{
            top: hoverCard.top,
            left: hoverCard.left,
            transform: hoverCard.flip ? "translateY(-100%)" : undefined,
          }}
        >
          <div className="font-semibold text-ink">{hoverCard.source.name}</div>
          <div className="readout mt-1 break-all text-ink-dim">{hoverCard.source.url}</div>
        </div>
      ) : null}

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
              <label className="block text-xs text-ink-dim">
                每轮抓取条数（留空/0 = 默认 5 条）
                <input
                  className="readout mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink"
                  defaultValue={Number(editing.config?.crawl_limit ?? "") || ""}
                  name="crawl_limit"
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

      {viewingResultFor && testResults[viewingResultFor] ? (
        (() => {
          const source = initialSources.find((candidate) => candidate.id === viewingResultFor);
          const result = testResults[viewingResultFor];
          const articles = result.articles ?? [];
          return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
              <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-md border border-line bg-panel">
                <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
                  <div>
                    <h2 className="text-lg font-semibold text-ink">
                      抓取结果 · {source?.name ?? viewingResultFor}
                    </h2>
                    <p className="mt-1 text-xs text-ink-dim">
                      {result.origin === "auto" ? "来自最近一次自动同步" : "来自手动抓取"}
                      {result.at ? ` · ${formatTime(result.at)}` : ""}
                      {result.status === "ok" ? ` · 共抓到 ${result.fetched_count ?? articles.length} 篇` : " · 本次抓取失败"}
                    </p>
                  </div>
                  <button
                    className="rounded border border-line px-3 py-1.5 text-sm text-ink-mid hover:text-ink"
                    onClick={() => setViewingResultFor(null)}
                    type="button"
                  >
                    关闭
                  </button>
                </div>
                <div className="overflow-y-auto px-6 py-4">
                  {result.status === "failed" ? (
                    <div className="rounded border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-200">
                      {result.error ?? "未知错误"}
                    </div>
                  ) : articles.length > 0 ? (
                    <ol className="space-y-1.5">
                      {articles.map((article, index) => {
                        const outcome = article.outcome ? OUTCOME_LABEL[article.outcome] : null;
                        return (
                          <li
                            key={`${article.url}-${index}`}
                            className="rounded px-2 py-2 text-sm hover:bg-panel-soft"
                          >
                            <div className="flex items-start gap-3">
                              <span className="readout mt-0.5 shrink-0 text-xs text-ink-dim">
                                {String(index + 1).padStart(2, "0")}
                              </span>
                              <a
                                className="min-w-0 flex-1 truncate text-ink hover:text-signal"
                                href={article.url}
                                rel="noreferrer"
                                target="_blank"
                                title={article.title}
                              >
                                {article.title}
                              </a>
                              {outcome ? (
                                <span className="shrink-0">
                                  <Pill tone={outcome.tone}>{outcome.text}</Pill>
                                </span>
                              ) : null}
                              {typeof article.final_score === "number" ? (
                                <span className="readout shrink-0 text-xs text-ink-dim">
                                  {Math.round(article.final_score)}
                                </span>
                              ) : null}
                            </div>
                            {article.reason ? (
                              <p className="ml-7 mt-1 text-xs text-ink-dim">
                                {article.category ? `${article.category} · ` : ""}
                                {article.reason}
                              </p>
                            ) : null}
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <p className="px-2 py-4 text-sm text-ink-dim">这一轮没有抓到任何文章。</p>
                  )}
                </div>
              </div>
            </div>
          );
        })()
      ) : null}
    </div>
  );
}
