import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "反馈 · AI·RADAR",
};

export default function FeedbackPage() {
  return (
    <StaticPage
      activeNavId="feedback"
      title="反馈"
      subtitle="告诉我们哪里可以做得更好"
    >
      <section className="rounded-md border border-line bg-panel p-6 text-sm leading-7 text-ink-mid">
        <p>欢迎反馈以下任何内容：</p>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>某条情报的评分、分类或翻译不准确</li>
          <li>值得接入的新信源</li>
          <li>希望增加的主题或功能</li>
          <li>页面显示问题</li>
        </ul>
        <a
          className="mt-6 inline-flex rounded-md border border-signal/40 bg-signal/10 px-5 py-3 text-sm font-semibold text-signal hover:border-signal/60 hover:text-signal-bright"
          href="mailto:suyloveslife@gmail.com?subject=AI·RADAR 反馈"
        >
          发送邮件反馈
        </a>
        <p className="mt-4 text-xs text-ink-dim">
          反馈邮件请附上具体的事件标题或页面链接，方便定位问题。
        </p>
      </section>
    </StaticPage>
  );
}
