import { getApiBaseUrl } from "@/lib/api";

async function jsonFromResponse(response: Response) {
  const text = await response.text();
  if (!text) {
    return { detail: "反馈接口返回了空响应。" };
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: "反馈接口返回了非 JSON 响应。" };
  }
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "请求格式不正确。" }, { status: 400 });
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/feedback`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await jsonFromResponse(response);
    return Response.json(payload, { status: response.status });
  } catch (error) {
    return Response.json(
      { detail: error instanceof Error ? error.message : "反馈服务暂时不可用。" },
      { status: 502 },
    );
  }
}
