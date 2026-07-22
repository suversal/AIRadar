import type { ReactNode } from "react";
import type { LatestEvent } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { proxiedImageUrl } from "@/lib/images";
import { BookmarkButton } from "@/components/bookmark-button";

export function EventCard({
  item,
  sourceLine,
  score,
  image,
  tagHref,
  maxTags = 5,
  clampSummary = false,
  alwaysSelected = false,
}: {
  item: LatestEvent;
  sourceLine: string;
  score: string;
  image?: { url: string; alt?: string };
  tagHref: (tag: string) => string;
  maxTags?: number;
  clampSummary?: boolean;
  // /latest 页面本身就是"精选"信息流,后端不总是逐条回填 selected 字段——
  // 这里允许调用方明确声明"本页面下的条目都算精选",而不是依赖可能缺失的
  // item.selected,避免徽章在 /latest 上意外消失
  alwaysSelected?: boolean;
}) {
  return (
    <article className="card-hover rounded-md border border-line bg-panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-xs text-ink-mid">{sourceLine}</div>
          <h2 className="mt-1.5 text-base font-semibold leading-6 text-ink">
            <a className="hover:text-signal" href={eventHref(item)}>{item.title}</a>
          </h2>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {alwaysSelected || item.selected ? (
            <span className="rounded-full border border-signal/60 bg-signal/15 px-2.5 py-0.5 text-xs font-semibold text-signal-bright">
              精选
            </span>
          ) : null}
          <span className="readout rounded-full border border-signal/40 px-2.5 py-0.5 text-xs font-semibold text-signal">
            评分 {score}
          </span>
          <BookmarkButton eventId={item.event_id} />
        </div>
      </div>

      <p className={`mt-3 text-sm leading-6 text-ink-mid ${clampSummary ? "line-clamp-3" : ""}`}>
        {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
      </p>

      {image ? (
        // 外链图必须走代理 + no-referrer：带 localhost Referer 会被各家
        // CDN 防盗链 403（详情页同款处理，实测案例：极客邦 CDN）
        <img
          alt={image.alt ?? item.title}
          className="mt-3 max-h-72 w-full max-w-xl rounded-md border border-line object-cover"
          src={proxiedImageUrl(image.url)}
          referrerPolicy="no-referrer"
        />
      ) : null}

      {item.tags?.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.tags.slice(0, maxTags).map((tag) => (
            <a
              key={tag}
              href={tagHref(tag)}
              className="rounded-md bg-panel-soft px-3 py-1.5 text-xs text-ink-mid transition hover:bg-line hover:text-signal-bright"
            >
              {tag}
            </a>
          ))}
        </div>
      ) : null}

      {item.reason ? (
        <div className="mt-4 border-t border-line pt-3">
          <p className="rounded-md bg-signal/10 px-3 py-2.5 text-sm leading-6 text-signal-bright">
            <span className="font-semibold">推荐理由：</span>
            {item.reason}
          </p>
        </div>
      ) : null}
    </article>
  );
}

/** 时间线一行：时间戳 + 圆点。移动端与卡片头部同排展示（紧凑内联），
 *  桌面端维持独立的时间列 + 时间轴圆点，避免手机上时间独占一整行占用滚动空间。 */
export function EventTimelineRow({ time, children }: { time: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5 md:grid-cols-[64px_1fr] md:gap-2">
      <div className="readout relative flex items-center gap-2 text-sm font-semibold text-ink md:block md:text-lg">
        <span className="h-2 w-2 shrink-0 rounded-full border border-signal bg-canvas md:absolute md:-left-[35px] md:top-1.5 md:h-2.5 md:w-2.5" />
        {time}
      </div>
      {children}
    </div>
  );
}
