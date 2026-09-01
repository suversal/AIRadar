import { newsletterProxy } from "@/lib/newsletter/http";

export async function POST(request: Request) {
  const tokenFromUrl = new URL(request.url).searchParams.get("token");
  if (tokenFromUrl) {
    // RFC 8058 one-click unsubscribe: mail clients POST to the URL declared
    // in List-Unsubscribe.  The body is intentionally irrelevant.
    return newsletterProxy("unsubscribe", { token: tokenFromUrl }, request);
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "请求格式不正确。" }, { status: 400 });
  }
  return newsletterProxy("unsubscribe", body, request);
}
