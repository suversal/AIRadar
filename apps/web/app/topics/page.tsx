import { getTopics, type TopicsPayload, type TopicSummary } from "@/lib/api";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";

/** 必须动态渲染，不能在构建期预渲染。
 *
 *  这个页面的内容全部来自后端 API，而 API 在 `docker build` 阶段是**不可达的**
 *  （web 镜像单独构建，那时 compose 网络里还没有 api 服务）。一旦被预渲染，
 *  lib/api.ts 的降级 payload——也就是"API 服务暂时不可用"——会被直接烤进静态
 *  HTML，然后按 revalidate 周期一直发给用户。
 *
 *  2026-08-13 加数据缓存时真踩过：`cache: "no-store"` 一去掉，这个页面就从
 *  动态渲染变成了 ISR 静态页，上线后 /weekly /monthly /topics 三个页面直接
 *  展示报错文案。见 docs/2026-08-13-hardening-plan.md。
 *
 *  性能不受影响：HTML 由 nginx 缓存（infra/nginx/radar-cf.conf，180s），
 *  取数由 Next 数据缓存兜（lib/api.ts 的 cacheFor），两层都还在。 */
export const dynamic = "force-dynamic";

export const metadata = {
  title: "主题",
  description: "按公司与模型、技术方向追踪 AI 精选动态：每个主题一条持续更新的档案流。",
  alternates: { canonical: "/topics" },
};

// 组内活跃/沉寂的分界：近 90 天精选不足这个数的主题折叠成小字行,
// 不和活跃主题平起平坐——点进去几乎是空页的入口摆在大卡位置会损耗可信度
const DORMANT_THRESHOLD = 5;

function daysAgo(dateStr: string | null): number | null {
  if (!dateStr) {
    return null;
  }
  const parsed = new Date(`${dateStr}T00:00:00+08:00`);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 86_400_000));
}

function freshnessLabel(dateStr: string | null): string {
  const days = daysAgo(dateStr);
  if (days === null) {
    return "暂无动态";
  }
  if (days <= 0) {
    return "今天更新";
  }
  if (days === 1) {
    return "昨天更新";
  }
  return `${days} 天前更新`;
}

/** 周环比信号。只在变化够大时给箭头,平稳就安静——满屏箭头等于没有箭头。 */
function weekTrend(topic: TopicSummary): "up" | "down" | null {
  const { week_count: week, prev_week_count: prev } = topic;
  if (week >= 3 && week >= prev * 1.5 && week > prev) {
    return "up";
  }
  if (prev >= 3 && prev >= week * 1.5 && prev > week) {
    return "down";
  }
  return null;
}

function sortByActivity(topics: TopicSummary[]): TopicSummary[] {
  return [...topics].sort(
    (a, b) => b.week_count - a.week_count || b.count - a.count || a.id.localeCompare(b.id),
  );
}

/** 异动主题:周环比显著上升的主题,给"本周雷达"条用,最多 4 个——
 *  它是信号灯不是排行榜,多了就没人看了。
 *  三条产品决策(2026-08-20):
 *  - 只收上升:这个位置回答"什么正在变热",降温交给卡片上的周环比;
 *  - 只看"公司与模型"组:技术方向(Agent/多模态…)太抽象,变热了也
 *    说不出是谁的事,实体异动才是可点进去看的新闻;
 *  - 入围用倍数门槛(weekTrend 的 1.5 倍,滤掉正常波动),排序用
 *    绝对增量——倍数排序会把 1→4 这种小基数噪声排到 6→20 前面。 */
function pickMovers(groups: TopicsPayload["groups"]) {
  return groups
    .filter((group) => group.id === "entities")
    .flatMap((group) => group.topics)
    .filter((topic) => weekTrend(topic) === "up")
    .sort(
      (a, b) => b.week_count - b.prev_week_count - (a.week_count - a.prev_week_count),
    )
    .slice(0, 4);
}

function WeeklyRadarStrip({ payload }: { payload: TopicsPayload }) {
  const movers = pickMovers(payload.groups);
  if (payload.storylines.length === 0 && movers.length === 0) {
    return null;
  }
  return (
    <section className="mt-4 rounded-md border border-line bg-panel-soft/40 p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">本周雷达</h2>
        <span className="text-xs text-ink-dim">正在发展的事件与异动主题 · 自动生成</span>
      </div>
      <div className="mt-3 grid gap-5 lg:grid-cols-[1fr_260px]">
        {payload.storylines.length > 0 ? (
          <ol className="space-y-2.5">
            {payload.storylines.map((story, index) => (
              <li key={story.event_id} className="flex items-baseline gap-3">
                <span className="readout w-4 shrink-0 text-sm font-semibold text-signal">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <a
                    className="title-link text-sm font-medium leading-6 text-ink"
                    href={`/event/${encodeURIComponent(story.event_id)}`}
                  >
                    {story.title}
                  </a>
                  <span className="ml-2 whitespace-nowrap text-xs tabular-nums text-ink-dim">
                    跨 {story.days} 天 · {story.source_count} 家信源
                  </span>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
        {movers.length > 0 ? (
          // 三列定宽表格:名称 | 上周 | 本周。数字各自在定宽列里右对齐,
          // 位数不同也不会左右跳;涨跌方向由列头语序 + 本周高亮承担,
          // 不再用箭头符号——它在数字位数变化时永远对不齐
          <div className={payload.storylines.length > 0 ? "lg:border-l lg:border-line lg:pl-5" : ""}>
            <div className="grid grid-cols-[minmax(0,1fr)_2.5rem_2.5rem] items-baseline gap-x-3 text-xs">
              <span className="font-semibold text-ink-mid">异动主题</span>
              <span className="text-right text-ink-dim">上周</span>
              <span className="text-right text-ink-dim">本周</span>
            </div>
            <ul className="mt-1.5 divide-y divide-line/60">
              {movers.map((topic) => (
                <li key={topic.id}>
                  <a
                    className="group grid grid-cols-[minmax(0,1fr)_2.5rem_2.5rem] items-baseline gap-x-3 py-2 text-sm"
                    href={`/topics/${encodeURIComponent(topic.id)}`}
                  >
                    <span className="truncate font-medium text-ink group-hover:text-signal">
                      {topic.name}
                    </span>
                    <span className="readout text-right text-xs tabular-nums text-ink-dim">
                      {topic.prev_week_count}
                    </span>
                    <span className="readout text-right text-xs font-semibold tabular-nums text-signal">
                      {topic.week_count}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function TopicCard({ topic }: { topic: TopicSummary }) {
  const trend = weekTrend(topic);
  return (
    <a
      className="group card-hover editorial-feed-hover flex flex-col rounded-md border border-line bg-panel p-4"
      href={`/topics/${encodeURIComponent(topic.id)}`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold text-ink group-hover:text-signal">
          {topic.name}
        </span>
        <span
          className={`shrink-0 text-xs tabular-nums ${
            trend === "up" ? "font-semibold text-signal" : "text-ink-mid"
          }`}
        >
          {trend === "up" ? "↑ " : trend === "down" ? "↓ " : ""}本周 {topic.week_count}
        </span>
      </div>
      <p className="mt-1.5 line-clamp-2 flex-1 text-xs leading-5 text-ink-dim">
        {topic.description}
      </p>
      <div className="mt-2.5 text-xs text-ink-mid">
        精选 {topic.count} 条 · {freshnessLabel(topic.latest_published_at)}
      </div>
    </a>
  );
}

export default async function TopicsPage() {
  const payload = await getTopics();

  return (
    <main className="editorial-page min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[248px_1fr]">
        <Sidebar activeNavId="topics" />
        <MobileNav activeNavId="topics" />

        <section className="w-full min-w-0 max-w-[1320px] justify-self-center px-4 py-8 md:px-8 xl:px-12">
          <header className="border-b border-line-strong pb-7">
            <p className="readout text-[11px] uppercase tracking-[0.16em] text-signal">LIVING INDEX / TOPICS</p>
            <h1 className="editorial-rule-title mt-4 text-4xl font-medium leading-none text-ink md:text-6xl">主题</h1>
            <p className="mt-1.5 text-sm text-ink-mid">
              公司与模型、技术方向——每个主题一条持续更新的精选档案
              {payload.article_count > 0
                ? ` · 近 ${payload.window_days} 天覆盖 ${payload.article_count} 条精选`
                : ""}
            </p>
          </header>

          {payload.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {payload.error}
            </div>
          ) : null}

          <WeeklyRadarStrip payload={payload} />

          <div className="mt-6 space-y-8">
            {payload.groups.map((group) => {
              const sorted = sortByActivity(group.topics);
              const active = sorted.filter((topic) => topic.count >= DORMANT_THRESHOLD);
              const dormant = sorted.filter((topic) => topic.count < DORMANT_THRESHOLD);
              return (
                <section key={group.id}>
                  <div className="flex items-end justify-between gap-4">
                    <h2 className="editorial-rule-title text-2xl font-medium text-ink">{group.name}</h2>
                    <span className="hidden text-sm text-ink-dim sm:block">
                      {group.description}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {active.map((topic) => (
                      <TopicCard key={topic.id} topic={topic} />
                    ))}
                  </div>
                  {dormant.length > 0 ? (
                    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink-dim">
                      <span>近期沉寂：</span>
                      {dormant.map((topic) => (
                        <a
                          key={topic.id}
                          className="text-ink-mid underline-offset-2 hover:text-signal hover:underline"
                          href={`/topics/${encodeURIComponent(topic.id)}`}
                        >
                          {topic.name}（{topic.count}）
                        </a>
                      ))}
                    </div>
                  ) : null}
                </section>
              );
            })}
            {payload.groups.length === 0 && !payload.error ? (
              <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
                主题数据正在积累中，稍后再来看看。
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
