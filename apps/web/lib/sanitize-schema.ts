import { defaultSchema } from "rehype-sanitize";

// backend only ever emits a validated <span style="color: ..."> wrapper (see
// _color_from_attrs / _safe_color_value in article_content.py) - the default
// sanitize schema strips `style` entirely, so it must be explicitly allowed
// here for that one tag. Shared by RichParagraph (extracted blocks) and
// MarkdownArticle (GitHub README markdown) so both keep inline color intact.
export const articleSanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    span: [...(defaultSchema.attributes?.span ?? []), "style"],
  },
};
