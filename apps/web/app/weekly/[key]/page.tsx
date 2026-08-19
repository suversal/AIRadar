import { WeeklyReportPage } from "../../reports/weekly-report-page";

export const metadata = {
  title: "AI 周报",
};

export default async function ArchivedWeeklyPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return <WeeklyReportPage periodKey={key} />;
}
