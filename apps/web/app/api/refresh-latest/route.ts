import { getApiBaseUrl } from "@/lib/api";

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const refreshUrl = new URL(`${getApiBaseUrl()}/api/admin/refresh-latest`);
  for (const name of ["limit", "top_n"]) {
    const value = requestUrl.searchParams.get(name);
    if (value) {
      refreshUrl.searchParams.set(name, value);
    }
  }

  const response = await fetch(refreshUrl.toString(), {
    method: "POST",
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({
    status: "error",
    detail: "刷新接口返回了非 JSON 响应。",
  }));

  return Response.json(payload, { status: response.status });
}
