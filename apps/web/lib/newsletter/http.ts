import { getApiBaseUrl } from "@/lib/api";

export async function newsletterProxy(
  path: "subscribe" | "confirm" | "unsubscribe",
  body: unknown,
  request?: Request,
) {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/public/newsletter/${path}`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(request ? forwardedIpHeader(request) : {}),
      },
      body: JSON.stringify(body),
    });
    const text = await response.text();
    let payload: unknown = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { detail: "订阅服务返回了无法识别的响应。" };
    }
    return Response.json(payload, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      { detail: "订阅服务暂时不可用，请稍后再试。" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

function forwardedIpHeader(request: Request): Record<string, string> {
  const forwarded = request.headers.get("x-forwarded-for");
  const ip = forwarded?.split(",")[0]?.trim() || request.headers.get("x-real-ip") || "";
  return ip ? { "X-Forwarded-For": ip } : {};
}
