import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "../admin-shell";
import { EventsManager, type AdminEvent } from "./events-manager";

export const metadata = {
  title: "内容管理 · AI·RADAR 管理后台",
};

const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

export default async function AdminEventsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; page?: string; page_size?: string }>;
}) {
  const params = await searchParams;
  const q = (params.q ?? "").trim();
  const requestedPageSize = Number(params.page_size ?? DEFAULT_PAGE_SIZE) || DEFAULT_PAGE_SIZE;
  const pageSize = PAGE_SIZE_OPTIONS.includes(requestedPageSize as (typeof PAGE_SIZE_OPTIONS)[number])
    ? requestedPageSize
    : DEFAULT_PAGE_SIZE;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const offset = (page - 1) * pageSize;

  const query = new URLSearchParams({ days: "30", limit: String(pageSize), offset: String(offset) });
  if (q) {
    query.set("q", q);
  }
  const response = await adminFetch(`/api/admin/events?${query}`);
  const payload = response.ok ? await response.json() : { items: [], total: 0 };
  const events: AdminEvent[] = payload.items ?? [];
  const total: number = payload.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

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
          q={q}
        />
      )}
    </AdminShell>
  );
}
