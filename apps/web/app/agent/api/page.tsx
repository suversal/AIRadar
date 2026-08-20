import { ArrowLeft } from "lucide-react";

import { StaticPage } from "@/components/static-page";

import { ApiReference } from "../api-reference";

export const metadata = {
  title: "REST API 参考",
  description: "AI·RADAR REST API v1 的端点、参数、字段、缓存与错误恢复参考。",
  alternates: { canonical: "/agent/api" },
};

export default function AgentApiPage() {
  return (
    <StaticPage
      activeNavId="agent"
      title="REST API 参考"
      subtitle="完整参数与错误处理；第一次接入请从 Quick Start 开始"
    >
      <a
        href="/agent#rest"
        className="inline-flex min-h-10 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm text-ink-mid transition-colors hover:border-signal/40 hover:text-signal"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        返回 Agent 接入
      </a>
      <ApiReference />
    </StaticPage>
  );
}
