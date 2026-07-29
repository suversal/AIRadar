export type EditorDocument = {
  type?: string;
  html?: string;
  content?: unknown[];
  [key: string]: unknown;
};

function escapeHtml(value: unknown) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineHtml(value: unknown) {
  if (!value || typeof value !== "object") return "";
  const item = value as { text?: unknown; html?: unknown };
  return String(item.html ?? escapeHtml(item.text));
}

export function legacyDocumentToHtml(node?: Record<string, unknown>): string {
  if (!node) return "";
  if (node.type === "text") {
    let value = escapeHtml(node.text);
    for (const mark of (Array.isArray(node.marks) ? node.marks : []) as Array<
      Record<string, unknown>
    >) {
      const attrs = (mark.attrs ?? {}) as Record<string, unknown>;
      if (mark.type === "bold") value = `<strong>${value}</strong>`;
      else if (mark.type === "italic") value = `<em>${value}</em>`;
      else if (mark.type === "strike") value = `<del>${value}</del>`;
      else if (mark.type === "underline") value = `<u>${value}</u>`;
      else if (mark.type === "subscript") value = `<sub>${value}</sub>`;
      else if (mark.type === "superscript") value = `<sup>${value}</sup>`;
      else if (mark.type === "code") value = `<code>${value}</code>`;
      else if (mark.type === "link" && attrs.href) {
        value = `<a href="${escapeHtml(attrs.href)}">${value}</a>`;
      } else if (mark.type === "textStyle") {
        const style = [
          attrs.color ? `color:${String(attrs.color)}` : "",
          attrs.fontSize ? `font-size:${String(attrs.fontSize)}` : "",
        ]
          .filter(Boolean)
          .join(";");
        if (style) value = `<span style="${style}">${value}</span>`;
      } else if (mark.type === "highlight" && attrs.color) {
        value = `<mark style="background-color:${String(attrs.color)}">${value}</mark>`;
      }
    }
    return value;
  }
  const children = Array.isArray(node.content)
    ? node.content
        .map((child) => legacyDocumentToHtml(child as Record<string, unknown>))
        .join("")
    : "";
  if (node.type === "doc") return children;
  if (node.type === "paragraph") return `<p>${children || "<br>"}</p>`;
  if (node.type === "heading") {
    const level = Math.max(
      1,
      Math.min(6, Number((node.attrs as { level?: number })?.level ?? 2)),
    );
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
      ? `<img src="${escapeHtml(attrs.src)}" alt="${escapeHtml(attrs.alt)}" title="${escapeHtml(attrs.title)}">`
      : "";
  }
  return children;
}

export function editorDocumentHtml(document?: EditorDocument | null) {
  if (!document) return "";
  if (document.type === "html") return String(document.html ?? "");
  return legacyDocumentToHtml(document);
}

export function contentBlocksToHtml(blocks?: unknown[]) {
  return (blocks ?? [])
    .map((value) => {
      if (!value || typeof value !== "object") return "";
      const block = value as Record<string, unknown>;
      const type = String(block.type ?? "");
      if (type === "paragraph") {
        return `<p>${String(block.html ?? escapeHtml(block.text)) || "<br>"}</p>`;
      }
      if (type === "heading") {
        const level = Math.max(1, Math.min(6, Number(block.level ?? 2)));
        return `<h${level}>${String(block.html ?? escapeHtml(block.text))}</h${level}>`;
      }
      if (type === "image" && block.url) {
        return `<p><img src="${escapeHtml(block.url)}" alt="${escapeHtml(block.alt)}"></p>`;
      }
      if (type === "list") {
        const tag = block.ordered ? "ol" : "ul";
        const items = Array.isArray(block.items)
          ? block.items.map((item) => `<li>${inlineHtml(item)}</li>`).join("")
          : "";
        return `<${tag}>${items}</${tag}>`;
      }
      if (type === "code") {
        return `<pre><code>${escapeHtml(block.text)}</code></pre>`;
      }
      if (type === "table") {
        const headers = Array.isArray(block.headers)
          ? `<thead><tr>${block.headers.map((item) => `<th>${inlineHtml(item)}</th>`).join("")}</tr></thead>`
          : "";
        const rows = Array.isArray(block.rows)
          ? block.rows
              .map((row) =>
                Array.isArray(row)
                  ? `<tr>${row.map((item) => `<td>${inlineHtml(item)}</td>`).join("")}</tr>`
                  : "",
              )
              .join("")
          : "";
        return `<table>${headers}<tbody>${rows}</tbody></table>`;
      }
      if (type === "divider") return "<hr>";
      if (type === "video" && block.url) {
        return `<p><a href="${escapeHtml(block.url)}">${escapeHtml(block.title || block.url)}</a></p>`;
      }
      if (type === "social_embed" && block.url) {
        return `<blockquote>${escapeHtml(block.text)}<p><a href="${escapeHtml(block.url)}">${escapeHtml(block.url)}</a></p></blockquote>`;
      }
      if (type === "source_list" && Array.isArray(block.links)) {
        return `<ul>${block.links
          .map((link) => {
            const item = link as Record<string, unknown>;
            return `<li><a href="${escapeHtml(item.url)}">${escapeHtml(item.label || item.url)}</a></li>`;
          })
          .join("")}</ul>`;
      }
      return block.text ? `<p>${escapeHtml(block.text)}</p>` : "";
    })
    .join("");
}
