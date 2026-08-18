import type { ReactNode } from "react";
import type { LatestEvent } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { proxiedImageUrl } from "@/lib/images";
import { BookmarkButton } from "@/components/bookmark-button";

export function EventCard({
  item,
  score,
  image,
  tagHref,
  maxTags = 5,
  clampSummary = false,
  alwaysSelected = false,
  showReason = true,
  hideImageOnMobile = false,
}: {
  item: LatestEvent;
  score: string;
  image?: { url: string; alt?: string };
  tagHref: (tag: string) => string;
  maxTags?: number;
  clampSummary?: boolean;
  // /latest 页面本身就是"精选"信息流,后端不总是逐条回填 selected 字段——
  // 这里允许调用方明确声明"本页面下的条目都算精选",而不是依赖可能缺失的
  // item.selected,避免徽章在 /latest 上意外消失
  alwaysSelected?: boolean;
  // /all 页面混合展示精选与非精选条目,推荐理由是"精选"信息流(/latest)的专属
  // 内容,在混合流里不展示,调用方按页面语境显式控制
  showReason?: boolean;
  // /all 移动端信息密度优先于配图,桌面端保留
  hideImageOnMobile?: boolean;
}) {
  return (
    <article className="card-hover rounded-md border border-line bg-panel p-3 md:p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 truncate text-xs leading-5 text-ink-mid">
          {item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="readout inline-flex h-5 items-center justify-center rounded-full border border-signal/40 px-1.5 text-[11px] font-semibold leading-none text-signal">
            {score}
          </span>
          <BookmarkButton eventId={item.event_id} compact />
        </div>
      </div>
      <h2 className="mt-1.5 text-base font-semibold leading-6 text-ink md:mt-2">
        {alwaysSelected || item.selected ? (
          <span className="relative -top-px mr-1.5 inline-flex h-5 items-center justify-center rounded-full border border-signal/60 bg-signal/15 px-1.5 align-middle text-[11px] font-semibold leading-none text-signal-bright">
            精选
          </span>
        ) : null}
        <a className="title-link" href={eventHref(item)}>{item.title}</a>
      </h2>

      <p
        className={`mt-1 text-sm leading-6 text-ink-mid line-clamp-2 md:mt-2 ${
          clampSummary ? "md:line-clamp-3" : "md:line-clamp-none"
        }`}
      >
        {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
      </p>

      {image ? (
        // 外链图必须走代理 + no-referrer：带 localhost Referer 会被各家
        // CDN 防盗链 403（详情页同款处理，实测案例：极客邦 CDN）
        <img
          alt={image.alt ?? item.title}
          className={`mt-3 max-h-72 w-full max-w-xl rounded-md border border-line object-cover ${
            hideImageOnMobile ? "hidden md:block" : ""
          }`}
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

      {showReason && item.reason ? (
        <div className="mt-4 border-t border-line pt-3">
          <p className="rounded-md bg-signal/10 px-3 py-2.5 text-xs leading-5 text-signal-bright">
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
    <div className="grid grid-cols-1 gap-2 md:grid-cols-[64px_1fr]">
      <div className="readout relative flex items-center gap-2 text-sm font-semibold text-ink md:block md:text-lg">
        <span className="h-2 w-2 shrink-0 rounded-full bg-signal md:absolute md:-left-[30px] md:top-1.5 md:h-2.5 md:w-2.5" />
        {time}
      </div>
      {children}
    </div>
  );
}
