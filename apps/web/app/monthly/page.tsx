import { PeriodReportPage } from "../reports/period-report-page";

export default function MonthlyPage() {
  return (
    <PeriodReportPage
      mode="monthly"
      title="AI·RADAR 月报"
      mainlineLabel="本期主线"
      highlightsTitle="本期看点"
      themeLabel="本期主题"
    />
  );
}
