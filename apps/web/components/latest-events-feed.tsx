"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LatestEvent } from "@/lib/api";
import { searchEvents } from "@/lib/events";
import { focusCategory } from "@/lib/taxonomy";
import { DateGroupSection } from "@/components/date-group-section";
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
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(parsed);
}

function formatWeekday(value?: string) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", { weekday: "long" }).format(parsed);
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
    weekday: formatWeekday(events[0]?.published_at),
    events,
  }));
}

function sourceLine(item: LatestEvent) {
  const source = item.main_source?.name ?? "未知来源";
  return `${source} · ${item.source_count ?? 1} 个来源`;
}

function representativeImage(item: LatestEvent) {
  return item.original_images?.[0];
}

function tagHref(tag: string) {
  return `/latest?${new URLSearchParams({ tag })}`;
}

function matchesExactTag(item: LatestEvent, selectedTag: string) {
  const normalized = selectedTag.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return (item.tags ?? []).some((tag) => tag.trim().toLowerCase() === normalized);
}

export function LatestEventsFeed({
  initialItems,
  initialTotal,
  tag,
  selectedCategory,
  query,
}: {
  initialItems: LatestEvent[];
  initialTotal: number;
  tag: string;
  selectedCategory: string;
  query: string;
}) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const filteredItems = useMemo(() => {
    const searched = searchEvents(items, query);
    return searched.filter((item) => {
      const categoryMatches = selectedCategory
        ? focusCategory(item.focus_category, item.scoring_category) === selectedCategory
        : true;
      return categoryMatches && matchesExactTag(item, tag);
    });
  }, [items, query, selectedCategory, tag]);

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
      if (selectedCategory) {
        params.set("focus", selectedCategory);
      }
      if (tag) {
        params.set("tag", tag);
      }
      if (query) {
        params.set("q", query);
      }
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
  }, [query, selectedCategory, tag]);

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
    <section className="mt-3 md:mt-6">
      {dateGroups.length > 0 ? (
        dateGroups.map((group) => (
          <DateGroupSection
            key={group.dateLabel}
            dateLabel={group.dateLabel}
            weekday={group.weekday}
            count={group.events.length}
          >
            {group.events.map((item) => (
              <EventTimelineRow key={item.event_id} time={formatTime(item.published_at)}>
                <EventCard
                  item={item}
                  sourceLine={sourceLine(item)}
                  score={formatScore(item.final_score)}
                  image={representativeImage(item)}
                  tagHref={tagHref}
                  maxTags={4}
                  clampSummary
                  alwaysSelected
                />
              </EventTimelineRow>
            ))}
          </DateGroupSection>
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
              <p className="text-xs text-danger">{loadError}</p>
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
