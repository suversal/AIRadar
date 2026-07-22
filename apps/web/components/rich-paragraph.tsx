import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import { articleSanitizeSchema } from "@/lib/sanitize-schema";
import { PROSE_CODE_INLINE_CLASSNAME, PROSE_P_CLASSNAME } from "@/components/prose-tokens";

const inlineComponents: Components = {
  p({ node: _node, ...props }) {
    return <p className={PROSE_P_CLASSNAME} {...props} />;
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
    return <strong className="font-semibold" {...props} />;
  },
  em({ node: _node, ...props }) {
    return <em {...props} />;
  },
  code({ node: _node, ...props }) {
    return <code className={PROSE_CODE_INLINE_CLASSNAME} {...props} />;
  },
  span({ node: _node, ...props }) {
    return <span {...props} />;
  },
};

const inlineOnlyComponents: Components = {
  ...inlineComponents,
  p({ node: _node, ...props }) {
    return <span {...props} />;
  },
};

export function RichInline({ text, html }: { text: string; html?: string }) {
  if (!html) return <>{text}</>;
  return (
    <ReactMarkdown
      components={inlineOnlyComponents}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, articleSanitizeSchema]]}
      skipHtml={false}
    >
      {html}
    </ReactMarkdown>
  );
}

/** Renders one extracted paragraph, preserving sanitized inline markup
 *  (links, bold, emphasis, code, color) when the crawler captured any. */
export function RichParagraph({
  text,
  html,
  className = PROSE_P_CLASSNAME,
}: {
  text: string;
  html?: string;
  className?: string;
}) {
  if (!html) {
    return <p className={className}>{text}</p>;
  }
  return (
    <ReactMarkdown
      components={{
        ...inlineComponents,
        p({ node: _node, ...props }) {
          return <p className={className} {...props} />;
        },
      }}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, articleSanitizeSchema]]}
      skipHtml={false}
    >
      {html}
    </ReactMarkdown>
  );
}
