import { AllEventsFeed } from "@/components/all-events-feed";
import { MobileCategoryNav, MobileSearchForm } from "@/components/mobile-discovery";
import { MobileNav } from "@/components/mobile-nav";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";
import { getTelegramEvents } from "@/lib/api";

export const metadata = {
  title: "电报",
  description: "AI·RADAR 信源中的 RSSHub 电报频道动态。",
  alternates: { canonical: "/telegram" },
};

type TelegramSearchParams = Promise<{
  channel?: string | string[];
  q?: string | string[];
}>;

const DAYS = 30;
const PAGE_SIZE = 50;

function firstQueryValue(value?: string | string[]) {
  return Array.isArray(value) ? value[0] : value;
}

function telegramHref({ channel, q }: { channel?: string; q?: string } = {}) {
  const params = new URLSearchParams();
  if (channel) {
    params.set("channel", channel);
  }
  if (q) {
    params.set("q", q);
  }
  const query = params.toString();
  return query ? `/telegram?${query}` : "/telegram";
}

export default async function TelegramPage({
  searchParams,
}: {
  searchParams: TelegramSearchParams;
}) {
  const resolved = await searchParams;
  const selectedChannel = firstQueryValue(resolved.channel)?.trim() ?? "";
  const query = firstQueryValue(resolved.q)?.trim() ?? "";
  const payload = await getTelegramEvents({
    days: DAYS,
    channel: selectedChannel || undefined,
    q: query || undefined,
    limit: PAGE_SIZE,
  });
  const channelOptions = [
    { href: telegramHref({ q: query }), label: "全部频道", selected: !selectedChannel },
    ...payload.channels.map((channel) => ({
      href: telegramHref({ channel: channel.id, q: query }),
      label: channel.name,
      selected: selectedChannel === channel.id,
    })),
  ];
  const selectedChannelName = payload.channels.find(
    (channel) => channel.id === selectedChannel,
  )?.name;

  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="telegram" />
        <MobileNav activeNavId="telegram" />

        <section className="w-full min-w-0 max-w-[1320px] justify-self-center px-4 pb-8 pt-3 md:px-8 md:py-8 xl:px-12">
          <header className="editorial-surface py-1 md:py-2">
            <RadarStatus
              compactScope="电报"
              updatedAt={payload.updated_at}
              eventCount={payload.total}
              scope={`TELEGRAM · ${DAYS}D`}
            />
            <div className="mt-3 md:mt-4 md:pb-2">
              <h1 className="editorial-rule-title text-4xl font-medium leading-none text-ink md:text-5xl">电报</h1>
              <p className="mt-1.5 text-sm text-ink-mid">
                  AI·RADAR 订阅的电报频道动态
              </p>
            </div>

            <MobileSearchForm
              action="/telegram"
              defaultValue={query}
              hiddenFields={selectedChannel ? [{ name: "channel", value: selectedChannel }] : []}
              placeholder="搜索标题、摘要或正文"
            />
            <MobileCategoryNav label="电报频道" options={channelOptions} />

            <div className="mt-5 hidden border-y border-line md:grid xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="min-w-0 py-2.5 xl:pr-5">
                <nav aria-label="电报频道" className="flex min-w-0 items-start gap-4">
                  <span className="readout w-10 shrink-0 py-2 text-[10px] uppercase tracking-[0.12em] text-ink-dim">
                    频道
                  </span>
                  <div className="flex min-w-0 flex-wrap gap-x-5 gap-y-0.5">
                    {channelOptions.map((option) => (
                      <a
                        aria-current={option.selected ? "page" : undefined}
                        className={`flex min-h-8 items-center border-b px-0.5 text-sm font-medium transition-colors ${
                          option.selected
                            ? "border-signal text-signal"
                            : "border-transparent text-ink-mid hover:border-line-strong hover:text-ink"
                        }`}
                        href={option.href}
                        key={option.href}
                      >
                        {option.label}
                      </a>
                    ))}
                  </div>
                </nav>
              </div>

              <form
                action="/telegram"
                aria-label="搜索电报动态"
                className="grid min-w-0 grid-cols-[1fr_auto] border-t border-line xl:border-l xl:border-t-0"
              >
                {selectedChannel ? <input name="channel" type="hidden" value={selectedChannel} /> : null}
                <label className="sr-only" htmlFor="telegram-search">搜索电报动态</label>
                <input
                  id="telegram-search"
                  className="relative z-0 min-h-12 min-w-0 bg-transparent px-4 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:bg-panel-soft/35 focus-visible:z-10"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要/正文..."
                  type="search"
                />
                <button
                  className="min-h-12 cursor-pointer border-l border-line px-5 py-2 text-sm font-medium text-signal transition-colors hover:bg-signal/10 hover:text-signal-bright focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-signal"
                  type="submit"
                >
                  搜索
                </button>
              </form>
            </div>
          </header>

          {payload.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {payload.error}
            </div>
          ) : null}

          <AllEventsFeed
            initialItems={payload.items}
            initialTotal={payload.total}
            topic=""
            tag=""
            selectedSource=""
            selectedCategory=""
            query={query}
            paginationPath="/api/telegram-events"
            paginationParams={selectedChannel ? { channel: selectedChannel } : {}}
            emptyMessage={
              query
                ? `没有找到包含“${query}”的电报动态。`
                : selectedChannelName
                ? `${selectedChannelName} 近 ${DAYS} 天还没有动态。`
                : `近 ${DAYS} 天还没有电报动态。`
            }
            completeLabel={
              selectedChannelName
                ? `${selectedChannelName}近 ${DAYS} 天全部`
                : `近 ${DAYS} 天全部电报频道的`
            }
          />
        </section>
      </div>
    </main>
  );
}
