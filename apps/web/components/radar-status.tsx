function formatClock(value?: string | null) {
  if (!value) {
    return "--:--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(parsed)
    .replace(/\//g, ".");
}

export function RadarStatus({
  updatedAt,
  eventCount,
  scope,
}: {
  updatedAt?: string | null;
  eventCount: number;
  scope: string;
}) {
  const live = Boolean(updatedAt);
  return (
    <div className="readout flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-line pb-3 text-xs uppercase tracking-[0.14em] text-ink-dim">
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className={`h-1.5 w-1.5 rounded-full ${live ? "bg-signal" : "bg-ink-dim"}`}
        />
        <span className={live ? "text-signal" : undefined}>SIGNAL</span>
      </span>
      <span>{scope}</span>
      <span className="text-ink-mid">{eventCount} EVENTS</span>
      <span>UPDATED {formatClock(updatedAt)}</span>
    </div>
  );
}
