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
      compact
      activeNavId="agent"
      title="REST API 参考"
      subtitle="完整参数与错误处理；第一次接入请从 Quick Start 开始"
    >
      <ApiReference />
    </StaticPage>
  );
}
