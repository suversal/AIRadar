import { AdminShell } from "../../../admin-shell";
import { ManualArticleEditor } from "../../new/manual-article-editor";

export const metadata = { title: "编辑内容 · AI·RADAR 管理后台" };
export const dynamic = "force-dynamic";

function enabled(name: string) {
  return (process.env[name] ?? "false").toLowerCase() === "true";
}

export default async function EditEventPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <AdminShell
      active="events"
      title="编辑内容"
      subtitle="可修改与草稿箱相同的标题、摘要、作者、时间、分类、标签和富文本正文"
    >
      <ManualArticleEditor
        imageUploadEnabled={enabled("ADMIN_MANUAL_IMAGE_UPLOAD_ENABLED")}
        initialEventId={id}
      />
    </AdminShell>
  );
}
