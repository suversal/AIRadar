import { notFound } from "next/navigation";
import { adminFetch } from "@/lib/admin-api";
import { editorDocumentHtml, type EditorDocument } from "@/lib/editor-document";
import { AdminShell } from "../../admin-shell";

export const metadata = { title: "草稿预览 · AI·RADAR 管理后台" };
export const dynamic = "force-dynamic";

type DraftPreview = {
  id: string;
  original_url?: string | null;
  editor_document?: EditorDocument;
  manual_fields?: Record<string, unknown>;
  extracted_fields?: Record<string, unknown>;
  ai_fields?: Record<string, unknown>;
  processing_status?: string;
  last_error_detail?: string | null;
};

function text(fields: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = fields[key];
    if (value != null && String(value).trim()) return String(value);
  }
  return "";
}

function stamp(value: string) {
  if (!value) return "未填写发布时间";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

export default async function DraftPreviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const response = await adminFetch(
    `/api/admin/article-submissions/${encodeURIComponent(id)}`,
  );
  if (response.status === 404) notFound();

  return (
    <AdminShell
      active="drafts"
      title="草稿预览"
      subtitle="按文章详情效果检查标题、摘要和正文；预览不会发布内容"
    >
      {!response.ok ? (
        <div className="rounded-md border border-danger/40 bg-danger/10 p-5 text-sm text-danger">
          草稿数据不可用（{response.status}）。
        </div>
      ) : (
        <DraftArticle submission={(await response.json()) as DraftPreview} />
      )}
    </AdminShell>
  );
}

function DraftArticle({ submission }: { submission: DraftPreview }) {
  const manual = submission.manual_fields ?? {};
  const extracted = submission.extracted_fields ?? {};
  const ai = submission.ai_fields ?? {};
  const title =
    text(manual, "title", "title_zh") ||
    text(ai, "title_zh") ||
    text(extracted, "title") ||
    "未命名草稿";
  const summary =
    text(manual, "summary_zh") ||
    text(ai, "summary_zh") ||
    text(manual, "one_line_summary") ||
    text(ai, "one_line_summary");
  const author = text(manual, "author") || text(extracted, "author") || "未填写作者";
  const publishedAt =
    text(manual, "published_at") || text(extracted, "published_at");
  const category = text(manual, "category") || text(ai, "category") || "未分类";
  const tags = Array.isArray(manual.tags)
    ? manual.tags
    : Array.isArray(ai.tags)
      ? ai.tags
      : [];
  const html = editorDocumentHtml(submission.editor_document);
  const extractedContent = text(extracted, "content");

  return (
    <article className="mx-auto max-w-3xl rounded-md border border-line bg-panel p-5 md:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-dim">
        <span>{author} · {stamp(publishedAt)} · {category}</span>
        <span>{submission.processing_status === "failed" ? "处理失败" : "草稿预览"}</span>
      </div>
      <h1 className="mt-4 text-2xl font-semibold leading-tight text-ink md:text-3xl">
        {title}
      </h1>
      {submission.original_url ? (
        <a
          className="mt-3 block break-all text-sm text-signal hover:text-signal-bright"
          href={submission.original_url}
          rel="noopener noreferrer"
          target="_blank"
        >
          {submission.original_url}
        </a>
      ) : null}
      {summary ? (
        <section className="mt-5 rounded-md border border-line-strong bg-panel-soft p-4">
          <h2 className="text-xs font-semibold text-signal">摘要</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-mid">{summary}</p>
        </section>
      ) : null}
      {submission.last_error_detail ? (
        <p className="mt-5 rounded border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          {submission.last_error_detail}
        </p>
      ) : null}
      <section className="mt-6 border-t border-line pt-5">
        <h2 className="text-sm font-semibold text-ink-mid">正文</h2>
        {html ? (
          <div
            className="draft-preview-content mt-4 text-sm leading-7 text-ink-mid"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-ink-mid">
            {extractedContent || "正文尚未填写。"}
          </p>
        )}
      </section>
      {tags.length ? (
        <div className="mt-6 flex flex-wrap gap-2">
          {tags.map((tag) => (
            <span
              className="rounded border border-line bg-canvas px-2.5 py-1 text-xs text-ink-mid"
              key={String(tag)}
            >
              {String(tag)}
            </span>
          ))}
        </div>
      ) : null}
      <div className="mt-8 flex justify-end gap-3">
        <a className="rounded border border-line px-4 py-2 text-sm font-semibold text-ink-mid" href="/admin/drafts">
          返回草稿管理
        </a>
        <a
          className="rounded bg-signal px-4 py-2 text-sm font-semibold text-canvas"
          href={`/admin/drafts/new?id=${encodeURIComponent(submission.id)}`}
        >
          继续编辑
        </a>
      </div>
      <style>{`
        .draft-preview-content h1,.draft-preview-content h2,.draft-preview-content h3 {
          margin: 1.5rem 0 .75rem;
          color: var(--color-ink);
          font-weight: 600;
        }
        .draft-preview-content p,.draft-preview-content ul,.draft-preview-content ol,
        .draft-preview-content blockquote,.draft-preview-content pre,.draft-preview-content table {
          margin: .85rem 0;
        }
        .draft-preview-content ul { list-style: disc; padding-left: 1.5rem; }
        .draft-preview-content ol { list-style: decimal; padding-left: 1.5rem; }
        .draft-preview-content img { display: block; height: auto; max-width: 100%; }
        .draft-preview-content a { color: var(--color-signal); text-decoration: underline; }
        .draft-preview-content table { width: 100%; border-collapse: collapse; }
        .draft-preview-content th,.draft-preview-content td {
          border: 1px solid var(--color-line);
          padding: .5rem;
        }
      `}</style>
    </article>
  );
}
