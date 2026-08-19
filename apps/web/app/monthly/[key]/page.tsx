import { MonthlyReportPage } from "../../reports/monthly-report-page";

export const metadata = {
  title: "AI 月报",
};

export default async function ArchivedMonthlyPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return <MonthlyReportPage periodKey={key} />;
}
