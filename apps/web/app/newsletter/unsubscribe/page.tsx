import { NewsletterTokenAction } from "@/components/newsletter-token-action";
import { StaticPage } from "@/components/static-page";

export const metadata = {
  title: "取消订阅周报",
  robots: { index: false, follow: false },
};

export default async function UnsubscribeNewsletterPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token = "" } = await searchParams;
  return (
    <StaticPage
      activeNavId="daily"
      title="取消订阅"
      subtitle="确认后，这个邮箱将不再收到 AI·RADAR 周报。以后仍可在周报页重新订阅。"
      compact
    >
      <NewsletterTokenAction action="unsubscribe" token={token} />
    </StaticPage>
  );
}
