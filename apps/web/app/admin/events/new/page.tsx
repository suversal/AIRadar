import { redirect } from "next/navigation";

export const metadata = { title: "新增文章 · AI·RADAR 管理后台" };
export const dynamic = "force-dynamic";

export default async function NewAdminArticlePage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const params = await searchParams;
  const suffix = params.id ? `?id=${encodeURIComponent(params.id)}` : "";
  redirect(`/admin/drafts/new${suffix}`);
}
