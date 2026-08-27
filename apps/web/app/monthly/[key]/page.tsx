import { MonthlyReportPage } from "../../reports/monthly-report-page";

export async function generateMetadata({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return {
    title: `AI 月报 ${key}`,
    description: `${key} AI 月报：当月趋势、代表事件与完整榜单。`,
    alternates: { canonical: `/monthly/${key}` },
  };
}

export default async function ArchivedMonthlyPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return <MonthlyReportPage periodKey={key} />;
}
