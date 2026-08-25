import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "关于",
  description: "AI·RADAR 是为创作者和开发者准备的 AI 情报雷达：监听数十个高信噪比信源，AI 评分聚类去重，每天一期精选日报。",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <StaticPage
      activeNavId="about"
      title="关于 AI·RADAR"
      subtitle="为创作者和开发者准备的 AI 情报雷达"
    >
      <section className="py-1">
        <p className="text-xs uppercase tracking-[0.3em] text-signal-dim">WHY AI·RADAR</p>
        <h2 className="editorial-rule-title mt-4 text-3xl font-medium leading-snug text-ink md:text-4xl">
          AI 圈子每天都在发生什么，
          <br />
          不该靠反复刷十几个信源才知道。
        </h2>
        <p className="mt-5 max-w-2xl text-sm leading-7 text-ink-mid">
          AI·RADAR 持续监听多个高信噪比信源——各大实验室官方博客、热门社区、X账号、微信公众号与中英文科技媒体。用 AI
          做相关性筛选、六维评分和同事件聚类，把同一件事在多个信源里的重复报道折叠成一条，
          每天沉淀为一期精选日报。
        </p>
      </section>

      <section className="border-l-2 border-signal py-1 pl-5 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-signal-bright">评分与筛选口径</h2>
        <p className="mt-2">
          评分综合 AI 相关度、新颖性、影响力、信息密度、可操作性与创作者价值六个维度，
          并叠加信源权威度与时效衰减。只有跨过分类阈值的事件才会进入精选；其余动态全部保留在
          「全部 AI 动态」中可查，不会因为没入选就彻底消失。
        </p>
      </section>

      <section className="py-2">
        <h2 className="text-base font-semibold text-ink">数据口径</h2>
        <div className="mt-5 grid grid-cols-2 gap-y-6 sm:grid-cols-4 sm:divide-x sm:divide-line">
          {[
            { label: "抓取频率", value: "每 2 小时一轮" },
            { label: "精选标准", value: "评分过线即入选" },
            { label: "全量视野", value: "相关即收录，可查可搜" },
            { label: "主题体系", value: "公司模型 / 技术方向 / 内容形态" },
          ].map((stat) => (
            <div key={stat.label} className="px-3 py-4 text-center">
              <div className="readout text-sm font-semibold text-signal">{stat.value}</div>
              <div className="mt-1 text-xs text-ink-dim">{stat.label}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-panel/45 px-5 py-5 text-sm leading-7 text-ink-mid">
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
