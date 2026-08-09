import { PeriodReportPage } from "../reports/period-report-page";

export const metadata = {
  title: "AI 周报",
  description: "本周日报的汇总提炼：AI 梳理出一条主线综述，附各主题看点与代表内容。",
};

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
