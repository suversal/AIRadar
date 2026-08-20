import { getAllEvents } from "@/lib/api";
import { FOCUS_FILTER_OPTIONS, focusCategory } from "@/lib/taxonomy";
import { topicLabel } from "@/lib/topics";
import { AllEventsFeed } from "@/components/all-events-feed";
import { MobileCategoryNav, MobileSearchForm } from "@/components/mobile-discovery";
import { MobileNav } from "@/components/mobile-nav";
import { MobileSourceFilter } from "@/components/mobile-source-filter";
import { RadarStatus } from "@/components/radar-status";
import { Sidebar } from "@/components/sidebar";

export const metadata = {
  title: "全部 AI 动态",
  description:
    "近 30 天的全部 AI 资讯，支持按分类、来源与主题筛选——没进精选的动态也都在这里。",
  alternates: { canonical: "/all" },
};

type AllSearchParams = Promise<{
  source?: string | string[];
  focus?: string | string[];
  category?: string | string[];
  q?: string | string[];
  tag?: string | string[];
  topic?: string | string[];
}>;

const DAYS = 30;
const PAGE_SIZE = 50;

const sourceOptions = [
  ["", "全部来源"],
  ["first_party", "官方原文"],
  ["news", "媒体报道"],
  ["community", "社区讨论"],
] as const;

const categoryOptions = FOCUS_FILTER_OPTIONS;

function firstQueryValue(value?: string | string[]) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function allHref({
  source,
  focus,
  tag,
  topic,
  q,
}: {
  source?: string;
  focus?: string;
  tag?: string;
  topic?: string;
  q?: string;
}) {
  const params = new URLSearchParams();
  if (source) {
    params.set("source", source);
  }
  if (focus) {
    params.set("focus", focus);
  }
  if (tag) {
    params.set("tag", tag);
  }
  if (topic) {
    params.set("topic", topic);
  }
  if (q) {
    params.set("q", q);
  }
  const query = params.toString();
  return query ? `/all?${query}` : "/all";
}

export default async function AllEventsPage({
  searchParams,
}: {
  searchParams: AllSearchParams;
}) {
  const resolvedSearchParams = await searchParams;
  const selectedSource = firstQueryValue(resolvedSearchParams.source) ?? "";
  const selectedCategory = focusCategory(
    firstQueryValue(resolvedSearchParams.focus),
    firstQueryValue(resolvedSearchParams.category),
  );
  const selectedTopic = firstQueryValue(resolvedSearchParams.topic)?.trim() ?? "";
  const selectedTag = firstQueryValue(resolvedSearchParams.tag)?.trim() ?? "";
  const query = firstQueryValue(resolvedSearchParams.q)?.trim() ?? "";
  const report = await getAllEvents({
    days: DAYS,
    limit: PAGE_SIZE,
    source: selectedSource || undefined,
    focus: selectedCategory || undefined,
    tag: selectedTag || undefined,
    topic: selectedTopic || undefined,
    q: query || undefined,
  });
  const mobileSourceOptions = sourceOptions.map(([source, label]) => ({
    href: allHref({
      source,
      focus: selectedCategory,
      tag: selectedTag,
      topic: selectedTopic,
      q: query,
    }),
    label,
    selected: selectedSource === source,
    value: source,
  }));

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="all" />
        <MobileNav activeNavId="all" />

        <section className="px-4 pt-2 pb-4 md:px-9 md:py-6">
          <header className="rounded-md border border-line bg-panel p-4 md:p-5">
            <RadarStatus
              compactScope={`${DAYS}天`}
              updatedAt={report.updated_at}
              eventCount={report.total}
              scope={`ALL DYNAMICS · ${DAYS}D`}
            />
            <div className="mt-3 md:mt-4 md:border-b md:border-line md:pb-4">
              <h1 className="text-2xl font-semibold text-ink">全部 AI 动态</h1>
              <p className="mt-1.5 text-sm text-ink-mid">
                近 {DAYS} 天的全部 AI 资讯——没进精选的动态也都在这里
              </p>
            </div>

            <MobileSearchForm
              action="/all"
              defaultValue={query}
              hiddenFields={[
                ...(selectedSource ? [{ name: "source", value: selectedSource }] : []),
                ...(selectedCategory ? [{ name: "focus", value: selectedCategory }] : []),
                ...(selectedTag ? [{ name: "tag", value: selectedTag }] : []),
                ...(selectedTopic ? [{ name: "topic", value: selectedTopic }] : []),
              ]}
              placeholder="搜索标题、摘要或正文"
              trailingControl={<MobileSourceFilter options={mobileSourceOptions} />}
            />
            <MobileCategoryNav
              label="全部动态内容分类"
              options={categoryOptions.map(([category, label]) => ({
                href: allHref({
                  source: selectedSource,
                  focus: category,
                  tag: selectedTag,
                  topic: selectedTopic,
                  q: query,
                }),
                label,
                selected: selectedCategory === category,
              }))}
            />

            <div className="mt-4 hidden gap-3 md:grid xl:grid-cols-[1fr_1fr_320px]">
              <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                {categoryOptions.map(([category, label]) => (
                  <a
                    key={category || "all-category"}
                    className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                      selectedCategory === category
                        ? "bg-signal/15 text-signal"
                        : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                    }`}
                    href={allHref({
                      source: selectedSource,
                      focus: category,
                      tag: selectedTag,
                      topic: selectedTopic,
                      q: query,
                    })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <div className="flex flex-wrap gap-1.5 rounded-md border border-line bg-canvas p-1.5">
                {sourceOptions.map(([source, label]) => (
                  <a
                    key={source || "all-source"}
                    className={`flex min-h-10 items-center rounded-md px-4 py-1.5 text-sm font-medium ${
                      selectedSource === source
                        ? "bg-signal/15 text-signal"
                        : "text-ink-mid hover:bg-panel-soft hover:text-ink"
                    }`}
                    href={allHref({
                      source,
                      focus: selectedCategory,
                      tag: selectedTag,
                      topic: selectedTopic,
                      q: query,
                    })}
                  >
                    {label}
                  </a>
                ))}
              </div>

              <form action="/all" className="grid grid-cols-[1fr_auto] gap-2">
                {selectedSource ? <input name="source" type="hidden" value={selectedSource} /> : null}
                {selectedCategory ? <input name="focus" type="hidden" value={selectedCategory} /> : null}
                {selectedTag ? <input name="tag" type="hidden" value={selectedTag} /> : null}
                {selectedTopic ? <input name="topic" type="hidden" value={selectedTopic} /> : null}
                <input
                  className="min-h-10 min-w-0 rounded-md border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要/正文..."
                  type="search"
                />
                <button
                  className="min-h-10 rounded-md border border-signal/40 bg-signal/10 px-4 py-2 text-sm font-medium text-signal transition hover:border-signal/60 hover:text-signal-bright"
                  type="submit"
                >
                  搜索
                </button>
              </form>
            </div>
          </header>

          {report.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {report.error}
            </div>
          ) : null}

          {selectedTopic ? (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="rounded-full border border-signal/40 bg-signal/10 px-3 py-1.5 font-medium text-signal">
                主题筛选：{topicLabel(selectedTopic)} · {report.total} 条
              </span>
              <a
                className="text-ink-mid hover:text-ink"
                href={allHref({
                  source: selectedSource,
                  focus: selectedCategory,
                  tag: selectedTag,
                  q: query,
                })}
              >
                清除
              </a>
              <a
                className="text-ink-mid hover:text-ink"
                href={`/topics/${encodeURIComponent(selectedTopic)}`}
              >
                主题详情
              </a>
              <a className="text-ink-mid hover:text-ink" href="/topics">
                全部主题
              </a>
            </div>
          ) : null}

          {selectedTag ? (
            <div className="mt-4 flex items-center gap-3 text-sm">
              <span className="rounded-full border border-signal/40 bg-signal/10 px-3 py-1.5 font-medium text-signal">
                标签筛选：{selectedTag} · {report.total} 条
              </span>
              <a
                className="text-ink-mid hover:text-ink"
                href={allHref({
                  source: selectedSource,
                  focus: selectedCategory,
                  topic: selectedTopic,
                  q: query,
                })}
              >
                清除
              </a>
            </div>
          ) : null}

          <AllEventsFeed
            initialItems={report.items}
            initialTotal={report.total}
            topic={selectedTopic}
            tag={selectedTag}
            selectedSource={selectedSource}
            selectedCategory={selectedCategory}
            query={query}
          />
        </section>
      </div>
    </main>
  );
}
