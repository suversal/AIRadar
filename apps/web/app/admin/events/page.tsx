import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "../admin-shell";
import { EventsManager, type AdminEvent } from "./events-manager";

export const metadata = {
  title: "内容修正 · AI·RADAR 管理后台",
};

export default async function AdminEventsPage() {
  const response = await adminFetch("/api/admin/events?days=30");
  const events: AdminEvent[] = response.ok ? (await response.json()).items : [];

  return (
    <AdminShell
      active="events"
      title="内容修正"
      subtitle="隐藏错误内容、修正 AI 的分类/标题/标签（近 30 天）"
    >
      {!response.ok ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 p-5 text-sm text-red-200">
          事件数据不可用（{response.status}）——数据库模式未启用或认证失效。
        </div>
      ) : (
        <EventsManager initialEvents={events} />
      )}
    </AdminShell>
  );
}
