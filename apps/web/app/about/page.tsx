import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "关于 · AI·RADAR",
};

export default function AboutPage() {
  return (
    <StaticPage
      activeNavId="about"
      title="关于 AI·RADAR"
      subtitle="为创作者和开发者准备的 AI 情报雷达"
    >
      <section className="rounded-md border border-line bg-panel p-6 text-center">
        <p className="text-xs uppercase tracking-[0.3em] text-ink-dim">关于 AI·RADAR</p>
        <h2 className="mt-4 text-xl font-semibold leading-relaxed text-ink md:text-2xl">
          AI 圈子每天都在发生什么，
          <br />
          不该靠反复刷十几个信源才知道。
        </h2>
        <p className="mx-auto mt-5 max-w-xl text-sm leading-6 text-ink-mid">
          AI·RADAR 持续监听 27 个高信噪比信源——各大实验室官方博客、arXiv、GitHub
          Trending、Hacker News、Reddit 社区与中英文科技媒体，用 AI 做相关性预筛、
          六维评分和事件聚类，把同一件事在多个信源里的重复报道折叠成一条，
          每天沉淀为一期精选日报。
        </p>
      </section>

      <section className="rounded-md border border-line bg-panel p-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-ink">评分与筛选口径</h2>
        <p>
          评分综合 AI 相关度、新颖性、影响力、信息密度、可操作性与创作者价值六个维度，
          并叠加信源权威度与时效衰减。只有跨过分类阈值的事件才会进入精选；其余动态全部保留在
          「全部 AI 动态」中可查，不会因为没入选就彻底消失。
        </p>
        <p className="mt-4">英文精选文章附 AI 中文翻译，GitHub 项目附 README 原文。</p>
      </section>

      <section className="rounded-md border border-line bg-panel p-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-ink">数据口径</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>抓取频率：可配置，默认每 2 小时一轮</li>
          <li>精选规模：每日 12 个事件聚类</li>
          <li>全量视野：所有通过 AI 预筛的动态（含未达精选阈值的）</li>
          <li>主题体系：公司与模型 / 技术方向 / 内容形态 三组</li>
        </ul>
      </section>

      <section className="rounded-md border border-signal/30 bg-signal/5 p-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-signal-bright">免责声明</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>
            本站是聚合摘要与阅读索引：评分、分类、标签、中文摘要与翻译均由 AI
            自动生成，可能存在偏差或错误，不代表原作者或信源立场，仅供参考。
          </li>
          <li>
            原文版权归各来源方所有，本站不主张任何原创权利，每条内容都保留跳转阅读原文的入口。
          </li>
          <li>涉及融资、市场、行业数据等内容仅为信息摘录，不构成投资或其他决策建议。</li>
          <li>
            如果你是信源方，希望更正内容、下架收录或调整展示方式，欢迎通过
            <a className="mx-1 text-signal underline hover:text-signal-bright" href="/feedback">
              反馈页
            </a>
            联系我们。
          </li>
        </ul>
      </section>
    </StaticPage>
  );
}
