import { PeriodReportPage } from "../../reports/period-report-page";

export const metadata = {
  title: "AI·RADAR 周报",
};

export default async function ArchivedWeeklyPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return (
    <PeriodReportPage
      mode="weekly"
      title="AI·RADAR 周报"
      mainlineLabel="本期主线"
      highlightsTitle="本期看点"
      themeLabel="本期主题"
      periodKey={key}
    />
  );
}
