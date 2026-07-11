import type { ReactNode } from "react";

export type Tone = "success" | "warning" | "danger" | "signal" | "neutral";

const PILL_TONE: Record<Tone, string> = {
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-danger/40 bg-danger/10 text-danger",
  signal: "border-signal/40 bg-signal/10 text-signal",
  neutral: "border-line text-ink-dim",
};

const DOT_TONE: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  signal: "bg-signal",
  neutral: "bg-ink-dim",
};

const TEXT_TONE: Record<Tone, string> = {
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  signal: "text-signal",
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
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${PILL_TONE[tone]}`}
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
