import { PeriodReportPage } from "../reports/period-report-page";

export const metadata = {
  title: "AI 月报",
  description: "当月日报的汇总提炼：AI 梳理出一条主线综述，附各主题看点与代表内容。",
};

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
