import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "../admin-shell";
import { SourcesManager, type AdminSource } from "./sources-manager";

export const metadata = {
  title: "信源管理 · AI·RADAR 管理后台",
};

export default async function AdminSourcesPage() {
  const response = await adminFetch("/api/admin/sources");
  const sources: AdminSource[] = response.ok ? (await response.json()).sources : [];

  return (
    <AdminShell
      active="sources"
      title="信源管理"
      subtitle="启停、编辑与试抓；改动即时生效于下一轮抓取"
    >
      {!response.ok ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 p-5 text-sm text-red-200">
          信源数据不可用（{response.status}）——数据库模式未启用或认证失效。
        </div>
      ) : (
        <SourcesManager initialSources={sources} />
      )}
    </AdminShell>
  );
}
