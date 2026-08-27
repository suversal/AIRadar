import { WeeklyReportPage } from "../../reports/weekly-report-page";

export async function generateMetadata({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return {
    title: `AI 周报 ${key}`,
    description: `${key} AI 周报：本周主线、栏目概述与完整入选名单。`,
    alternates: { canonical: `/weekly/${key}` },
  };
}

export default async function ArchivedWeeklyPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return <WeeklyReportPage periodKey={key} />;
}
