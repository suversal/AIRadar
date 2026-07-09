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
      <section className="rounded-md border border-line bg-panel p-6 text-sm leading-7 text-ink-mid">
        <p>
          AI·RADAR 持续监听 27 个高信噪比信源——各大实验室官方博客、arXiv、GitHub
          Trending、Hacker News、Reddit 社区与中英文科技媒体——用 AI
          对每篇文章做相关性预筛、六维评分、分类打标和中文摘要，每天沉淀为一期精选日报。
        </p>
        <p className="mt-4">
          评分综合 AI 相关度、新颖性、影响力、信息密度、可操作性与创作者价值六个维度，
          并叠加信源权威度与时效衰减。只有跨过分类阈值的事件才会进入精选；其余动态全部保留在
          「全部 AI 动态」中可查。
        </p>
        <p className="mt-4">
          英文精选文章附 AI 中文翻译，GitHub 项目附 README 原文。原文版权归原作者所有，
          本站仅做聚合与导读，每条事件都保留阅读原文入口。
        </p>
      </section>

      <section className="rounded-md border border-line bg-panel p-6 text-sm leading-7 text-ink-mid">
        <h2 className="text-base font-semibold text-ink">数据口径</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>抓取频率：可配置，默认每 2 小时一轮</li>
          <li>精选规模：每日 12 个事件聚类</li>
          <li>全量视野：所有通过 AI 预筛的动态（含未达精选阈值的）</li>
          <li>主题体系：公司与模型 / 技术方向 / 内容形态 三组</li>
        </ul>
      </section>
    </StaticPage>
  );
}
