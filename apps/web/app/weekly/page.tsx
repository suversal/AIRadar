import { PeriodReportPage } from "../reports/period-report-page";

export default function WeeklyPage() {
  return (
    <PeriodReportPage
      mode="weekly"
      title="AI·RADAR 周报"
      mainlineLabel="本期主线"
      highlightsTitle="本期看点"
      themeLabel="本期主题"
    />
  );
}
