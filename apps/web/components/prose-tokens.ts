// Shared typography tokens for long-form article body content
// (/event/[id]). original-block.tsx (structured OriginalBlock[] path),
// rich-paragraph.tsx (inline markdown renderer used by both paths), and
// article-reading-toggle.tsx (raw-Markdown fallback path) all import from
// here so paragraph/list/code/heading styling can't drift apart again -
// this file has no imports of its own to avoid a cycle between the two
// component modules that both need these values.
//
// Use the site's CJK-optimized sans stack for body copy and the editorial
// serif only for article headings. Body ink is softened slightly from pure
// display ink so long dark-mode passages remain clear without glowing.

export const HEADING_CLASSNAMES: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
  1: "editorial-rule-title mt-10 text-[26px] lg:text-[30px] font-semibold leading-tight text-ink",
  2: "editorial-rule-title mt-9 border-b border-line pb-2.5 text-[22px] lg:text-[25px] font-semibold leading-tight text-ink",
  3: "editorial-rule-title mt-8 text-xl lg:text-[22px] font-semibold leading-snug text-ink",
  4: "editorial-rule-title mt-7 text-lg lg:text-[20px] font-semibold leading-snug text-ink",
  5: "editorial-rule-title mt-7 text-lg lg:text-[20px] font-semibold leading-snug text-ink",
  6: "editorial-rule-title mt-7 text-lg lg:text-[20px] font-semibold leading-snug text-ink",
};

export const PROSE_P_CLASSNAME =
  "break-words font-sans text-[15px] font-normal leading-7 tracking-[0.005em] text-ink/90 lg:text-[16px] lg:leading-[29px] [overflow-wrap:anywhere]";
export const PROSE_LIST_CLASSNAME =
  "ml-6 my-5 space-y-2 font-sans text-[15px] font-normal leading-7 tracking-[0.005em] text-ink/90 lg:text-[16px] lg:leading-[29px] marker:text-signal";
export const PROSE_CODE_INLINE_CLASSNAME =
  "rounded border border-line-strong bg-panel-soft px-1.5 py-0.5 text-[14px] lg:text-[15px] text-signal-bright";
export const PROSE_CODE_BLOCK_CLASSNAME =
  "my-7 max-w-full overflow-x-auto rounded-md border border-line-strong bg-panel-soft p-4 text-sm leading-6 text-ink";
