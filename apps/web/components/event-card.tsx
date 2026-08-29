import type { ReactNode } from "react";
import type { LatestEvent } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { proxiedImageUrl } from "@/lib/images";
import { BookmarkButton } from "@/components/bookmark-button";
import { Sparkles } from "lucide-react";

export function EventCard({
  item,
  score,
  image,
  tagHref,
  maxTags = 5,
  clampSummary = false,
  showReason = true,
  hideImageOnMobile = false,
  openArticle = false,
}: {
  item: LatestEvent;
  score: string;
  image?: { url: string; alt?: string };
  tagHref: (tag: string) => string;
  maxTags?: number;
  clampSummary?: boolean;
  // /all 页面混合展示精选与非精选条目,推荐理由是"精选"信息流(/latest)的专属
  // 内容,在混合流里不展示,调用方按页面语境显式控制
  showReason?: boolean;
  // /all 移动端信息密度优先于配图,桌面端保留
  hideImageOnMobile?: boolean;
  // /latest 使用杂志式开放条目，避免重复卡片容器挤压正文与配图
  openArticle?: boolean;
}) {
  const authorProfile = item.main_source?.handle
    ? {
        name: item.main_source.display_name ?? item.main_source.handle,
        handle: item.main_source.handle,
      }
    : null;

  return (
    <article
      className={
        openArticle
          ? "group/event border-t border-line-strong pb-1 pt-3"
          : "card-hover editorial-feed-hover overflow-hidden border border-line bg-panel/45"
      }
    >
      <div className={openArticle ? "" : `grid ${image ? "2xl:grid-cols-[minmax(0,1fr)_220px]" : ""}`}>
        <div
          className={
            openArticle
              ? "min-w-0"
              : "min-w-0 p-4"
          }
        >
          <div className={`flex items-center justify-between gap-3 ${openArticle ? "" : "border-b border-line/70 pb-3"}`}>
            {authorProfile ? (
              <div className="flex min-w-0 items-center gap-1.5 text-sm">
                <span className="shrink-0 font-medium text-ink-mid">X ·</span>
                <span className="min-w-0 truncate font-semibold text-ink">
                  {authorProfile.name}
                </span>
                <span className="shrink-0 text-ink-mid">
                  {authorProfile.handle}
                </span>
                {item.selected ? (
                  <span className="readout inline-flex h-5 shrink-0 items-center gap-1 border border-signal/45 bg-signal/10 px-1.5 text-[9px] font-semibold tracking-[0.12em] text-signal">
                    <Sparkles aria-hidden className="h-3 w-3" strokeWidth={1.8} />
                    精选
                  </span>
                ) : null}
              </div>
            ) : (
              <div className="readout min-w-0 truncate text-[10px] uppercase tracking-[0.12em] text-ink-dim">
                {item.main_source?.name ?? "未知来源"} · {item.source_count ?? 1} 个来源
              </div>
            )}
            <div className="flex shrink-0 items-center gap-2">
              <span className="readout text-[10px] font-semibold uppercase tracking-[0.12em] text-signal">
                Score {score}
              </span>
              <BookmarkButton eventId={item.event_id} compact />
            </div>
          </div>

          <h2 className="editorial-card-title mt-1.5 text-[1.15rem] font-semibold leading-[1.42] text-ink md:mt-2 md:text-[1.25rem]">
            {item.selected && !authorProfile ? (
              <span className="readout relative -top-0.5 mr-2 inline-flex h-5 items-center gap-1 border border-signal/45 bg-signal/10 px-1.5 align-middle text-[9px] font-semibold tracking-[0.12em] text-signal">
                <Sparkles aria-hidden className="h-3 w-3 shrink-0" strokeWidth={1.8} />
                精选
              </span>
            ) : null}
            <a className="title-link" href={eventHref(item)}>{item.title}</a>
          </h2>

          <p
            className={`mt-2 text-sm leading-6 text-ink-mid ${
              openArticle
                ? "w-full line-clamp-3 md:line-clamp-none"
                : `max-w-[76ch] line-clamp-2 ${clampSummary ? "md:line-clamp-3" : "md:line-clamp-none"}`
            }`}
          >
            {item.summary ?? item.one_line_summary ?? "暂无摘要。"}
          </p>

          {item.tags?.length ? (
            <div
              className={`mt-2 flex flex-wrap gap-x-4 gap-y-1.5 md:gap-y-2 ${
                openArticle
                  ? ""
                  : "border-t border-line/70 pt-3"
              }`}
            >
              {item.tags.slice(0, maxTags).map((tag) => (
                <a
                  key={tag}
                  href={tagHref(tag)}
                  className="text-xs text-ink-dim underline decoration-line-strong underline-offset-4 hover:text-signal"
                >
                  #{tag}
                </a>
              ))}
            </div>
          ) : null}

          {image && openArticle ? (
            // 精选信息流中的配图是正文证据而非视觉主角：保持 2:1 中心裁切，
            // 桌面端缩至正文的 40% 并左对齐，放在推荐理由之前。
            <figure className={`relative mr-auto mt-3 aspect-[2/1] w-full max-w-[460px] overflow-hidden border border-line/70 bg-panel-soft md:w-2/5 ${hideImageOnMobile ? "hidden md:block" : ""}`}>
              <img
                alt={image.alt ?? item.title}
                className="absolute inset-0 h-full w-full object-cover object-center"
                src={proxiedImageUrl(image.url)}
                referrerPolicy="no-referrer"
              />
            </figure>
          ) : null}

          {showReason && item.reason ? (
            <aside
              className={`mt-2 border-l-2 border-signal pl-3 text-xs leading-5 text-ink-mid ${
                openArticle
                  ? "w-full"
                  : "max-w-[84ch] line-clamp-2"
              }`}
            >
              <span className="readout mb-1 block text-[9px] uppercase tracking-[0.14em] text-signal">推荐理由</span>
              {item.reason}
            </aside>
          ) : null}
        </div>

        {image && !openArticle ? (
          // 外链图必须走代理 + no-referrer：带 localhost Referer 会被各家
          // CDN 防盗链 403（详情页同款处理，实测案例：极客邦 CDN）
          <div className={`relative h-40 border-t border-line 2xl:h-auto 2xl:min-h-full 2xl:border-l 2xl:border-t-0 ${
            hideImageOnMobile ? "hidden 2xl:block" : "md:hidden 2xl:block"
          }`}>
            <img
              alt={image.alt ?? item.title}
              className="absolute inset-0 h-full w-full object-cover grayscale-[18%] transition duration-300 hover:grayscale-0"
              src={proxiedImageUrl(image.url)}
              referrerPolicy="no-referrer"
            />
            <span aria-hidden className="readout absolute right-2 top-2 border border-line bg-canvas/90 px-1.5 py-1 text-[9px] text-ink-dim">
              IMAGE
            </span>
          </div>
        ) : null}
      </div>
    </article>
  );
}

/** 时间线一行：时间戳 + 短刻度。移动端与卡片头部同排展示（紧凑内联），
 *  桌面端维持独立时间列，并让短刻度与时间文字垂直居中。 */
export function EventTimelineRow({ time, children }: { time: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 md:grid-cols-[72px_1fr] md:gap-2">
      <div className="readout relative flex items-center gap-2 text-xs font-semibold text-ink-mid md:block md:pt-3 md:text-sm">
        <span className="h-px w-4 shrink-0 bg-signal md:absolute md:-left-[25px] md:top-[21px] md:w-5" />
        {time}
      </div>
      {children}
    </div>
  );
}
