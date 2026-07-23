"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LatestEvent } from "@/lib/api";
import { searchEvents } from "@/lib/events";
import { displayCategory } from "@/lib/taxonomy";
import { ChevronDown } from "lucide-react";
import { EventCard, EventTimelineRow } from "@/components/event-card";

const PAGE_SIZE = 50;

function formatScore(score?: number) {
  if (typeof score !== "number") {
    return "--";
  }
  return Math.round(score).toString();
}

function formatDateKey(value?: string) {
  if (!value) {
    return "日期未知";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 10) || "日期未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(parsed);
}

function formatTime(value?: string) {
  if (!value) {
    return "--:--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "--:--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function groupEventsByDate(items: LatestEvent[]) {
  const groups = new Map<string, LatestEvent[]>();
  for (const item of items) {
    const key = formatDateKey(item.published_at);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return Array.from(groups.entries()).map(([dateLabel, events]) => ({
    dateLabel,
    events,
  }));
}

function sourceLine(item: LatestEvent) {
  const source = item.main_source?.name ?? "未知来源";
  return `${source} · ${item.source_count ?? 1} 个来源`;
}

// matches the pre-existing behavior of clicking a tag chip: it always
// searches by just that tag, not "current filters + tag". Kept local to
// this client component since functions (a prop the server component
// previously passed) can't cross the server/client boundary.
function tagHref(tag: string) {
  return `/latest?${new URLSearchParams({ q: tag })}`;
}

export function LatestEventsFeed({
  initialItems,
  initialTotal,
  selectedCategory,
  query,
}: {
  initialItems: LatestEvent[];
  initialTotal: number;
  selectedCategory: string;
  query: string;
}) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const filteredItems = useMemo(() => {
    const searched = searchEvents(items, query);
    return selectedCategory
      ? searched.filter((item) => displayCategory(item.category) === selectedCategory)
      : searched;
  }, [items, query, selectedCategory]);

  const dateGroups = useMemo(() => groupEventsByDate(filteredItems), [filteredItems]);
  const hasMore = items.length < total;

  // guards against IntersectionObserver firing loadMore twice for the same
  // page (e.g. one fetch still in flight when the sentinel re-triggers) -
  // `loading` state alone isn't enough since the observer callback closes
  // over whatever render it was created in, not necessarily the latest one
  const loadingRef = useRef(false);
  // itemsRef mirrors `items` so loadMore (stable via useCallback) always
  // reads the current offset without needing to be recreated on every
  // items change, which would otherwise re-trigger the observer effect
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const loadMore = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setLoadError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(itemsRef.current.length),
      });
      const response = await fetch(`/api/latest-events?${params}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`请求失败（${response.status}）`);
      }
      const payload = (await response.json()) as { items: LatestEvent[]; total?: number };
      setItems((current) => [...current, ...payload.items]);
      if (typeof payload.total === "number") {
        setTotal(payload.total);
      }
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "加载更多失败");
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, []);

  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hasMore) return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          loadMore();
        }
      },
      { rootMargin: "600px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loadMore]);

  return (
    <section className="mt-6">
      {dateGroups.length > 0 ? (
        dateGroups.map((group) => (
          <details key={group.dateLabel} open className="group">
            <summary className="sticky top-16 z-10 -mx-5 flex cursor-pointer list-none items-center gap-3 border-b border-line bg-canvas px-5 py-3 text-sm font-semibold text-ink-mid md:-mx-9 md:px-9 lg:top-0">
              <span>{group.dateLabel}</span>
              <span className="flex items-center gap-1 text-ink-dim">
                折叠
                <ChevronDown
                  aria-hidden
                  className="h-4 w-4 -rotate-90 transition-transform group-open:rotate-0"
                  strokeWidth={2}
                />
              </span>
              <span className="text-ink-dim">{group.events.length} 条</span>
            </summary>
            <div className="relative grid gap-3 md:border-l md:border-line md:pl-6">
              {group.events.map((item) => (
                <EventTimelineRow key={item.event_id} time={formatTime(item.published_at)}>
                  <EventCard
                    item={item}
                    sourceLine={sourceLine(item)}
                    score={formatScore(item.final_score)}
                    tagHref={tagHref}
                    maxTags={4}
                    clampSummary
                    alwaysSelected
                  />
                </EventTimelineRow>
              ))}
            </div>
          </details>
        ))
      ) : (
        <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
          当前分类没有精选内容。
        </div>
      )}

      {hasMore ? (
        <div ref={sentinelRef} className="mt-6 flex flex-col items-center gap-2 py-4">
          {loadError ? (
            <>
              <p className="text-xs text-red-300">{loadError}</p>
              <button
                type="button"
                onClick={loadMore}
                className="min-h-10 rounded-md border border-line bg-panel px-6 text-sm font-medium text-ink-mid transition hover:border-signal/40 hover:text-signal"
              >
                重试
              </button>
            </>
          ) : (
            <p className="text-xs text-ink-dim">
              {loading ? "加载中…" : `已显示 ${items.length} / ${total} 条`}
            </p>
          )}
        </div>
      ) : items.length > 0 ? (
        <p className="mt-6 text-center text-xs text-ink-dim">已显示近 7 天全部 {total} 条精选</p>
      ) : null}
    </section>
  );
}
