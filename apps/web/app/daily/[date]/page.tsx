import { getDailyReport } from "@/lib/api";
import { DailyReportView } from "../report-view";

type DailyDateParams = Promise<{
  date: string;
}>;

export default async function DailyDatePage({ params }: { params: DailyDateParams }) {
  const { date } = await params;
  const report = await getDailyReport(date);

  return <DailyReportView report={report} />;
}
