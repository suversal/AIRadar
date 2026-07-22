"use client";

import { useEffect, useState } from "react";
import type { LatestEvent } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { Sidebar } from "@/components/sidebar";
import { MobileNav } from "@/components/mobile-nav";
import { BookmarkButton } from "@/components/bookmark-button";
import { getBookmarkIds, removeBookmark } from "@/lib/bookmarks";

function sourceLine(item: LatestEvent) {
  const source = item.main_source?.name ?? "未知来源";
  return `${source} · ${item.source_count ?? 1} 个来源`;
}

export default function BookmarksPage() {
  const [status, setStatus] = useState<"loading" | "ready">("loading");
  const [events, setEvents] = useState<LatestEvent[]>([]);
  const [prunedCount, setPrunedCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const ids = getBookmarkIds();
      if (ids.length === 0) {
        if (!cancelled) {
          setEvents([]);
          setStatus("ready");
        }
        return;
      }
      const results = await Promise.all(
        ids.map(async (id) => {
          try {
            const response = await fetch(`/api/events/${encodeURIComponent(id)}`, { cache: "no-store" });
            if (!response.ok) {
              return { id, event: null as LatestEvent | null };
            }
            return { id, event: (await response.json()) as LatestEvent };
          } catch {
            return { id, event: null as LatestEvent | null };
          }
        }),
      );
      if (cancelled) {
        return;
      }
      // an id that no longer resolves (hidden, merged away, deleted) is
      // stale - prune it instead of showing a broken bookmark forever
      let pruned = 0;
      for (const result of results) {
        if (result.event === null) {
          removeBookmark(result.id);
          pruned += 1;
        }
      }
      setPrunedCount(pruned);
      setEvents(results.map((result) => result.event).filter((event): event is LatestEvent => event !== null));
      setStatus("ready");
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="bookmarks" />
        <MobileNav activeNavId="bookmarks" />

        <section className="px-5 py-8 md:px-10 xl:px-16">
          <div className="mx-auto max-w-4xl">
            <header className="py-6">
              <h1 className="text-2xl font-semibold text-ink">收藏</h1>
              <p className="mt-1.5 text-sm text-ink-mid">
                保存在这台设备的浏览器里，换设备或清除浏览器数据后需要重新收藏。
              </p>
            </header>

            {status === "loading" ? (
              <div className="rounded-md border border-line bg-panel p-8 text-center text-sm text-ink-dim">
                正在加载收藏内容…
              </div>
            ) : events.length === 0 ? (
              <div className="rounded-md border border-line bg-panel p-8 text-center text-sm text-ink-dim">
                还没有收藏任何内容。在动态旁点击收藏图标即可保存到这里。
              </div>
            ) : (
              <div className="space-y-4">
                {prunedCount > 0 ? (
                  <p className="text-xs text-ink-dim">
                    有 {prunedCount} 条收藏内容已下线或找不到了，已自动清理。
                  </p>
                ) : null}
                {events.map((item) => (
                  <article key={item.event_id} className="card-hover rounded-md border border-line bg-panel p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-xs text-ink-mid">{sourceLine(item)}</div>
                        <h3 className="mt-1.5 text-base font-semibold leading-6 text-ink">
                          <a className="hover:text-signal" href={eventHref(item)}>
                            {item.title}
                          </a>
                        </h3>
                      </div>
                      <BookmarkButton
                        eventId={item.event_id}
                        labeled
                        onChange={(bookmarked) => {
                          if (!bookmarked) {
                            setEvents((current) => current.filter((event) => event.event_id !== item.event_id));
                          }
                        }}
                      />
                    </div>
                    <p className="mt-2.5 line-clamp-2 text-sm leading-6 text-ink-mid">
                      {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
                    </p>
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
