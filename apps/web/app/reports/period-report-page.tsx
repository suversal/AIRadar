import { getPeriodReport } from "@/lib/api";
import { eventHref } from "@/lib/events";
import { buildPeriodDigest, type PeriodMode } from "./report-data";
import { ReportShell } from "./report-shell";

function secondaryItems(mode: PeriodMode) {
  if (mode === "weekly") {
    return [
      ["第5周", "模型军备竞赛与智能体落地"],
      ["第4周", "智能体生态加速成型"],
      ["第3周", "AI应用资金时代与地缘博弈"],
      ["第2周", "超级应用与模型军备竞赛"],
    ];
  }
  return [
    ["6月", "AI基础设施与智能体生态加速"],
    ["5月", "模型开源与智能体生态加速"],
  ];
}

function labelFor(mode: PeriodMode) {
  return mode === "weekly" ? "周报" : "月报";
}

export async function PeriodReportPage({
  mode,
  title,
  mainlineLabel,
  highlightsTitle,
  themeLabel,
}: {
  mode: PeriodMode;
  title: string;
  mainlineLabel: string;
  highlightsTitle: string;
  themeLabel: string;
}) {
  const period = await getPeriodReport(mode);
  const digest = buildPeriodDigest(period, mode);

  return (
    <ReportShell
      activeMode={mode}
      secondary={
        <div className="mt-6 space-y-2">
          {secondaryItems(mode).map(([period, label], index) => (
            <a
              key={period}
              className={`grid grid-cols-[48px_1fr] gap-3 rounded-md px-3 py-3 text-sm ${
                index === 0 ? "bg-emerald-400/15 text-emerald-300" : "text-slate-500 hover:text-slate-300"
              }`}
              href={mode === "weekly" ? "/weekly" : "/monthly"}
            >
              <span>{period}</span>
              <span className="line-clamp-2">{label}</span>
            </a>
          ))}
        </div>
      }
    >
      <div className="mx-auto max-w-4xl">
        <header className="py-8">
          <div className="flex items-center gap-4 text-xs font-semibold uppercase tracking-[0.35em] text-slate-600">
            <span className="h-px w-12 bg-emerald-400" />
            <span>{digest.issueMeta}</span>
          </div>
          <h1
            aria-label={title}
            className="mt-8 text-6xl font-semibold leading-none tracking-normal text-slate-100 md:text-8xl"
          >
            <span className="text-slate-100">AI</span>
            <span className="text-emerald-400">HOT</span> {labelFor(mode)}
          </h1>
          <div className="mt-8 grid items-center gap-4 text-sm text-slate-500 md:grid-cols-[auto_1fr_auto]">
            <span>{digest.range}</span>
            <span className="hidden h-px bg-slate-800 md:block" />
            <span>{digest.label} · 编辑系统自动融合</span>
          </div>
        </header>

        <section className="rounded-md border-l-4 border-emerald-400 bg-emerald-400/15 p-6">
          <div className="text-sm font-semibold text-emerald-300">{mainlineLabel}</div>
          <h2 className="mt-3 text-3xl font-semibold leading-tight text-slate-100">{digest.mainline.title}</h2>
          <p className="mt-4 text-sm leading-7 text-slate-300">{digest.mainline.body}</p>
        </section>

        <div className="mt-6 grid gap-3 md:grid-cols-4">
          {digest.stats.map((stat) => (
            <div key={stat.label} className="rounded-md border border-slate-800 bg-slate-900/60 p-4 text-center">
              <div className="text-2xl font-semibold text-slate-100">{stat.value}</div>
              <div className="mt-1 text-xs text-slate-600">{stat.label}</div>
            </div>
          ))}
        </div>

        <section className="mt-10 rounded-md border border-slate-800 bg-slate-900/80 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-slate-100">{highlightsTitle}</h2>
            <div className="text-sm text-slate-600">
              {digest.highlights.length} 个主题 · {period.items.length} 篇报道
            </div>
          </div>
          <div className="mt-4 divide-y divide-slate-800">
            {digest.highlights.map((highlight, index) => (
              <a
                key={highlight.label}
                className="grid gap-2 py-3 text-sm md:grid-cols-[36px_1fr_40px]"
                href={eventHref(highlight.items[0])}
              >
                <span className="font-semibold text-emerald-400">{String(index + 1).padStart(2, "0")}</span>
                <span className="font-semibold text-slate-200">{highlight.label}：{highlight.title}</span>
                <span className="text-slate-600 md:text-right">{highlight.count}</span>
              </a>
            ))}
          </div>
        </section>

        <div className="mt-14 space-y-12">
          {digest.sections.map((section, index) => (
            <section key={section.label}>
              <div className="flex items-end justify-between gap-4">
                <h2 className="text-3xl font-semibold text-slate-100">
                  <span className="mr-4 text-5xl text-emerald-400">{String(index + 1).padStart(2, "0")}</span>
                  {themeLabel}：{section.label}
                </h2>
                <span className="text-sm font-semibold text-emerald-400">{section.count} 篇</span>
              </div>
              <p className="mt-6 text-sm leading-7 text-slate-400">
                {section.items[0]?.summary ?? section.items[0]?.one_line_summary ?? "暂无主题摘要。"}
              </p>
              <div className="mt-5 grid gap-4">
                {section.items.slice(0, 3).map((item) => (
                  <article key={item.event_id} className="rounded-md border border-slate-800 bg-slate-900/70 p-5">
                    <h3 className="text-lg font-semibold text-slate-100">
                      <a href={eventHref(item)}>{item.title}</a>
                    </h3>
                    <p className="mt-3 text-sm leading-6 text-slate-500">
                      {item.reason ?? item.one_line_summary ?? "暂无推荐理由。"}
                    </p>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </ReportShell>
  );
}
