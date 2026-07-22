// Shared typography tokens for long-form article body content
// (/event/[id]). original-block.tsx (structured OriginalBlock[] path),
// rich-paragraph.tsx (inline markdown renderer used by both paths), and
// article-reading-toggle.tsx (raw-Markdown fallback path) all import from
// here so paragraph/list/code/heading styling can't drift apart again -
// this file has no imports of its own to avoid a cycle between the two
// component modules that both need these values.
//
// 15px/24px on phones+tablets, 18px/30px at lg (desktop, matches the site's
// existing lg:1024px layout breakpoint). HEADING_CLASSNAMES' lg: sizes are
// bumped in lockstep so h3~h6 don't collide with the 18px desktop body text.

export const HEADING_CLASSNAMES: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
  1: "mt-8 text-2xl lg:text-[28px] font-semibold leading-tight text-ink",
  2: "mt-7 border-b border-line pb-2 text-xl lg:text-[22px] font-semibold text-ink",
  3: "mt-6 text-lg lg:text-[20px] font-semibold text-ink",
  4: "mt-6 text-lg lg:text-[20px] font-semibold text-ink",
  5: "mt-6 text-lg lg:text-[20px] font-semibold text-ink",
  6: "mt-6 text-lg lg:text-[20px] font-semibold text-ink",
};

export const PROSE_P_CLASSNAME =
  "break-words text-[15px] leading-[24px] lg:text-[18px] lg:leading-[30px] text-ink [overflow-wrap:anywhere]";
export const PROSE_LIST_CLASSNAME =
  "ml-6 space-y-2 text-[15px] leading-[24px] lg:text-[18px] lg:leading-[30px] text-ink";
export const PROSE_CODE_INLINE_CLASSNAME =
  "rounded border border-line-strong bg-panel-soft px-1.5 py-0.5 text-[15px] lg:text-[16px] text-signal-bright";
export const PROSE_CODE_BLOCK_CLASSNAME =
  "max-w-full overflow-x-auto rounded-md border border-line-strong bg-panel-soft p-4 text-sm leading-6 text-ink";
