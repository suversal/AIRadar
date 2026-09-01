import { NewsletterTokenAction } from "@/components/newsletter-token-action";
import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "确认订阅周报",
  robots: { index: false, follow: false },
};

export default async function ConfirmNewsletterPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token = "" } = await searchParams;
  return (
    <StaticPage
      activeNavId="daily"
      title="确认订阅"
      subtitle="最后一步：确认这是你本人提交的邮箱。确认后只接收每周封版周报。"
      compact
    >
      <NewsletterTokenAction action="confirm" token={token} />
    </StaticPage>
  );
}
