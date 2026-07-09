import { getTopics } from "@/lib/api";
import { Sidebar } from "@/components/sidebar";

export const metadata = {
  title: "主题 · AIHOT",
};

function topicHref(topicId: string) {
  return `/all?topic=${encodeURIComponent(topicId)}`;
}

export default async function TopicsPage() {
  const payload = await getTopics();

  return (
    <main className="min-h-screen bg-[#070d1a] text-slate-100">
      <div className="grid min-h-screen lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="topics" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-slate-800 bg-slate-900/80 p-6 shadow-[0_20px_80px_rgba(0,0,0,0.25)]">
            <h1 className="text-3xl font-semibold text-slate-100">主题</h1>
            <p className="mt-2 text-sm text-slate-500">
              按公司、技术方向和内容形态浏览近 30 天的 AI 动态
              {payload.article_count > 0 ? ` · 覆盖 ${payload.article_count} 条` : ""}
            </p>
          </header>

          {payload.error ? (
            <div className="mt-5 rounded-md border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-6 text-amber-200">
              {payload.error}
            </div>
          ) : null}

          <div className="mt-8 space-y-12">
            {payload.groups.map((group) => (
              <section key={group.id}>
                <div className="flex items-end justify-between gap-4">
                  <h2 className="text-xl font-semibold text-slate-100">{group.name}</h2>
                  <span className="text-sm text-slate-600">{group.description}</span>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {group.topics.map((topic) => (
                    <a
                      key={topic.id}
                      className="group rounded-md border border-slate-800 bg-slate-900/70 p-5 transition hover:border-cyan-400/40 hover:bg-slate-900"
                      href={topicHref(topic.id)}
                    >
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-base font-semibold text-slate-100 group-hover:text-cyan-300">
                          {topic.name}
                        </span>
                        <span className="text-sm tabular-nums text-slate-500">{topic.count}</span>
                      </div>
                      <div className="mt-2 text-xs text-slate-600">查看 {topic.count} 条动态</div>
                    </a>
                  ))}
                </div>
              </section>
            ))}
            {payload.groups.length === 0 && !payload.error ? (
              <div className="rounded-md border border-slate-800 bg-slate-900/80 p-8 text-sm text-slate-500">
                暂无主题数据，先运行一轮抓取和处理后再来。
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
