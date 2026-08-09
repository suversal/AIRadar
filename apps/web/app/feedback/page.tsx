import { FeedbackForm } from "@/components/feedback-form";
import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "反馈",
  description: "打分不准、页面出错、想要的功能——写下来就好，每一条都会看到。",
};

export default function FeedbackPage() {
  return (
    <StaticPage
      activeNavId="feedback"
      title="反馈"
      subtitle="打分不准、页面出错、想要的功能——写下来就好，每一条都会看到。"
    >
      <section className="rounded-md border border-line bg-panel p-6">
        <FeedbackForm />
      </section>

      <section className="rounded-md border border-line bg-panel p-5 text-sm leading-7 text-ink-mid">
          <p>也欢迎反馈以下任何内容：</p>
          <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>某条情报的评分、分类或翻译不准确</li>
              <li>值得接入的新信源</li>
              <li>希望增加的主题或功能</li>
              <li>页面显示问题</li>
          </ul>
          <p className="mt-4 text-xs text-ink-dim">
              留言时附上具体的事件标题或页面链接，方便定位问题；留了邮箱的话我会尽量回信。
          </p>
      </section>
    </StaticPage>
  );
}
