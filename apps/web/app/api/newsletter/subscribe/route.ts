import { newsletterProxy } from "@/lib/newsletter/http";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "请求格式不正确。" }, { status: 400 });
  }
  return newsletterProxy("subscribe", body, request);
}
