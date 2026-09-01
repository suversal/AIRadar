import { WeeklySubscribeForm } from "@/components/weekly-subscribe-form";
import { StaticPage } from "@/components/static-page";
import { getAdminToken, verifyAdminToken } from "@/lib/admin-api";
import { redirect } from "next/navigation";

export const metadata = {
  title: "周报订阅私测",
  robots: { index: false, follow: false },
};

export default async function SubscribeNewsletterPage() {
  const token = await getAdminToken();
  if (!token || !(await verifyAdminToken(token))) {
    redirect("/admin/login?next=%2Fnewsletter%2Fsubscribe");
  }

  return (
    <StaticPage
      activeNavId="weekly"
      title="周报订阅私测"
      subtitle="这个入口暂不对外展示，仅用于订阅、确认和邮件送达测试。"
      compact
    >
      <WeeklySubscribeForm source="private_test_page" />
    </StaticPage>
  );
}
