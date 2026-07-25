"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState, type ClipboardEvent } from "react";
import type { IJodit } from "jodit/esm/types/jodit";
import type { Config } from "jodit/esm/config";
import type { DeepPartial } from "jodit/esm/types";
import { proxiedImageUrl } from "@/lib/images";

import "jodit/es2021/jodit.min.css";

const JoditEditor = dynamic(() => import("jodit-react"), { ssr: false });

type Submission = {
  id: string;
  publication_status: "draft" | "published";
  processing_status: "idle" | "fetching" | "scoring" | "ready" | "failed";
  original_url?: string | null;
  editor_document?: { type?: string; html?: string; content?: unknown[] };
  manual_fields?: Record<string, unknown>;
  selection_mode?: "auto" | "force_selected";
  last_error_detail?: string | null;
  ai_fields?: Record<string, unknown>;
  raw_article_id?: string | null;
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

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`/api/admin-proxy/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ?? detail?.code ?? `请求失败（${response.status}）`,
    );
  }
  return payload;
}

function legacyDocumentToHtml(node?: Record<string, unknown>): string {
  if (!node) return "";
  if (node.type === "text") {
    let value = String(node.text ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
    for (const mark of (Array.isArray(node.marks) ? node.marks : []) as Array<Record<string, unknown>>) {
      const attrs = (mark.attrs ?? {}) as Record<string, unknown>;
      if (mark.type === "bold") value = `<strong>${value}</strong>`;
      else if (mark.type === "italic") value = `<em>${value}</em>`;
      else if (mark.type === "strike") value = `<del>${value}</del>`;
      else if (mark.type === "underline") value = `<u>${value}</u>`;
      else if (mark.type === "subscript") value = `<sub>${value}</sub>`;
      else if (mark.type === "superscript") value = `<sup>${value}</sup>`;
      else if (mark.type === "code") value = `<code>${value}</code>`;
      else if (mark.type === "link" && attrs.href) value = `<a href="${String(attrs.href)}">${value}</a>`;
      else if (mark.type === "textStyle") {
        const style = [attrs.color ? `color:${attrs.color}` : "", attrs.fontSize ? `font-size:${attrs.fontSize}` : ""].filter(Boolean).join(";");
        if (style) value = `<span style="${style}">${value}</span>`;
      } else if (mark.type === "highlight" && attrs.color) {
        value = `<mark style="background-color:${attrs.color}">${value}</mark>`;
      }
    }
    return value;
  }
  const children = Array.isArray(node.content)
    ? node.content.map((child) => legacyDocumentToHtml(child as Record<string, unknown>)).join("")
    : "";
  if (node.type === "doc") return children;
  if (node.type === "paragraph") return `<p>${children || "<br>"}</p>`;
  if (node.type === "heading") {
    const level = Math.max(1, Math.min(6, Number((node.attrs as { level?: number })?.level ?? 2)));
    return `<h${level}>${children}</h${level}>`;
  }
  if (node.type === "bulletList") return `<ul>${children}</ul>`;
  if (node.type === "orderedList") return `<ol>${children}</ol>`;
  if (node.type === "listItem") return `<li>${children}</li>`;
  if (node.type === "blockquote") return `<blockquote>${children}</blockquote>`;
  if (node.type === "codeBlock") return `<pre><code>${children}</code></pre>`;
  if (node.type === "horizontalRule") return "<hr>";
  if (node.type === "hardBreak") return "<br>";
  if (node.type === "image") {
    const attrs = (node.attrs ?? {}) as { src?: string; alt?: string; title?: string };
    return attrs.src
      ? `<img src="${attrs.src}" alt="${attrs.alt ?? ""}" title="${attrs.title ?? ""}">`
      : "";
  }
  return children;
}

function documentHtml(document?: Submission["editor_document"]) {
  if (!document) return "";
  if (document.type === "html") return String(document.html ?? "");
  return legacyDocumentToHtml(document as Record<string, unknown>);
}

const LAZY_IMAGE_ATTRIBUTES = [
  "data-original",
  "data-original-src",
  "data-actualsrc",
  "data-src",
  "data-lazy-src",
  "data-lazy",
  "data-url",
  "data-echo",
  "data-fallback-src",
] as const;

function bestSrcsetCandidate(value: string) {
  const candidates = value
    .split(",")
    .map((item) => item.trim().split(/\s+/)[0] ?? "")
    .filter(Boolean);
  return candidates.at(-1) ?? "";
}

/** Remote images are previewed through HotAI's existing anti-hotlink proxy,
 * while data-original keeps the source URL that the backend persists. */
function prepareEditorHtml(html: string, baseUrl = "") {
  if (!html || typeof window === "undefined") return html;
  const document = new DOMParser().parseFromString(html, "text/html");
  const resolvedBaseUrl = baseUrl || document.querySelector("base[href]")?.getAttribute("href") || "";

  for (const noscript of Array.from(document.querySelectorAll("noscript"))) {
    if (!/<img\b/i.test(noscript.textContent ?? "")) continue;
    const fragment = document.createRange().createContextualFragment(noscript.textContent ?? "");
    noscript.replaceWith(fragment);
  }
  for (const picture of Array.from(document.querySelectorAll("picture"))) {
    const image = picture.querySelector("img");
    const source = picture.querySelector("source[srcset], source[data-srcset]");
    if (image && source && !image.getAttribute("srcset") && !image.getAttribute("data-srcset")) {
      image.setAttribute(
        "data-srcset",
        source.getAttribute("data-srcset") ?? source.getAttribute("srcset") ?? "",
      );
    }
  }
  for (const image of Array.from(document.querySelectorAll("img"))) {
    const lazySource = LAZY_IMAGE_ATTRIBUTES
      .map((attribute) => image.getAttribute(attribute) ?? "")
      .find((value) => value && !value.startsWith("data:"));
    const srcset = image.getAttribute("data-srcset") ?? image.getAttribute("srcset") ?? "";
    let source = lazySource || bestSrcsetCandidate(srcset) || image.getAttribute("src") || "";
    if (source.startsWith("//")) source = `https:${source}`;
    try {
      source = new URL(source, resolvedBaseUrl || undefined).toString();
    } catch {
      image.remove();
      continue;
    }
    if (!source.startsWith("http://") && !source.startsWith("https://")) {
      image.remove();
      continue;
    }
    image.setAttribute("data-original", source);
    image.setAttribute("src", proxiedImageUrl(source));
    image.setAttribute("referrerpolicy", "no-referrer");
    image.removeAttribute("srcset");
    image.removeAttribute("data-srcset");
    for (const attribute of LAZY_IMAGE_ATTRIBUTES) {
      if (attribute !== "data-original") image.removeAttribute(attribute);
    }
  }
  return document.body.innerHTML;
}

function datetimeLocal(value: unknown) {
  if (!value) return "";
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return "";
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function ManualArticleEditor({
  imageUploadEnabled,
  initialSubmissionId,
}: {
  imageUploadEnabled: boolean;
  initialSubmissionId?: string;
}) {
  const editorRef = useRef<IJodit | null>(null);
  const contentRef = useRef("");
  const loadedId = useRef<string | null>(null);
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [originalUrl, setOriginalUrl] = useState("");
  const [title, setTitle] = useState("");
  const [oneLineSummary, setOneLineSummary] = useState("");
  const [summary, setSummary] = useState("");
  const [author, setAuthor] = useState("");
  const [publishedAt, setPublishedAt] = useState("");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");
  const [forceSelected, setForceSelected] = useState(false);
  const isPublished = submission?.publication_status === "published";

  const config = useMemo<DeepPartial<Config>>(
    () => ({
      readonly: false,
      theme: "dark",
      height: 560,
      minHeight: 360,
      toolbarAdaptive: false,
      askBeforePasteHTML: false,
      askBeforePasteFromWord: false,
      processPasteHTML: true,
      processPasteFromWord: true,
      defaultActionOnPaste: "insert_as_html" as const,
      defaultActionOnPasteFromWord: "insert_as_html" as const,
      cleanHTML: {
        denyTags: "script,iframe,object,embed,form,input,button,svg",
        removeEventAttributes: true,
        safeJavaScriptLink: true,
        safeLinksTarget: true,
        allowedStyles: {
          "*": [
            "background-color", "color", "font-family", "font-size", "font-style",
            "font-weight", "letter-spacing", "line-height", "text-align",
            "text-decoration", "text-indent", "vertical-align", "white-space",
          ],
          img: ["height", "max-width", "width"],
        },
      },
      placeholder: "直接编写正文，或从博客页面复制后粘贴到这里…",
      uploader: imageUploadEnabled
        ? {
            url: "/api/admin-upload-image",
            method: "POST",
            format: "json",
            filesVariableName: () => "file",
            insertImageAsBase64URI: false,
            imagesExtensions: ["jpg", "jpeg", "png", "gif", "webp"],
            isSuccess: (response: { src?: string }) => Boolean(response?.src),
            getMessage: (response: { detail?: { message?: string } | string }) =>
              typeof response?.detail === "string"
                ? response.detail
                : response?.detail?.message ?? "图片上传失败",
            process: (response: { src: string }) => ({
              files: [response.src],
              path: "",
              baseurl: "",
              isImages: [true],
            }),
          }
        : { insertImageAsBase64URI: false },
    }),
    [imageUploadEnabled],
  );

  useEffect(() => {
    if (!initialSubmissionId || loadedId.current === initialSubmissionId) return;
    loadedId.current = initialSubmissionId;
    setBusy(true);
    void api(`article-submissions/${initialSubmissionId}`)
      .then((item: Submission) => {
        const fields = item.manual_fields ?? {};
        setSubmission(item);
        setOriginalUrl(String(item.original_url ?? ""));
        const loadedContent = prepareEditorHtml(
          documentHtml(item.editor_document),
          String(item.original_url ?? ""),
        );
        contentRef.current = loadedContent;
        setContent(loadedContent);
        setTitle(String(fields.title ?? fields.title_zh ?? ""));
        setOneLineSummary(String(fields.one_line_summary ?? ""));
        setSummary(String(fields.summary_zh ?? ""));
        setAuthor(String(fields.author ?? ""));
        setPublishedAt(datetimeLocal(fields.published_at));
        setCategory(String(fields.category ?? ""));
        setTags(Array.isArray(fields.tags) ? fields.tags.join(", ") : "");
        setForceSelected(item.selection_mode === "force_selected");
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "草稿加载失败"))
      .finally(() => setBusy(false));
  }, [initialSubmissionId]);

  function manualFields() {
    return {
      title: title.trim(),
      one_line_summary: oneLineSummary.trim(),
      summary_zh: summary.trim(),
      author: author.trim(),
      published_at: publishedAt ? new Date(publishedAt).toISOString() : "",
      category,
      tags: tags.split(/[,，\s]+/).map((value) => value.trim()).filter(Boolean),
    };
  }

  async function saveDraft() {
    const html = contentRef.current || content;
    const payload = {
      original_url: originalUrl.trim() || null,
      editor_document: { type: "html", html },
      manual_fields: manualFields(),
      selection_mode: forceSelected ? "force_selected" : "auto",
    };
    if (submission) {
      return api(`article-submissions/${submission.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    }
    return api("article-submissions", { method: "POST", body: JSON.stringify(payload) });
  }

  async function waitUntilFinished(id: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const status = await api(`article-submissions/${id}/status`);
      if (status.publication_status === "published" || status.processing_status === "failed") {
        return api(`article-submissions/${id}`);
      }
    }
    throw new Error("处理超时，请稍后回到草稿管理查看状态");
  }

  async function saveOnly() {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await saveDraft();
      setSubmission(saved);
      const savedContent = prepareEditorHtml(
        documentHtml(saved.editor_document),
        String(saved.original_url ?? originalUrl),
      );
      contentRef.current = savedContent;
      setContent(savedContent);
      setMessage("草稿已保存。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "草稿保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function scoreAndEnterContent() {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await saveDraft();
      setSubmission(saved);
      await api(`article-submissions/${saved.id}/process`, { method: "POST" });
      const processed = await waitUntilFinished(saved.id);
      setSubmission(processed);
      setMessage(
        processed.publication_status === "published"
          ? "AI 评分完成，文章已进入内容管理并默认隐藏；审核后取消隐藏即可对外展示。"
          : processed.last_error_detail ?? "AI 评分失败，草稿仍然保留。",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "AI 评分失败");
    } finally {
      setBusy(false);
    }
  }

  function handlePasteCapture(event: ClipboardEvent<HTMLDivElement>) {
    const html = event.clipboardData.getData("text/html");
    if (!html) return;
    const clipboardPageUrl = (
      event.clipboardData.getData("text/uri-list")
      || event.clipboardData.getData("text/x-moz-url").split("\n")[0]
    )
      .split("\n")
      .map((value) => value.trim())
      .find((value) => value && !value.startsWith("#")) ?? "";
    const normalized = prepareEditorHtml(html, originalUrl || clipboardPageUrl);
    event.preventDefault();
    event.stopPropagation();
    editorRef.current?.s.insertHTML(normalized);
  }

  const ai = submission?.ai_fields ?? {};
  const previewTitle = title || String(ai.title_zh ?? "");
  const previewSummary = summary || String(ai.summary_zh ?? "");
  const editorConfig = useMemo<DeepPartial<Config>>(
    () => ({ ...config, readonly: isPublished }),
    [config, isPublished],
  );

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-line bg-panel p-5">
        <label className="block text-sm text-ink-mid">
          原文链接 <span className="text-ink-dim">（可选）</span>
          <input className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-ink" disabled={isPublished} onChange={(event) => setOriginalUrl(event.target.value)} placeholder="有原文则填写 https://...；原创文章可留空" type="url" value={originalUrl} />
        </label>
      </section>

      <section className="rounded-md border border-line bg-panel p-5">
        <h2 className="font-semibold text-ink">人工字段（留空由 AI 补全）</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <label className="text-xs text-ink-dim">标题<input className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setTitle(event.target.value)} value={title} /></label>
          <label className="text-xs text-ink-dim">一句话摘要<input className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setOneLineSummary(event.target.value)} value={oneLineSummary} /></label>
          <label className="text-xs text-ink-dim">作者<input className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setAuthor(event.target.value)} value={author} /></label>
          <label className="text-xs text-ink-dim">原文发布时间<input className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setPublishedAt(event.target.value)} type="datetime-local" value={publishedAt} /></label>
          <label className="text-xs text-ink-dim">分类<select className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setCategory(event.target.value)} value={category}><option value="">留空由 AI 分类</option>{CATEGORY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="text-xs text-ink-dim">标签<input className="mt-1 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setTags(event.target.value)} placeholder="逗号分隔" value={tags} /></label>
        </div>
        <label className="mt-3 block text-xs text-ink-dim">详细摘要<textarea className="mt-1 min-h-24 w-full rounded border border-line bg-canvas px-3 py-2 text-sm text-ink" disabled={isPublished} onChange={(event) => setSummary(event.target.value)} value={summary} /></label>
      </section>

      <section className="rounded-md border border-line bg-panel p-3" onPasteCapture={handlePasteCapture}>
        <p className="mb-3 text-xs leading-5 text-ink-dim">
          粘贴博客正文会保留标题、字号、颜色、列表、表格及原始图片链接；编辑器内手动上传图片才会使用配置的图床。
        </p>
        <JoditEditor
          editorRef={(instance) => {
            editorRef.current = instance;
          }}
          value={content}
          config={editorConfig}
          onBlur={(value) => {
            contentRef.current = value;
            setContent(value);
          }}
          onChange={(value) => {
            contentRef.current = value;
          }}
        />
        <style jsx global>{`
          .jodit-wysiwyg img {
            display: block;
            height: auto;
            max-width: 100%;
          }
        `}</style>
      </section>

      <section className="rounded-md border border-line bg-panel p-5">
        <label className="flex items-center gap-2 text-sm font-semibold text-ink"><input checked={forceSelected} disabled={isPublished} onChange={(event) => setForceSelected(event.target.checked)} type="checkbox" />手动精选（仍保留真实 AI 分数）</label>
        {submission ? (
          <div className="mt-4 rounded border border-line bg-canvas p-4 text-sm text-ink-mid">
            <div>状态：{submission.processing_status} / {submission.publication_status}</div>
            {previewTitle ? <h3 className="mt-3 text-lg font-semibold text-ink">{previewTitle}</h3> : null}
            {previewSummary ? <p className="mt-2 leading-6">{previewSummary}</p> : null}
          </div>
        ) : null}
        {message ? <p className="mt-4 rounded border border-line bg-canvas px-3 py-2 text-sm text-ink-mid">{message}</p> : null}
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <a className="rounded border border-line px-4 py-2 text-sm font-semibold text-ink-mid" href="/admin/drafts">返回草稿管理</a>
          <button className="rounded border border-line px-4 py-2 text-sm font-semibold text-ink-mid disabled:opacity-40" disabled={busy || isPublished} onClick={saveOnly} type="button">保存草稿</button>
          <button className="rounded bg-signal px-4 py-2 text-sm font-semibold text-canvas disabled:opacity-40" disabled={busy || isPublished} onClick={scoreAndEnterContent} type="button">{busy ? "处理中…" : "保存内容并生成 AI 评分"}</button>
        </div>
      </section>
    </div>
  );
}
