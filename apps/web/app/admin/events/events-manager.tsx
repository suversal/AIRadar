"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { HoverCard, Pill, TABLE_HEAD_ROW, TABLE_ROW, TableShell, useHoverCard } from "../ui";

export type AdminEvent = {
  event_id: string;
  title: string;
  category: string;
  category_label?: string;
  scoring_category?: string;
  scoring_category_label?: string;
  tags?: string[];
  final_score?: number;
  selected?: boolean;
  hidden?: boolean;
  published_at?: string;
  crawled_at?: string;
  main_source?: { id: string; name: string };
  original_url?: string;
};

const CATEGORY_OPTIONS = [
  ["model_release", "模型进展"],
  ["product_release", "产品应用"],
  ["open_source", "开源项目"],
  ["research", "研究评测"],
  ["industry", "行业事件"],
  ["funding", "资本动态"],
  ["opinion", "观点分析"],
  ["tutorial", "教程实践"],
] as const;

type StatusFilter = "all" | "visible" | "hidden" | "selected" | "unselected";
type SortBy = "published_at" | "crawled_at";
type SortDirection = "asc" | "desc";

function formatStamp(value?: string) {
  if (!value) return "--";
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

export function EventsManager({
  initialEvents,
  page,
  pageSize,
  totalPages,
  total,
  title,
  category,
  sourceId,
  status,
  sortBy,
  sortDirection,
  sources,
}: {
  initialEvents: AdminEvent[];
  page: number;
  pageSize: number;
  totalPages: number;
  total: number;
  title: string;
  category: string;
  sourceId: string;
  status: StatusFilter;
  sortBy: SortBy;
  sortDirection: SortDirection;
  sources: { id: string; name: string; is_active: boolean }[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminEvent | null>(null);
  const [deletingEvent, setDeletingEvent] = useState<AdminEvent | null>(null);
  const [titleInput, setTitleInput] = useState(title);
  const [categoryInput, setCategoryInput] = useState(category);
  const [sourceInput, setSourceInput] = useState(sourceId);
  // 悬浮 1 秒后再展示,避免鼠标划过表格时到处弹卡片
  const titleHoverCard = useHoverCard<AdminEvent>(1000);

  const events = initialEvents;

  // 先启用后停用,同状态内按名称排序(中文按拼音),和信源管理列表保持一致，让下拉框可预期地定位
  const sortedSources = useMemo(
    () =>
      [...sources].sort((a, b) => {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        return a.name.localeCompare(b.name, "zh-CN");
      }),
    [sources],
  );

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

  async function deleteEvent(event: AdminEvent) {
    await run(event.event_id, async () => {
      await api(`events/${event.event_id}`, { method: "DELETE" });
      setDeletingEvent(null);
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

  function queryHref(
    nextPage: number,
    nextPageSize = pageSize,
    nextSortBy = sortBy,
    nextSortDirection = sortDirection,
  ) {
    const params = new URLSearchParams({
      page: String(nextPage),
      page_size: String(nextPageSize),
      sort_by: nextSortBy,
      sort_dir: nextSortDirection,
    });
    if (title) {
      params.set("title", title);
    }
    if (category) {
      params.set("category", category);
    }
    if (sourceId) {
      params.set("source_id", sourceId);
    }
    if (status !== "all") {
      params.set("status", status);
    }
    return `/admin/events?${params.toString()}`;
  }

  function sortHref(nextSortBy: SortBy) {
    const nextDirection =
      sortBy === nextSortBy && sortDirection === "desc" ? "asc" : "desc";
    return queryHref(1, pageSize, nextSortBy, nextDirection);
  }

  function sortIndicator(field: SortBy) {
    if (sortBy !== field) return "↕";
    return sortDirection === "desc" ? "↓" : "↑";
  }

  function clearHref() {
    const params = new URLSearchParams({
      page: "1",
      page_size: String(pageSize),
      sort_by: sortBy,
      sort_dir: sortDirection,
    });
    return `/admin/events?${params.toString()}`;
  }

  return (
    <div className="space-y-4">
      <section className="rounded-md border border-line bg-panel p-4">
        <form action="/admin/events" className="space-y-3" method="get">
          <input name="page" type="hidden" value="1" />
          <input name="page_size" type="hidden" value={pageSize} />
          <input name="sort_by" type="hidden" value={sortBy} />
          <input name="sort_dir" type="hidden" value={sortDirection} />
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_160px_180px_auto] md:items-end">
            <label className="block text-xs font-semibold text-ink-dim">
              标题
              <input
                className="mt-1 w-full rounded-md border border-line bg-canvas px-4 py-2 text-sm font-normal text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
                name="title"
                onChange={(event) => setTitleInput(event.target.value)}
                placeholder="按标题关键词搜索，可用空格分隔多个词"
                type="search"
                value={titleInput}
              />
            </label>
            <label className="block text-xs font-semibold text-ink-dim">
              主信源
              <select
                className="mt-1 w-full rounded-md border border-line bg-canvas px-4 py-2 text-sm font-normal text-ink outline-none focus:border-signal/60"
                name="source_id"
                onChange={(event) => setSourceInput(event.target.value)}
                value={sourceInput}
              >
                <option value="">全部主信源</option>
                {sortedSources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-semibold text-ink-dim">
              状态
              <select
                className="mt-1 w-full rounded-md border border-line bg-canvas px-4 py-2 text-sm font-normal text-ink outline-none focus:border-signal/60"
                defaultValue={status}
                name="status"
              >
                <option value="all">全部状态</option>
                <option value="visible">已展示</option>
                <option value="hidden">已隐藏</option>
                <option value="selected">已精选</option>
                <option value="unselected">未精选</option>
              </select>
            </label>
            <label className="block text-xs font-semibold text-ink-dim">
              分类
              <select
                className="mt-1 w-full rounded-md border border-line bg-canvas px-4 py-2 text-sm font-normal text-ink outline-none focus:border-signal/60"
                name="category"
                onChange={(event) => setCategoryInput(event.target.value)}
                value={categoryInput}
              >
                <option value="">全部分类</option>
                {CATEGORY_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-2">
              <a
                className="rounded-md border border-line px-3 py-2 text-sm text-ink-mid hover:border-signal/40 hover:text-signal"
                href={clearHref()}
              >
                清除
              </a>
              <button
                className="rounded-md border border-signal bg-signal px-4 py-2 text-sm font-semibold text-canvas hover:bg-signal-bright"
                type="submit"
              >
                搜索
              </button>
            </div>
          </div>
          <p className="text-xs text-ink-dim">
            标题、分类和主信源会同时生效；当前按
            {sortBy === "published_at" ? "发布时间" : "抓取时间"}
            {sortDirection === "desc" ? "倒序" : "正序"}排列，点击时间表头可切换。
          </p>
        </form>
      </section>

      <div className="flex flex-wrap items-center justify-end gap-3">
        <p className="text-xs text-ink-dim">
          隐藏立即从全部动态与详情页消失；影响精选日报需再点仪表盘"刷新最新日报"
        </p>
      </div>

      {message ? (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          {message}
        </div>
      ) : null}

      <TableShell>
        <table className="w-full table-fixed text-left text-sm">
          <thead>
            <tr className={TABLE_HEAD_ROW}>
              <th className="w-[29%] px-4 py-3 font-semibold">标题</th>
              <th className="w-[11%] px-4 py-3 font-semibold">来源</th>
              <th className="w-[9%] px-4 py-3 font-semibold">分类</th>
              <th className="w-[6%] px-4 py-3 text-right font-semibold">评分</th>
              <th
                aria-sort={sortBy === "published_at" ? (sortDirection === "desc" ? "descending" : "ascending") : "none"}
                className="w-[10%] px-4 py-3 font-semibold"
              >
                <a className="inline-flex items-center gap-1 hover:text-signal" href={sortHref("published_at")}>
                  发布时间 <span aria-hidden>{sortIndicator("published_at")}</span>
                </a>
              </th>
              <th
                aria-sort={sortBy === "crawled_at" ? (sortDirection === "desc" ? "descending" : "ascending") : "none"}
                className="w-[10%] px-4 py-3 font-semibold"
              >
                <a className="inline-flex items-center gap-1 hover:text-signal" href={sortHref("crawled_at")}>
                  抓取时间 <span aria-hidden>{sortIndicator("crawled_at")}</span>
                </a>
              </th>
              <th className="w-[10%] px-4 py-3 font-semibold">状态</th>
              <th className="w-[15%] px-4 py-3 font-semibold">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {events.map((event) => (
              <tr key={event.event_id} className={`align-top text-ink-mid ${TABLE_ROW}`}>
                <td className="min-w-0 px-4 py-3">
                  <div
                    className="w-fit max-w-full"
                    onMouseEnter={(mouseEvent) => titleHoverCard.show(mouseEvent, event)}
                    onMouseLeave={titleHoverCard.hide}
                  >
                    <a
                      className={`block truncate text-sm font-semibold hover:text-signal ${
                        event.hidden ? "text-ink-dim line-through" : "text-ink"
                      }`}
                      href={`/event/${encodeURIComponent(event.event_id)}${
                        event.hidden ? "?admin_preview=1" : ""
                      }`}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {event.title}
                    </a>
                    {event.tags?.length ? (
                      <div className="mt-1 truncate text-xs text-ink-dim">{event.tags.join(" / ")}</div>
                    ) : null}
                  </div>
                </td>
                <td className="min-w-0 px-4 py-3 text-xs" title={event.main_source?.name}>
                  <span className="block truncate">{event.main_source?.name ?? "--"}</span>
                </td>
                <td className="min-w-0 px-4 py-3 text-xs">
                  <span
                    className="block truncate rounded bg-panel-soft px-2 py-0.5 text-ink-mid"
                    title={event.scoring_category_label ?? event.scoring_category ?? event.category}
                  >
                    {event.scoring_category_label ?? event.scoring_category ?? event.category}
                  </span>
                </td>
                <td className="readout px-4 py-3 text-right text-xs text-ink-dim">
                  {event.final_score != null ? Math.round(event.final_score) : "--"}
                </td>
                <td className="readout px-4 py-3 text-xs text-ink-dim">
                  <div className="truncate">{formatStamp(event.published_at)}</div>
                </td>
                <td className="readout px-4 py-3 text-xs text-ink-dim">
                  <div className="truncate">{formatStamp(event.crawled_at)}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col items-start gap-1">
                    {event.selected ? <Pill tone="signal">精选</Pill> : null}
                    {event.hidden ? <Pill tone="danger">已隐藏</Pill> : null}
                    {!event.selected && !event.hidden ? <span className="text-xs text-ink-dim">--</span> : null}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-nowrap gap-1.5 text-xs font-semibold">
                    <button
                      className={`shrink-0 whitespace-nowrap rounded border px-2.5 py-1 ${
                        event.hidden
                          ? "border-success/40 text-success hover:bg-success/10"
                          : "border-line text-ink-mid hover:border-danger/40 hover:text-danger"
                      }`}
                      disabled={busy === event.event_id}
                      onClick={() => toggleHidden(event)}
                      type="button"
                    >
                      {event.hidden ? "恢复" : "隐藏"}
                    </button>
                    <button
                      className="shrink-0 whitespace-nowrap rounded border border-line px-2.5 py-1 text-ink-mid hover:border-signal/40 hover:text-signal"
                      onClick={() => setEditing(event)}
                      type="button"
                    >
                      编辑
                    </button>
                    <button
                      className="shrink-0 whitespace-nowrap rounded border border-line px-2.5 py-1 text-ink-mid hover:border-danger/40 hover:text-danger"
                      disabled={busy === event.event_id}
                      onClick={() => setDeletingEvent(event)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {events.length === 0 ? (
              <tr>
                <td className="px-4 py-8 text-sm text-ink-dim" colSpan={8}>
                  当前筛选下没有事件。
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </TableShell>

      <HoverCard
        card={titleHoverCard.card}
        onMouseEnter={titleHoverCard.cancelHide}
        onMouseLeave={titleHoverCard.hide}
        render={(event) => (
          <>
            <div className="font-semibold text-ink">{event.title}</div>
            {event.tags?.length ? (
              <div className="mt-1 text-ink-dim">{event.tags.join(" / ")}</div>
            ) : null}
          </>
        )}
      />

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-panel px-4 py-3 text-sm text-ink-mid">
        <span className="readout text-xs text-ink-dim">
          共 {total} 篇 · 第 {page}/{totalPages} 页
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <form action="/admin/events" className="flex items-center gap-2 text-xs text-ink-dim" method="get">
            <input name="title" type="hidden" value={title} />
            <input name="category" type="hidden" value={category} />
            <input name="source_id" type="hidden" value={sourceId} />
            <input name="status" type="hidden" value={status} />
            <input name="sort_by" type="hidden" value={sortBy} />
            <input name="sort_dir" type="hidden" value={sortDirection} />
            <input name="page" type="hidden" value="1" />
            每页
            <select
              className="rounded border border-line bg-canvas px-2 py-1 text-ink"
              defaultValue={pageSize}
              name="page_size"
              onChange={(event) => event.currentTarget.form?.requestSubmit()}
            >
              {[10, 20, 50, 100].map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </form>
          <form action="/admin/events" className="flex items-center gap-2 text-xs text-ink-dim" method="get">
            <input name="title" type="hidden" value={title} />
            <input name="category" type="hidden" value={category} />
            <input name="source_id" type="hidden" value={sourceId} />
            <input name="status" type="hidden" value={status} />
            <input name="sort_by" type="hidden" value={sortBy} />
            <input name="sort_dir" type="hidden" value={sortDirection} />
            <input name="page_size" type="hidden" value={pageSize} />
            跳至
            <input
              className="readout w-16 rounded border border-line bg-canvas px-2 py-1 text-ink"
              defaultValue={page}
              max={totalPages}
              min={1}
              name="page"
              type="number"
            />
            <button className="rounded border border-line px-2 py-1 hover:border-signal/40 hover:text-signal" type="submit">
              前往
            </button>
          </form>
          <a
            aria-disabled={page <= 1}
            className={`rounded border border-line px-4 py-1.5 ${
              page <= 1 ? "pointer-events-none opacity-40" : "hover:border-signal/40 hover:text-signal"
            }`}
            href={queryHref(page - 1)}
          >
            上一页
          </a>
          <a
            aria-disabled={page >= totalPages}
            className={`rounded border border-line px-4 py-1.5 ${
              page >= totalPages ? "pointer-events-none opacity-40" : "hover:border-signal/40 hover:text-signal"
            }`}
            href={queryHref(page + 1)}
          >
            下一页
          </a>
        </div>
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
                  defaultValue={editing.scoring_category ?? editing.category}
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

      {deletingEvent ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="w-full max-w-md rounded-md border border-line bg-panel p-6">
            <h2 className="text-lg font-semibold text-ink">删除文章</h2>
            <p className="mt-3 text-sm text-ink-mid">
              确定要彻底删除这篇文章吗？此操作不可恢复。
            </p>
            <p className="mt-2 truncate text-sm font-semibold text-ink" title={deletingEvent.title}>
              {deletingEvent.title}
            </p>
            {message ? (
              <p className="mt-3 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                {message}
              </p>
            ) : null}
            <div className="mt-5 flex justify-end gap-3 text-sm font-semibold">
              <button
                className="rounded border border-line px-4 py-2 text-ink-mid hover:text-ink"
                onClick={() => setDeletingEvent(null)}
                type="button"
              >
                取消
              </button>
              <button
                className="rounded border border-danger bg-danger px-4 py-2 text-canvas hover:bg-danger/90"
                disabled={busy === deletingEvent.event_id}
                onClick={() => deleteEvent(deletingEvent)}
                type="button"
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
