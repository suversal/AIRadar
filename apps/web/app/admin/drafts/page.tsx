import { notFound } from "next/navigation";
import { adminFetch } from "@/lib/admin-api";
import { AdminShell } from "../admin-shell";
import { DraftsManager, type ArticleDraft } from "./drafts-manager";

export const metadata = { title: "草稿管理 · AI·RADAR 管理后台" };
export const dynamic = "force-dynamic";

function enabled(name: string) {
  return (process.env[name] ?? "false").toLowerCase() === "true";
}

export default async function AdminDraftsPage() {
  if (!enabled("ADMIN_MANUAL_ARTICLE_ENABLED")) notFound();
  const response = await adminFetch(
    "/api/admin/article-submissions?publication_status=draft&limit=200",
  );
  const payload = response.ok ? await response.json() : { items: [] };
  return (
    <AdminShell
      active="drafts"
      title="草稿管理"
      subtitle="在这里新增、续写和保存草稿；AI 评分成功后文章自动进入内容管理并保持隐藏"
    >
      {!response.ok ? (
        <div className="rounded-md border border-red-400/40 bg-red-400/10 p-5 text-sm text-red-200">
          草稿数据不可用（{response.status}）。
        </div>
      ) : (
        <DraftsManager initialDrafts={(payload.items ?? []) as ArticleDraft[]} />
      )}
    </AdminShell>
  );
}
