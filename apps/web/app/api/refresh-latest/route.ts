import { getApiBaseUrl } from "@/lib/api";

export async function POST() {
  const response = await fetch(`${getApiBaseUrl()}/api/admin/refresh-latest`, {
    method: "POST",
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({
    status: "error",
    detail: "刷新接口返回了非 JSON 响应。",
  }));

  return Response.json(payload, { status: response.status });
}
