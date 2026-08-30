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
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="bookmarks" />
        <MobileNav activeNavId="bookmarks" />

        <section className="min-w-0 px-4 pb-10 pt-4 md:px-8 md:py-10 xl:px-12">
          <div className="mx-auto max-w-5xl">
            <header className="border-b border-line-strong pb-5">
              <p className="readout text-[11px] uppercase tracking-[0.16em] text-signal">PERSONAL ARCHIVE</p>
              <h1 className="editorial-rule-title mt-4 text-4xl font-medium leading-none text-ink md:text-6xl">收藏</h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-ink-mid">
                收藏过的内容都在这里。收藏保存在本设备的浏览器里，换设备或清除浏览器数据后需要重新收藏。
              </p>
            </header>

            {status === "loading" ? (
              <div className="mt-6 rounded-md border border-line bg-panel p-6 text-center text-sm text-ink-dim">
                正在加载收藏内容…
              </div>
            ) : events.length === 0 ? (
              <div className="mt-6 rounded-md border border-line bg-panel p-6 text-center text-sm text-ink-dim">
                还没有收藏任何内容。在动态旁点击收藏图标即可保存到这里。
              </div>
            ) : (
              <div className="mt-6">
                {prunedCount > 0 ? (
                  <p className="text-xs text-ink-dim">
                    有 {prunedCount} 条收藏内容已下线或找不到了，已自动清理。
                  </p>
                ) : null}
                <div className={prunedCount > 0 ? "mt-3" : ""}>
                  {events.map((item) => (
                    <article
                      key={item.event_id}
                      className="card-hover editorial-feed-hover -mt-px border-x-0 border-y border-line bg-panel p-4 first:mt-0 hover:z-10"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs text-ink-mid">{sourceLine(item)}</div>
                          <h3 className="mt-1.5 text-base font-semibold leading-6 text-ink">
                            <a className="title-link" href={eventHref(item)}>
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
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
