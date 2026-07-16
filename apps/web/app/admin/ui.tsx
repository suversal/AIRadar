"use client";

import {
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

export type Tone = "success" | "warning" | "danger" | "signal" | "info" | "neutral";

const PILL_TONE: Record<Tone, string> = {
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-danger/40 bg-danger/10 text-danger",
  signal: "border-signal/40 bg-signal/10 text-signal",
  info: "border-info/40 bg-info/10 text-info",
  neutral: "border-line text-ink-dim",
};

const DOT_TONE: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  signal: "bg-signal",
  info: "bg-info",
  neutral: "bg-ink-dim",
};

const TEXT_TONE: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  signal: "text-signal",
  info: "text-info",
  neutral: "text-ink-dim",
};

/** Small rounded-full status chip — the one shape every table uses for
 * run status, article outcomes, and 精选/已隐藏 flags. */
export function Pill({
  tone,
  children,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold ${PILL_TONE[tone]}`}
      title={title}
    >
      {children}
    </span>
  );
}

/** Dot + label used for at-a-glance health/status reads (信源健康, 运行状态). */
export function StatusDot({
  tone,
  label,
  className = "",
}: {
  tone: Tone;
  label: ReactNode;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold ${TEXT_TONE[tone]} ${className}`}>
      <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${DOT_TONE[tone]}`} />
      {label}
    </span>
  );
}

/** Shared table shell: rounded panel border, horizontal scroll on overflow. */
export function TableShell({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-panel">{children}</div>
  );
}

/** Header row style shared by every admin table — quiet, tracked-out
 * caption type that reads as instrumentation rather than body copy. */
export const TABLE_HEAD_ROW = "border-b border-line-strong text-[11px] font-semibold uppercase tracking-wide text-ink-dim";

/** Body row hover — a faint lift so scanning a dense table has feedback
 * without adding zebra striping (which fights the hairline dividers). */
export const TABLE_ROW = "transition-colors hover:bg-panel-soft/60";

type HoverCardState<T> = { data: T; top: number; left: number; flip: boolean };

/** Positions a floating card via fixed viewport coordinates (measured from
 * the hovered element) instead of CSS-relative absolute positioning, so it
 * always renders in full even when the trigger sits inside a table wrapped
 * in `overflow-x-auto` (which per spec also clips overflow-y). */
export function useHoverCard<T>(delayMs = 0) {
  const [card, setCard] = useState<HoverCardState<T> | null>(null);
  const hideTimer = useRef<number | null>(null);
  const showTimer = useRef<number | null>(null);

  function cancelHide() {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }

  function cancelShow() {
    if (showTimer.current !== null) {
      window.clearTimeout(showTimer.current);
      showTimer.current = null;
    }
  }

  function show(event: ReactMouseEvent<HTMLElement>, data: T) {
    cancelHide();
    cancelShow();
    // capture the node now - event.currentTarget is nulled out once this
    // handler returns, so it can't be read from inside the delayed callback
    const target = event.currentTarget;
    const reveal = () => {
      const rect = target.getBoundingClientRect();
      const flip = rect.bottom + 90 > window.innerHeight;
      setCard({
        data,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 340)),
        top: flip ? rect.top - 8 : rect.bottom + 8,
        flip,
      });
    };
    if (delayMs > 0) {
      showTimer.current = window.setTimeout(reveal, delayMs);
    } else {
      reveal();
    }
  }

  // 延迟关闭:给鼠标留出从触发元素移入卡片的走廊,悬停卡片时取消关闭,
  // 这样卡片里的 URL 可以选中复制
  function hide() {
    cancelShow();
    cancelHide();
    hideTimer.current = window.setTimeout(() => setCard(null), 200);
  }

  useEffect(() => () => {
    cancelHide();
    cancelShow();
  }, []);

  return { card, show, hide, cancelHide };
}

/** Renders whatever `useHoverCard` is currently showing — mount once per table.
 * Pass the hook's cancelHide/hide so the card survives the pointer moving
 * into it (and text inside stays selectable for copying). */
export function HoverCard<T>({
  card,
  render,
  onMouseEnter,
  onMouseLeave,
}: {
  card: HoverCardState<T> | null;
  render: (data: T) => ReactNode;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}) {
  if (!card) return null;
  return (
    <div
      className="fixed z-50 max-w-sm select-text rounded-md border border-line-strong bg-panel-soft px-3 py-2 text-xs shadow-lg"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{
        top: card.top,
        left: card.left,
        transform: card.flip ? "translateY(-100%)" : undefined,
      }}
    >
      {render(card.data)}
    </div>
  );
}
