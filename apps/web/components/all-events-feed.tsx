"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LatestEvent } from "@/lib/api";
import { formatTime, groupEventsByDate } from "@/lib/event-format";
import { formatScore, searchEvents } from "@/lib/events";
import { focusCategory } from "@/lib/taxonomy";
import { DateGroupSection } from "@/components/date-group-section";
import { EventCard, EventTimelineRow } from "@/components/event-card";

const DAYS = 30;
const PAGE_SIZE = 50;

// maps the source registry's real category (official/research/community/
// media, see apps/api/app/data/default_sources.py) to this page's three
// filter buckets, instead of guessing from the source display name - a name
// heuristic missed real community sources whose name doesn't literally say
// "reddit"/"x.com"/etc. (e.g. "X 推文 (AttentionVC)")
const SOURCE_CATEGORY_TO_BUCKET: Record<string, string> = {
  official: "first_party",
  research: "first_party",
  community: "community",
  media: "news",
};

function sourceBucket(item: LatestEvent) {
  const category = item.main_source?.category;
  if (category && category in SOURCE_CATEGORY_TO_BUCKET) {
    return SOURCE_CATEGORY_TO_BUCKET[category];
  }
  return "news";
}

function sortByPublishedAtDesc(items: LatestEvent[]) {
  return [...items].sort((left, right) => {
    const leftTime = left.published_at ? new Date(left.published_at).getTime() : 0;
    const rightTime = right.published_at ? new Date(right.published_at).getTime() : 0;
    return rightTime - leftTime;
  });
}


function representativeImage(item: LatestEvent) {
  return item.original_images?.[0];
}

function tagHref(tag: string) {
  return `/all?${new URLSearchParams({ tag })}`;
}

function matchesExactTag(item: LatestEvent, selectedTag: string) {
  const normalized = selectedTag.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return (item.tags ?? []).some((tag) => tag.trim().toLowerCase() === normalized);
}

export function AllEventsFeed({
  initialItems,
  initialTotal,
  topic,
  tag,
  selectedSource,
  selectedCategory,
  query,
  paginationPath = "/api/all-events",
  paginationParams = {},
  emptyMessage = "当前筛选条件下没有 AI 动态。",
  completeLabel = `近 ${DAYS} 天全部`,
}: {
  initialItems: LatestEvent[];
  initialTotal: number;
  topic: string;
  tag: string;
  selectedSource: string;
  selectedCategory: string;
  query: string;
  paginationPath?: string;
  paginationParams?: Record<string, string>;
  emptyMessage?: string;
  completeLabel?: string;
}) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const filteredItems = useMemo(() => {
    const searched = searchEvents(items, query);
    return sortByPublishedAtDesc(
      searched.filter((item) => {
        const sourceMatches = selectedSource ? sourceBucket(item) === selectedSource : true;
        const categoryMatches = selectedCategory
          ? focusCategory(item.focus_category, item.scoring_category) === selectedCategory
          : true;
        return sourceMatches && categoryMatches && matchesExactTag(item, tag);
      }),
    );
  }, [items, query, selectedSource, selectedCategory, tag]);

  // /all 的日期头用完整中文("8月20日"),与 /latest 的 "8/20" 是刻意差异
  const dateGroups = useMemo(() => groupEventsByDate(filteredItems, "long"), [filteredItems]);
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
  const paginationQuery = new URLSearchParams(paginationParams).toString();

  const loadMore = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setLoadError(null);
    try {
      const params = new URLSearchParams({
        days: String(DAYS),
        limit: String(PAGE_SIZE),
        offset: String(itemsRef.current.length),
      });
      if (topic) {
        params.set("topic", topic);
      }
      if (selectedCategory) {
        params.set("focus", selectedCategory);
      }
      if (selectedSource) {
        params.set("source", selectedSource);
      }
      if (tag) {
        params.set("tag", tag);
      }
      if (query) {
        params.set("q", query);
      }
      new URLSearchParams(paginationQuery).forEach((value, key) => params.set(key, value));
      const response = await fetch(`${paginationPath}?${params}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`请求失败（${response.status}）`);
      }
      const payload = (await response.json()) as { items: LatestEvent[]; total: number };
      setItems((current) => [...current, ...payload.items]);
      setTotal(payload.total);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "加载更多失败");
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, [paginationPath, paginationQuery, query, selectedCategory, selectedSource, tag, topic]);

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
                  score={formatScore(item.final_score)}
                  image={representativeImage(item)}
                  tagHref={tagHref}
                  maxTags={5}
                  showReason={false}
                  hideImageOnMobile
                  openArticle
                />
              </EventTimelineRow>
            ))}
          </DateGroupSection>
        ))
      ) : (
        <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
          {emptyMessage}
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
        <p className="mt-6 text-center text-xs text-ink-dim">
          已显示{completeLabel} {total} 条动态
        </p>
      ) : null}
    </section>
  );
}
