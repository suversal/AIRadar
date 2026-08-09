import { PeriodReportPage } from "../../reports/period-report-page";

export const metadata = {
  title: "AI 月报",
};

export default async function ArchivedMonthlyPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return (
    <PeriodReportPage
      mode="monthly"
      title="AI·RADAR 月报"
      mainlineLabel="本期主线"
      highlightsTitle="本期看点"
      themeLabel="本期主题"
      periodKey={key}
    />
  );
}
