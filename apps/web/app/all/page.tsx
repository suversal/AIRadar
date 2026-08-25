import { getAllEvents } from "@/lib/api";
import { FOCUS_FILTER_OPTIONS, focusCategory } from "@/lib/taxonomy";
import { resolveTopicId, TOPIC_NAMES, topicLabel } from "@/lib/topics";
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
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="all" />
        <MobileNav activeNavId="all" />

        <section className="w-full min-w-0 max-w-[1320px] justify-self-center px-4 pb-8 pt-3 md:px-8 md:py-8 xl:px-12">
          <header className="editorial-surface py-1 md:py-2">
            <RadarStatus
              compactScope={`${DAYS}天`}
              updatedAt={report.updated_at}
              eventCount={report.total}
              scope={`ALL DYNAMICS · ${DAYS}D`}
            />
            <div className="mt-3 md:mt-4 md:pb-2">
              <h1 className="editorial-rule-title text-4xl font-medium leading-none text-ink md:text-5xl">全部 AI 动态</h1>
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

            <div className="mt-5 hidden border-y border-line md:grid xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="min-w-0 py-2.5 xl:pr-5">
                <nav aria-label="内容分类" className="flex min-w-0 items-start gap-4">
                  <span className="readout w-10 shrink-0 py-2 text-[10px] uppercase tracking-[0.12em] text-ink-dim">
                    分类
                  </span>
                  <div className="flex min-w-0 flex-wrap gap-x-5 gap-y-0.5">
                    {categoryOptions.map(([category, label]) => (
                      <a
                        key={category || "all-category"}
                        className={`flex min-h-8 items-center border-b px-0.5 text-sm font-medium transition-colors ${
                          selectedCategory === category
                            ? "border-signal text-signal"
                            : "border-transparent text-ink-mid hover:border-line-strong hover:text-ink"
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
                </nav>

                <nav aria-label="内容来源" className="mt-1 flex min-w-0 items-start gap-4">
                  <span className="readout w-10 shrink-0 py-2 text-[10px] uppercase tracking-[0.12em] text-ink-dim">
                    来源
                  </span>
                  <div className="flex min-w-0 flex-wrap gap-x-5 gap-y-0.5">
                    {sourceOptions.map(([source, label]) => (
                      <a
                        key={source || "all-source"}
                        className={`flex min-h-8 items-center border-b px-0.5 text-sm font-medium transition-colors ${
                          selectedSource === source
                            ? "border-signal text-signal"
                            : "border-transparent text-ink-mid hover:border-line-strong hover:text-ink"
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
                </nav>
              </div>

              <form
                action="/all"
                className="grid min-w-0 grid-cols-[1fr_auto] border-t border-line xl:border-l xl:border-t-0"
              >
                {selectedSource ? <input name="source" type="hidden" value={selectedSource} /> : null}
                {selectedCategory ? <input name="focus" type="hidden" value={selectedCategory} /> : null}
                {selectedTag ? <input name="tag" type="hidden" value={selectedTag} /> : null}
                {selectedTopic ? <input name="topic" type="hidden" value={selectedTopic} /> : null}
                <input
                  className="min-h-12 min-w-0 bg-transparent px-4 py-2 text-sm text-ink outline-none placeholder:text-ink-dim focus:bg-panel-soft/35"
                  defaultValue={query}
                  name="q"
                  placeholder="搜索标题/摘要/正文..."
                  type="search"
                />
                <button
                  className="min-h-12 border-l border-line px-5 py-2 text-sm font-medium text-signal transition-colors hover:bg-signal/10 hover:text-signal-bright"
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
              {/* 旧链接可能带着已退役的主题 id(如 cn_models):详情页会 404,
                  这种情况不给入口;别名 id 则跳到解析后的 canonical 路径 */}
              {resolveTopicId(selectedTopic) in TOPIC_NAMES ? (
                <a
                  className="text-ink-mid hover:text-ink"
                  href={`/topics/${encodeURIComponent(resolveTopicId(selectedTopic))}`}
                >
                  主题详情
                </a>
              ) : null}
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
