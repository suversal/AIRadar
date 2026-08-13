import { PeriodReportPage } from "../reports/period-report-page";

/** 必须动态渲染，不能在构建期预渲染。
 *
 *  这个页面的内容全部来自后端 API，而 API 在 `docker build` 阶段是**不可达的**
 *  （web 镜像单独构建，那时 compose 网络里还没有 api 服务）。一旦被预渲染，
 *  lib/api.ts 的降级 payload——也就是"API 服务暂时不可用"——会被直接烤进静态
 *  HTML，然后按 revalidate 周期一直发给用户。
 *
 *  2026-08-13 加数据缓存时真踩过：`cache: "no-store"` 一去掉，这个页面就从
 *  动态渲染变成了 ISR 静态页，上线后 /weekly /monthly /topics 三个页面直接
 *  展示报错文案。见 docs/2026-08-13-hardening-plan.md。
 *
 *  性能不受影响：HTML 由 nginx 缓存（infra/nginx/radar-cf.conf，180s），
 *  取数由 Next 数据缓存兜（lib/api.ts 的 cacheFor），两层都还在。 */
export const dynamic = "force-dynamic";

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
