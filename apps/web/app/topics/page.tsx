import { getTopics } from "@/lib/api";
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
  description: "按模型、产品工具、技术方向和公司行业浏览近 30 天的 AI 动态。",
  alternates: { canonical: "/topics" },
};

function topicHref(topicId: string) {
  return `/all?topic=${encodeURIComponent(topicId)}`;
}

export default async function TopicsPage() {
  const payload = await getTopics();

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="grid min-h-screen grid-cols-1 content-start lg:grid-cols-[224px_1fr]">
        <Sidebar activeNavId="topics" />
        <MobileNav activeNavId="topics" />

        <section className="px-5 py-6 md:px-9">
          <header className="rounded-md border border-line bg-panel p-5">
            <h1 className="text-2xl font-semibold text-ink">主题</h1>
            <p className="mt-1.5 text-sm text-ink-mid">
              按模型、产品工具、技术方向和公司行业浏览近 30 天的 AI 动态
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
                主题数据正在积累中，稍后再来看看。
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
