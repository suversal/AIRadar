import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { articleSanitizeSchema } from "@/lib/sanitize-schema";

const inlineComponents: Components = {
  p({ node: _node, ...props }) {
    return <p className="break-words text-[17px] leading-8 text-ink [overflow-wrap:anywhere]" {...props} />;
  },
  a({ node: _node, ...props }) {
    return (
      <a
        className="break-words text-signal underline decoration-signal/40 underline-offset-4 [overflow-wrap:anywhere] hover:text-signal-bright"
        rel="noreferrer"
        target="_blank"
        {...props}
      />
    );
  },
  strong({ node: _node, ...props }) {
    return <strong className="font-semibold text-ink" {...props} />;
  },
  em({ node: _node, ...props }) {
    return <em {...props} />;
  },
  code({ node: _node, ...props }) {
    return (
      <code
        className="rounded border border-line-strong bg-panel-soft px-1.5 py-0.5 text-[15px] text-signal-bright"
        {...props}
      />
    );
  },
  span({ node: _node, ...props }) {
    return <span {...props} />;
  },
};

/** Renders one extracted paragraph, preserving sanitized inline markup
 *  (links, bold, emphasis, code, color) when the crawler captured any. */
export function RichParagraph({ text, html }: { text: string; html?: string }) {
  if (!html) {
    return <p className="break-words text-[17px] leading-8 text-ink [overflow-wrap:anywhere]">{text}</p>;
  }
  return (
    <ReactMarkdown
      components={inlineComponents}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, articleSanitizeSchema]]}
      skipHtml={false}
    >
      {html}
    </ReactMarkdown>
  );
}
