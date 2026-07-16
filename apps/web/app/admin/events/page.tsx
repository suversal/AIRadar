import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "../admin-shell";
import { EventsManager, type AdminEvent } from "./events-manager";

export const metadata = {
  title: "内容管理 · AI·RADAR 管理后台",
};

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const SORT_FIELDS = ["published_at", "crawled_at"] as const;
const SORT_DIRECTIONS = ["asc", "desc"] as const;

type SortBy = (typeof SORT_FIELDS)[number];
type SortDirection = (typeof SORT_DIRECTIONS)[number];
type StatusFilter = "all" | "visible" | "hidden" | "selected" | "unselected";

export default async function AdminEventsPage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string;
    title?: string;
    category?: string;
    source_id?: string;
    status?: string;
    sort_by?: string;
    sort_dir?: string;
    page?: string;
    page_size?: string;
  }>;
}) {
  const params = await searchParams;
  const title = (params.title ?? params.q ?? "").trim();
  const category = (params.category ?? "").trim();
  const sourceId = (params.source_id ?? "").trim();
  const status: StatusFilter = ["visible", "hidden", "selected", "unselected"].includes(
    params.status ?? "",
  )
    ? (params.status as StatusFilter)
    : "all";
  const sortBy = SORT_FIELDS.includes(params.sort_by as SortBy)
    ? (params.sort_by as SortBy)
    : "published_at";
  const sortDirection = SORT_DIRECTIONS.includes(params.sort_dir as SortDirection)
    ? (params.sort_dir as SortDirection)
    : "desc";
  const requestedPageSize = Number(params.page_size ?? DEFAULT_PAGE_SIZE) || DEFAULT_PAGE_SIZE;
  const pageSize = PAGE_SIZE_OPTIONS.includes(requestedPageSize as (typeof PAGE_SIZE_OPTIONS)[number])
    ? requestedPageSize
    : DEFAULT_PAGE_SIZE;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const offset = (page - 1) * pageSize;

  const query = new URLSearchParams({
    days: "30",
    limit: String(pageSize),
    offset: String(offset),
    sort_by: sortBy,
    sort_dir: sortDirection,
    status,
  });
  if (title) {
    query.set("title", title);
  }
  if (category) {
    query.set("category", category);
  }
  if (sourceId) {
    query.set("source_id", sourceId);
  }
  const [response, sourcesResponse] = await Promise.all([
    adminFetch(`/api/admin/events?${query}`),
    adminFetch("/api/admin/sources"),
  ]);
  const payload = response.ok ? await response.json() : { items: [], total: 0 };
  const sourcesPayload = sourcesResponse.ok ? await sourcesResponse.json() : { sources: [] };
  const events: AdminEvent[] = payload.items ?? [];
  const total: number = payload.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const sources: { id: string; name: string; is_active: boolean }[] = (
    sourcesPayload.sources ?? []
  ).map((source: { id: string; name: string; is_active: boolean }) => ({
    id: source.id,
    name: source.name,
    is_active: source.is_active,
  }));
  if (
    (process.env.ADMIN_MANUAL_ARTICLE_ENABLED ?? "false").toLowerCase() === "true"
    && !sources.some((source) => source.id === "hotai_manual")
  ) {
    sources.push({ id: "hotai_manual", name: "AI·RADAR 手动添加", is_active: false });
  }

  return (
    <AdminShell
      active="events"
      title="内容管理"
      subtitle={`近 30 天全部处理文章（共 ${total} 篇）· 隐藏错误内容、修正 AI 的分类/标题/标签`}
    >
      {!response.ok ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 p-5 text-sm text-red-200">
          事件数据不可用（{response.status}）——数据库模式未启用或认证失效。
        </div>
      ) : (
        <EventsManager
          initialEvents={events}
          page={page}
          pageSize={pageSize}
          totalPages={totalPages}
          total={total}
          title={title}
          category={category}
          sourceId={sourceId}
          status={status}
          sortBy={sortBy}
          sortDirection={sortDirection}
          sources={sources}
        />
      )}
    </AdminShell>
  );
}
