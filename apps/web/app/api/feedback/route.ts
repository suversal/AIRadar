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

/** 把真实访客 IP 透传给后端。
 *
 *  链路是 CF → nginx → 这个 route → api。nginx 在 real_ip 还原之后写了
 *  X-Real-IP / X-Forwarded-For，但这一跳如果不主动带上，后端看到的就只有
 *  docker 网络里 web 容器的地址，日志等于白记。 */
function clientIp(request: Request): string | null {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    return forwarded.split(",")[0]!.trim() || null;
  }
  return request.headers.get("x-real-ip");
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "请求格式不正确。" }, { status: 400 });
  }

  const ip = clientIp(request);
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/feedback`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(ip ? { "X-Forwarded-For": ip } : {}),
      },
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
