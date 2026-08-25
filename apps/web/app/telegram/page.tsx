import { AllEventsFeed } from "@/components/all-events-feed";
import { MobileCategoryNav } from "@/components/mobile-discovery";
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
}>;

const DAYS = 30;
const PAGE_SIZE = 50;

function firstQueryValue(value?: string | string[]) {
  return Array.isArray(value) ? value[0] : value;
}

function telegramHref(channel?: string) {
  return channel ? `/telegram?${new URLSearchParams({ channel })}` : "/telegram";
}

export default async function TelegramPage({
  searchParams,
}: {
  searchParams: TelegramSearchParams;
}) {
  const resolved = await searchParams;
  const selectedChannel = firstQueryValue(resolved.channel)?.trim() ?? "";
  const payload = await getTelegramEvents({
    days: DAYS,
    channel: selectedChannel || undefined,
    limit: PAGE_SIZE,
  });
  const channelOptions = [
    { href: telegramHref(), label: "全部频道", selected: !selectedChannel },
    ...payload.channels.map((channel) => ({
      href: telegramHref(channel.id),
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

        <section className="w-full min-w-0 max-w-[1200px] justify-self-center px-4 pb-8 pt-3 md:px-8 md:py-8 xl:px-12">
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

            <MobileCategoryNav label="电报频道" options={channelOptions} />

            <nav
              aria-label="电报频道"
              className="mt-4 hidden flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5 md:flex"
            >
              {channelOptions.map((option) => (
                <a
                  aria-current={option.selected ? "page" : undefined}
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
            </nav>
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
            query=""
            paginationPath="/api/telegram-events"
            paginationParams={selectedChannel ? { channel: selectedChannel } : {}}
            emptyMessage={
              selectedChannelName
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
