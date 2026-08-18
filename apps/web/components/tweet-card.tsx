"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Eye, Heart, MessageCircle, Repeat2 } from "lucide-react";

import type { XTweet } from "@/lib/api";
import { articleSanitizeSchema } from "@/lib/sanitize-schema";
import { proxiedImageUrl } from "@/lib/images";
import { formatRelativeTime } from "@/lib/time";
import { ArticleImage } from "@/components/article-image";
import { AuthorAvatar } from "@/components/author-avatar";
import {
  PROSE_CODE_INLINE_CLASSNAME,
  PROSE_LIST_CLASSNAME,
} from "@/components/prose-tokens";

// 契约红线（SP contract §5.4）：display_text 是 Markdown 且已把配图织进正文，
// 渲染它就**不要**再渲染 media 数组（同一张图会出现两次）；外链一律用
// external_urls（SP 已展开 t.co，别再去解析短链）；信源内容是不可信数据，
// Markdown 必须过 sanitize。
//
// 展示分两级：列表卡片对长内容（article / 超长 longform）只出标题与摘要，
// 全文在详情页 /x/[id]（TweetCard 的 detail 变体）——一篇几千字的长文塞进
// 列表位，翻页体验两边都不对。

const KIND_LABELS: Record<XTweet["content_kind"], string> = {
  repost: "转发",
  article: "长文",
  longform: "长推",
  link: "链接",
  quote: "引用",
  brief: "短推",
};

// 推文正文比 /event 的长文阅读页紧凑一号
const TWEET_P = "break-words text-[15px] leading-[24px] text-ink [overflow-wrap:anywhere]";

// 列表摘要长度：够看出「这篇讲什么」，又不至于把列表撑成正文
const EXCERPT_CHARS = 200;

const tweetMarkdownComponents: Components = {
  p({ node: _node, ...props }) {
    return <p className={TWEET_P} {...props} />;
  },
  a({ node: _node, ...props }) {
    return (
      <a
        className="break-words text-signal underline decoration-signal/40 underline-offset-4 [overflow-wrap:anywhere] hover:text-signal-bright"
        rel="noreferrer"
        target="_blank"
        {...props}
      />
    );
  },
  h1({ node: _node, ...props }) {
    return <h3 className="mt-4 text-lg font-semibold text-ink" {...props} />;
  },
  h2({ node: _node, ...props }) {
    return <h4 className="mt-4 text-base font-semibold text-ink" {...props} />;
  },
  h3({ node: _node, ...props }) {
    return <h5 className="mt-3 text-base font-semibold text-ink" {...props} />;
  },
  ul({ node: _node, ...props }) {
    return <ul className={`${PROSE_LIST_CLASSNAME} list-disc`} {...props} />;
  },
  ol({ node: _node, ...props }) {
    return <ol className={`${PROSE_LIST_CLASSNAME} list-decimal`} {...props} />;
  },
  li({ node: _node, ...props }) {
    return <li className="pl-1" {...props} />;
  },
  code({ node: _node, ...props }) {
    return <code className={PROSE_CODE_INLINE_CLASSNAME} {...props} />;
  },
  blockquote({ node: _node, ...props }) {
    return <blockquote className="border-l-2 border-signal/50 pl-4 text-ink-mid" {...props} />;
  },
  img({ node: _node, src, alt }) {
    if (!src || typeof src !== "string") {
      return null;
    }
    return (
      <ArticleImage
        src={proxiedImageUrl(src)}
        alt={alt ?? ""}
        className="my-2 max-h-[480px] w-auto max-w-full rounded-md border border-line object-contain"
      />
    );
  },
};

function TweetMarkdown({ text }: { text: string }) {
  return (
    <div className="space-y-2">
      <ReactMarkdown
        components={tweetMarkdownComponents}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, articleSanitizeSchema]]}
        remarkPlugins={[remarkGfm]}
        skipHtml={false}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

type ExtractedMedia = {
  type: "image" | "video";
  url: string; // 图片地址；视频时是缩略图
  link?: string; // 视频的跳转地址
};

/** 把织在正文里的配图/视频缩略图抽出来（参照 X 的排版：正文只留文字，
 *  媒体合并到底部栅格）。长文（article）不走这里——那是文章排版，
 *  图有上下文，保持图文混排。 */
function splitMediaFromMarkdown(markdown: string): { text: string; media: ExtractedMedia[] } {
  const media: ExtractedMedia[] = [];
  let text = markdown;
  // 先抽视频（可点击缩略图 [![](thumb)](href)），再抽普通图片，顺序不能反——
  // 视频语法里嵌着图片语法，先跑图片正则会把它拆碎
  text = text.replace(/\[!\[[^\]]*\]\(([^)\s]+)\)\]\(([^)\s]+)\)/g, (_m, thumb, href) => {
    media.push({ type: "video", url: thumb, link: href });
    return "";
  });
  text = text.replace(/!\[[^\]]*\]\(([^)\s]+)\)/g, (_m, url) => {
    media.push({ type: "image", url });
    return "";
  });
  // 清掉抽走媒体后留下的空段
  text = text.replace(/\n{3,}/g, "\n\n").trim();
  return { text, media };
}

function MediaGrid({ media, alt }: { media: ExtractedMedia[]; alt: string }) {
  // 点击放大的弹层状态：null = 关闭，数字 = 当前看第几张
  const [lightbox, setLightbox] = useState<number | null>(null);
  // 弹层必须 portal 到 <body>：.card-hover 一旦给卡片上 transform，带
  // transform 的祖先就会接管后代 position:fixed 的包含块——弹层于是变成
  // "以卡片居中"，位置随卡片在页面里的位置飘。现在悬浮态只亮边框、没有
  // transform 了，但这个 portal 得留着：hover 效果是随时会调回来的东西。
  // 挂到 body 之后才是真正的视口居中。SSR 阶段没有 document，先等挂载完成。
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (media.length === 0) {
    return null;
  }
  const shown = media.slice(0, 4);
  const extra = media.length - shown.length;

  return (
    <>
      {/* 整块限宽（对齐 X：媒体不随卡片通栏铺满）；单图保持原始比例不裁切，
          多图才用等高裁切格 */}
      <div
        className={`mt-3 max-w-xl ${
          shown.length === 1 ? "" : "grid grid-cols-2 gap-1.5"
        }`}
      >
        {shown.map((item, index) => (
          <button
            className={`group relative overflow-hidden rounded-md border border-line bg-panel-soft ${
              shown.length === 1 ? "inline-block" : ""
            }`}
            key={`${item.url}-${index}`}
            onClick={() => {
              if (item.type === "video" && item.link) {
                window.open(item.link, "_blank", "noopener,noreferrer");
                return;
              }
              setLightbox(index);
            }}
            title={item.type === "video" ? "播放视频（跳转原推）" : "查看大图"}
            type="button"
          >
            <img
              alt={alt}
              className={
                shown.length === 1
                  ? "max-h-[420px] w-auto max-w-full object-contain"
                  : "h-36 w-full object-cover transition-transform group-hover:scale-[1.02] md:h-44"
              }
              loading="lazy"
              referrerPolicy="no-referrer"
              src={proxiedImageUrl(item.url)}
            />
            {item.type === "video" ? (
              <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <span className="flex size-12 items-center justify-center rounded-full bg-black/60 text-xl text-white">
                  ▶
                </span>
              </span>
            ) : null}
            {extra > 0 && index === shown.length - 1 ? (
              <span className="absolute inset-0 flex items-center justify-center bg-black/50 text-lg font-semibold text-white">
                +{extra}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {lightbox !== null && mounted
        ? createPortal(
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
              onClick={() => setLightbox(null)}
              role="presentation"
            >
              {media.length > 1 ? (
                <button
                  className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full bg-black/60 px-3 py-2 text-xl text-white"
                  onClick={(event) => {
                    event.stopPropagation();
                    setLightbox((lightbox - 1 + media.length) % media.length);
                  }}
                  type="button"
                >
                  ‹
                </button>
              ) : null}
              <img
                alt={alt}
                className="max-h-[90vh] max-w-[92vw] rounded-md object-contain"
                src={proxiedImageUrl(media[lightbox].url)}
              />
              {media.length > 1 ? (
                <button
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-black/60 px-3 py-2 text-xl text-white"
                  onClick={(event) => {
                    event.stopPropagation();
                    setLightbox((lightbox + 1) % media.length);
                  }}
                  type="button"
                >
                  ›
                </button>
              ) : null}
              <button
                className="absolute right-3 top-3 rounded-full bg-black/60 px-3 py-1.5 text-sm text-white"
                onClick={() => setLightbox(null)}
                type="button"
              >
                关闭 ✕
              </button>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

/** Markdown → 纯文本摘要。剥掉图片/链接/强调/标题标记后按字符截断——
 *  截断发生在纯文本上，永远不会切碎 Markdown 语法。 */
function plainExcerpt(markdown: string, maxChars = EXCERPT_CHARS): string {
  const plain = markdown
    .replace(/\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)/g, "") // 可点击缩略图（视频）
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "") // 图片
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // 链接留锚文本
    .replace(/^#{1,6}\s+/gm, "") // 标题标记
    .replace(/(\*\*|__|\*|_|`)/g, "") // 强调/代码标记
    .replace(/^>\s?/gm, "") // 引用标记
    .replace(/\s+/g, " ")
    .trim();
  if (plain.length <= maxChars) {
    return plain;
  }
  return `${plain.slice(0, maxChars).trimEnd()}…`;
}

function formatCount(value?: number | null): string | null {
  if (value === null || value === undefined || value <= 0) {
    return null;
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}万`;
  }
  return String(value);
}

function EngagementBar({ tweet }: { tweet: XTweet }) {
  const entries: Array<[typeof Heart, string | null, string]> = [
    [Heart, formatCount(tweet.likes), "点赞"],
    [Repeat2, formatCount(tweet.retweets), "转发"],
    [MessageCircle, formatCount(tweet.replies), "回复"],
    [Eye, formatCount(tweet.views), "浏览"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-ink-mid">
      {entries.map(([Icon, label, title]) =>
        label ? (
          <span className="inline-flex items-center gap-1" key={title} title={title}>
            <Icon aria-hidden className="size-3.5" />
            {label}
          </span>
        ) : null,
      )}
      <a
        className="ml-auto font-medium text-signal hover:text-signal-bright"
        href={tweet.url}
        rel="noopener noreferrer"
        target="_blank"
      >
        查看原推 ↗
      </a>
    </div>
  );
}

function QuoteBlock({ handle, text }: { handle?: string | null; text?: string | null }) {
  if (!text) {
    return null;
  }
  return (
    <blockquote className="rounded-md border border-line bg-panel-soft p-3 text-sm text-ink-mid">
      {handle ? <p className="mb-1 font-semibold text-ink">@{handle}</p> : null}
      <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{text}</p>
    </blockquote>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function ExternalLinks({ urls }: { urls?: string[] }) {
  if (!urls || urls.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {urls.map((url) => (
        <a
          className="inline-flex max-w-full items-center gap-1 truncate rounded-md border border-line bg-panel-soft px-3 py-1.5 text-xs font-medium text-signal hover:text-signal-bright"
          href={url}
          key={url}
          rel="noopener noreferrer"
          target="_blank"
        >
          {hostOf(url)} ↗
        </a>
      ))}
    </div>
  );
}

function AiSummaryBox({ text }: { text: string }) {
  // article_ai_summary 是 X（Grok）生成的二手信息，展示必须带标注
  return (
    <p className="rounded-md border border-line bg-panel-soft p-3 text-sm text-ink-mid">
      <span className="mr-1.5 rounded border border-line px-1 py-0.5 text-[10px]">X 生成</span>
      {text}
    </p>
  );
}

function TweetHeader({
  tweet,
  showOriginal,
  onToggleOriginal,
}: {
  tweet: XTweet;
  showOriginal: boolean;
  onToggleOriginal?: () => void;
}) {
  const authorName = tweet.author_name || tweet.author_handle;
  return (
    <header className="flex items-center gap-3">
      <AuthorAvatar
        name={authorName}
        sizeClassName="size-9"
        src={tweet.author_avatar ?? undefined}
      />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-ink">
          {authorName}
          <span className="ml-1.5 font-normal text-ink-mid">@{tweet.author_handle}</span>
        </p>
        <p className="text-xs text-ink-mid">
          <time dateTime={tweet.created_at} title={tweet.created_at}>
            {formatRelativeTime(tweet.created_at)}
          </time>
          {tweet.is_reply && tweet.reply_to_handle && tweet.content_kind !== "repost" ? (
            <span className="ml-1.5">回复 @{tweet.reply_to_handle}</span>
          ) : null}
        </p>
      </div>
      <span className="ml-auto flex shrink-0 items-center gap-1.5">
        {(tweet.topics ?? []).map((topic) => (
          <a
            className="readout hidden h-5 items-center rounded-full border border-signal/40 bg-signal/10 px-1.5 text-[11px] font-semibold leading-none text-signal hover:text-signal-bright md:inline-flex"
            href={`/x?topic=${encodeURIComponent(topic)}`}
            key={topic}
          >
            #{topic}
          </a>
        ))}
        {onToggleOriginal ? (
          <button
            className="readout inline-flex h-5 items-center rounded-full border border-signal/40 px-1.5 text-[11px] font-semibold leading-none text-signal hover:text-signal-bright"
            onClick={onToggleOriginal}
            title={showOriginal ? "切换到中文翻译" : "查看原文"}
            type="button"
          >
            {showOriginal ? "译文" : "原文"}
          </button>
        ) : null}
        <span className="readout inline-flex h-5 items-center rounded-full border border-line px-1.5 text-[11px] font-semibold leading-none text-ink-mid">
          {KIND_LABELS[tweet.content_kind]}
        </span>
      </span>
    </header>
  );
}

/** 列表卡片对长内容的收敛正文：标题 + 纯文本摘要 + 阅读全文入口。 */
function CollapsedBody({
  tweet,
  heading,
  summary,
  aiSummary,
}: {
  tweet: XTweet;
  heading?: string | null;
  summary: string;
  aiSummary?: string | null;
}) {
  const detailHref = `/x/${tweet.tweet_id}`;
  return (
    <div className="mt-3 space-y-2">
      {heading ? (
        <h2 className="text-lg font-semibold leading-snug text-ink">
          <a className="title-link" href={detailHref}>
            {heading}
          </a>
        </h2>
      ) : null}
      {aiSummary ? <AiSummaryBox text={aiSummary} /> : summary ? (
        <p className="text-sm leading-6 text-ink-mid">{summary}</p>
      ) : null}
      <a
        className="inline-block text-sm font-medium text-signal hover:text-signal-bright"
        href={detailHref}
      >
        阅读全文 →
      </a>
    </div>
  );
}

export function TweetCard({ tweet, detail = false }: { tweet: XTweet; detail?: boolean }) {
  // 有译文时默认展示中文，「原」按钮切回原文；无译文（或原文本就是中文）
  // 时不出按钮，直接展示原文
  const [showOriginal, setShowOriginal] = useState(false);
  const translation = tweet.translation;
  const useZh = Boolean(translation?.display_text_zh) && !showOriginal;
  const bodyText = useZh ? translation!.display_text_zh : tweet.display_text;
  const quotedText =
    useZh && translation?.quoted_text_zh ? translation.quoted_text_zh : tweet.quoted_text;

  const kind = tweet.content_kind;
  const isRepost = kind === "repost";
  // 只有长文（X Articles，动辄几千字）收敛进详情页；长推再长也就千把字，
  // 直接在列表里全文展示，多跳一次反而碍事
  const articleCollapsed = !detail && kind === "article";
  // 长推不出独立标题——display_title 就是正文首行的截断，再显示一遍是重复
  const heading = kind === "article" ? tweet.display_title?.trim() : null;

  // 参照 X 的排版：普通推文的配图不混在正文里，抽出来合并到底部媒体栅格，
  // 点击放大。长文例外——article_markdown 里的图是文章内容的一部分，保持混排。
  const splitMedia = kind !== "article";
  const { text: bodyWithoutMedia, media: extractedMedia } = splitMedia
    ? splitMediaFromMarkdown(bodyText)
    : { text: bodyText, media: [] as ExtractedMedia[] };

  return (
    <article className="card-hover rounded-md border border-line bg-panel p-3 md:p-4">
      <TweetHeader
        onToggleOriginal={
          translation?.display_text_zh
            ? () => setShowOriginal((value) => !value)
            : undefined
        }
        showOriginal={showOriginal}
        tweet={tweet}
      />

      {isRepost ? (
        // 转发的外层推文没有自己的内容（正文是 RT 截断、互动数记的是转发
        // 动作），display_text 已被 SP 换成原文——头部必须写清作者归属
        <p className="mt-3 text-xs text-ink-mid">
          @{tweet.author_handle} 转发了 @{tweet.retweeted_handle ?? "?"}
        </p>
      ) : null}

      {articleCollapsed ? (
        <CollapsedBody
          aiSummary={useZh ? null : tweet.article_ai_summary}
          heading={tweet.display_title?.trim()}
          summary={
            useZh
              ? plainExcerpt(bodyText)
              : tweet.article_summary?.trim() || plainExcerpt(tweet.display_text)
          }
          tweet={tweet}
        />
      ) : (
        <>
          {heading ? (
            <h2 className="mt-3 text-lg font-semibold leading-snug text-ink">{heading}</h2>
          ) : null}
          {detail && kind === "article" && !useZh && tweet.article_ai_summary ? (
            <div className="mt-3">
              <AiSummaryBox text={tweet.article_ai_summary} />
            </div>
          ) : null}
          {bodyWithoutMedia ? (
            <div className="mt-3">
              <TweetMarkdown text={bodyWithoutMedia} />
            </div>
          ) : null}
          <MediaGrid alt={`@${tweet.author_handle} 的推文配图`} media={extractedMedia} />
        </>
      )}

      {kind === "quote" ? (
        <div className="mt-3">
          <QuoteBlock handle={tweet.quoted_handle} text={quotedText} />
        </div>
      ) : null}

      {kind === "link" ? (
        <div className="mt-3">
          <ExternalLinks urls={tweet.external_urls} />
        </div>
      ) : null}

      <footer className="mt-4 border-t border-line pt-3">
        <EngagementBar tweet={tweet} />
      </footer>
    </article>
  );
}
