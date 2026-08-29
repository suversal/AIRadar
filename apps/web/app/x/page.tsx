import { getTweets, type XTweet } from "@/lib/api";
import { MobileCategoryNav } from "@/components/mobile-discovery";
import { MobileNav } from "@/components/mobile-nav";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";
import { TweetCard } from "@/components/tweet-card";

// X 推文展示面（SourcePilot 接入 Phase 4）。数据是本地 x_tweets 镜像表
// （订阅账号 + 订阅话题，refresh 时增量同步），不进 LLM 管线，与事件流互不相干。
// 页面骨架与 /latest、/all 保持一致：RadarStatus 头 + 移动端横滚分类 +
// 桌面 chips 过滤行。

export const metadata = {
  title: "X 推文",
  description: "AI·RADAR 跟踪的 X 账号与话题，推文原样呈现，不经 AI 筛选。",
  alternates: { canonical: "/x" },
};

type XSearchParams = Promise<{
  kind?: string | string[];
  handle?: string | string[];
  topic?: string | string[];
  offset?: string | string[];
}>;

const PAGE_SIZE = 50;

const kindOptions = [
  ["", "全部"],
  ["article", "长文"],
  ["longform", "长推"],
  ["link", "链接"],
  ["quote", "引用"],
  ["repost", "转发"],
  ["brief", "短推"],
] as const;

const VALID_KINDS = new Set<string>(kindOptions.map(([kind]) => kind).filter(Boolean));

// 「长文 / 长推」字面上分不出区别，桌面端悬停给出解释
const kindHints: Record<string, string> = {
  article: "X 平台的 Article 长文，列表只展示标题与摘要",
  longform: "超出常规长度的长推文",
  brief: "常规长度的短推文",
};

function firstQueryValue(value?: string | string[]) {
  return Array.isArray(value) ? value[0] : value;
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "暂无数据";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(parsed)
    .replace(/\//g, "-");
}

function xHref({
  kind,
  handle,
  topic,
  offset,
}: {
  kind?: string;
  handle?: string;
  topic?: string;
  offset?: number;
}) {
  const params = new URLSearchParams();
  if (kind) {
    params.set("kind", kind);
  }
  if (handle) {
    params.set("handle", handle);
  }
  if (topic) {
    params.set("topic", topic);
  }
  if (offset && offset > 0) {
    params.set("offset", String(offset));
  }
  const query = params.toString();
  return query ? `/x?${query}` : "/x";
}

export default async function TweetsPage({ searchParams }: { searchParams: XSearchParams }) {
  const resolved = await searchParams;
  const rawKind = firstQueryValue(resolved.kind) ?? "";
  const selectedKind = VALID_KINDS.has(rawKind) ? rawKind : "";
  const selectedHandle = firstQueryValue(resolved.handle)?.trim() ?? "";
  const selectedTopic = firstQueryValue(resolved.topic)?.trim() ?? "";
  const offset = Math.max(0, Number.parseInt(firstQueryValue(resolved.offset) ?? "0", 10) || 0);

  const payload = await getTweets({
    kind: selectedKind || undefined,
    handle: selectedHandle || undefined,
    topic: selectedTopic || undefined,
    limit: PAGE_SIZE,
    offset,
  });
  const tweets: XTweet[] = payload.items;
  const hasPrev = offset > 0;
  const hasNext = offset + tweets.length < payload.total;

  const topicOptions = [
    { href: xHref({ kind: selectedKind, handle: selectedHandle }), label: "全部话题", selected: !selectedTopic },
    ...payload.topics.map((topic) => ({
      href: xHref({ kind: selectedKind, handle: selectedHandle, topic }),
      label: topic,
      selected: selectedTopic === topic,
    })),
  ];

  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="x" />
        <MobileNav activeNavId="x" />

        <section className="w-full min-w-0 max-w-[1120px] justify-self-center px-4 pb-8 pt-3 md:px-8 md:py-8 xl:px-12">
          <header className="editorial-surface py-1 md:py-2">
            <RadarStatus
              compactScope="X"
              updatedAt={payload.updated_at}
              eventCount={payload.total}
              scope="X TWEETS"
            />
            <div className="mt-3 md:mt-4 md:flex md:items-end md:justify-between md:pb-2">
              <div>
                <h1 className="editorial-rule-title text-4xl font-medium leading-none text-ink md:text-5xl">推文</h1>
                <p className="mt-1.5 text-sm text-ink-mid">
                  AI·RADAR 跟踪的 X 账号与话题，推文原样呈现，不经 AI 筛选
                </p>
              </div>
              <div className="hidden text-sm text-ink-mid md:block">
                更新时间：{formatDateTime(payload.updated_at)}
              </div>
            </div>

            <MobileCategoryNav
              label="推文形态"
              options={kindOptions.map(([kind, label]) => ({
                href: xHref({ kind, handle: selectedHandle, topic: selectedTopic }),
                label: kind === "" ? "全部类型" : label,
                selected: selectedKind === kind,
              }))}
            />
            {payload.topics.length > 0 ? (
              <MobileCategoryNav label="订阅话题" options={topicOptions} />
            ) : null}

            <div className="mt-4 hidden gap-3 md:grid xl:grid-cols-[1fr_minmax(280px,auto)]">
              <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                {kindOptions.map(([kind, label]) => (
                  <a
                    className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                      selectedKind === kind
                        ? "bg-signal/15 text-signal"
                        : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                    }`}
                    href={xHref({ kind, handle: selectedHandle, topic: selectedTopic })}
                    key={kind || "all"}
                    title={kindHints[kind]}
                  >
                    {label}
                  </a>
                ))}
              </div>

              {payload.topics.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                  {topicOptions.map((option) => (
                    <a
                      className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                        option.selected
                          ? "bg-signal/15 text-signal"
                          : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                      }`}
                      href={option.href}
                      key={option.href}
                    >
                      {option.label}
                    </a>
                  ))}
                </div>
              ) : null}
            </div>
          </header>

          {payload.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {payload.error}
            </div>
          ) : null}

          {selectedHandle ? (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="rounded-full border border-signal/40 bg-signal/10 px-3 py-1.5 font-medium text-signal">
                只看 @{selectedHandle} · {payload.total} 条
              </span>
              <a
                className="text-ink-mid hover:text-ink"
                href={xHref({ kind: selectedKind, topic: selectedTopic })}
              >
                清除
              </a>
            </div>
          ) : null}

          {!payload.error && tweets.length === 0 ? (
            <p className="mt-4 rounded-md border border-line bg-panel p-4 text-sm text-ink-mid">
              这个筛选下还没有推文。
            </p>
          ) : null}

          <div className="mt-2 md:mt-4">
            {tweets.map((tweet) => (
              <TweetCard key={tweet.tweet_id} tweet={tweet} />
            ))}
          </div>

          {hasPrev || hasNext ? (
            <nav className="mt-4 flex items-center justify-between text-sm">
              {hasPrev ? (
                <a
                  className="rounded-md border border-line bg-panel px-4 py-2 font-medium text-signal hover:text-signal-bright"
                  href={xHref({
                    kind: selectedKind,
                    handle: selectedHandle,
                    topic: selectedTopic,
                    offset: Math.max(0, offset - PAGE_SIZE),
                  })}
                >
                  ← 较新
                </a>
              ) : (
                <span />
              )}
              {hasNext ? (
                <a
                  className="rounded-md border border-line bg-panel px-4 py-2 font-medium text-signal hover:text-signal-bright"
                  href={xHref({
                    kind: selectedKind,
                    handle: selectedHandle,
                    topic: selectedTopic,
                    offset: offset + PAGE_SIZE,
                  })}
                >
                  更早 →
                </a>
              ) : null}
            </nav>
          ) : null}
        </section>
      </div>
    </main>
  );
}
