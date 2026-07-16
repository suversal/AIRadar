import { notFound } from "next/navigation";
import { AdminShell } from "../../admin-shell";
import { ManualArticleEditor } from "../../events/new/manual-article-editor";

export const metadata = { title: "编辑文章草稿 · AI·RADAR 管理后台" };
export const dynamic = "force-dynamic";

function enabled(name: string) {
  return (process.env[name] ?? "false").toLowerCase() === "true";
}

export default async function NewDraftPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  if (!enabled("ADMIN_MANUAL_ARTICLE_ENABLED")) notFound();
  const params = await searchParams;
  return (
    <AdminShell
      active="drafts"
      title={params.id ? "编辑文章草稿" : "新增文章草稿"}
      subtitle="保存草稿不会进入内容流；生成 AI 评分成功后自动进入内容管理并默认隐藏"
    >
      <ManualArticleEditor
        imageUploadEnabled={enabled("ADMIN_MANUAL_IMAGE_UPLOAD_ENABLED")}
        initialSubmissionId={params.id}
      />
    </AdminShell>
  );
}
