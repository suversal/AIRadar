import { getTopics } from "@/lib/api";
import { MobileNav } from "@/components/mobile-nav";
import { Sidebar } from "@/components/sidebar";

export const metadata = {
  title: "主题 · AI·RADAR",
};

function topicHref(topicId: string) {
  return `/all?topic=${encodeURIComponent(topicId)}`;
}

export default async function TopicsPage() {
  const payload = await getTopics();

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="topics" />
        <MobileNav activeNavId="topics" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <h1 className="text-2xl font-semibold text-ink">主题</h1>
            <p className="mt-1.5 text-sm text-ink-mid">
              按公司、技术方向和内容形态浏览近 30 天的 AI 动态
              {payload.article_count > 0 ? ` · 覆盖 ${payload.article_count} 条` : ""}
            </p>
          </header>

          {payload.error ? (
            <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 p-4 text-sm leading-6 text-danger">
              {payload.error}
            </div>
          ) : null}

          <div className="mt-6 space-y-8">
            {payload.groups.map((group) => (
              <section key={group.id}>
                <div className="flex items-end justify-between gap-4">
                  <h2 className="text-lg font-semibold text-ink">{group.name}</h2>
                  <span className="text-sm text-ink-dim">{group.description}</span>
                </div>
                <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {group.topics.map((topic) => (
                    <a
                      key={topic.id}
                      className="group card-hover rounded-md border border-line bg-panel p-4"
                      href={topicHref(topic.id)}
                    >
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-sm font-semibold text-ink group-hover:text-signal">
                          {topic.name}
                        </span>
                        <span className="text-xs tabular-nums text-ink-mid">{topic.count}</span>
                      </div>
                      <div className="mt-1.5 text-xs text-ink-dim">查看 {topic.count} 条动态</div>
                    </a>
                  ))}
                </div>
              </section>
            ))}
            {payload.groups.length === 0 && !payload.error ? (
              <div className="rounded-md border border-line bg-panel p-8 text-sm text-ink-mid">
                暂无主题数据，先运行一轮抓取和处理后再来。
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
