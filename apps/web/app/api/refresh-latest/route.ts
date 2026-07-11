import { getApiBaseUrl } from "@/lib/api";
import { getAdminToken } from "@/lib/admin-api";

async function jsonFromResponse(response: Response) {
  const text = await response.text();
  if (!text) {
    return {
      status: "error",
      detail: "刷新接口返回了空响应，已避免 Unexpected end of JSON input。",
    };
  }
  try {
    return JSON.parse(text);
  } catch {
    return {
      status: "error",
      detail: "刷新接口返回了非 JSON 响应。",
    };
  }
}

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const refreshUrl = new URL(`${getApiBaseUrl()}/api/admin/refresh-latest-async`);
  for (const name of ["limit"]) {
    const value = requestUrl.searchParams.get(name);
    if (value) {
      refreshUrl.searchParams.set(name, value);
    }
  }

  try {
    const token = await getAdminToken();
    const response = await fetch(refreshUrl.toString(), {
      method: "POST",
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const payload = await jsonFromResponse(response);

    return Response.json(payload, { status: response.status });
  } catch (error) {
    return Response.json(
      {
        status: "error",
        detail: error instanceof Error ? error.message : "刷新服务暂时不可用。",
      },
      { status: 502 },
    );
  }
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const jobId = requestUrl.searchParams.get("job_id");
  if (!jobId) {
    return Response.json({ status: "error", detail: "缺少 job_id。" }, { status: 400 });
  }

  try {
    const token = await getAdminToken();
    const response = await fetch(
      `${getApiBaseUrl()}/api/admin/refresh-jobs/${encodeURIComponent(jobId)}`,
      {
        cache: "no-store",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );
    const payload = await jsonFromResponse(response);

    return Response.json(payload, { status: response.status });
  } catch (error) {
    return Response.json(
      {
        status: "error",
        detail: error instanceof Error ? error.message : "刷新状态暂时不可用。",
      },
      { status: 502 },
    );
  }
}
