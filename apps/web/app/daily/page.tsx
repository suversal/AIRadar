import { redirect } from "next/navigation";
import { getLatestReport } from "@/lib/api";

export default async function DailyPage() {
  const latest = await getLatestReport();

  if (latest.report_date) {
    redirect(`/daily/${latest.report_date}`);
  }

  return (
    <main className="min-h-screen bg-[var(--background)] px-5 py-8 text-[var(--foreground)]">
      <div className="mx-auto max-w-3xl">
        <p className="text-sm text-[var(--muted)]">Suversal AI Radar</p>
        <h1 className="mt-2 text-3xl font-semibold">日报</h1>
        <p className="mt-4 text-[var(--muted)]">暂无可跳转的最新日报。</p>
        <a className="mt-6 inline-block text-[var(--accent)] underline" href="/latest">
          查看最新情报
        </a>
      </div>
    </main>
  );
}
