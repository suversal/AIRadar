import { getApiBaseUrl } from "@/lib/api";
import { getAdminToken } from "@/lib/admin-api";

/** Generic browser→API proxy for the admin console: forwards the request
 *  to /api/admin/<path> with the token from the HttpOnly cookie attached. */
async function forward(request: Request, path: string[], method: string) {
  const token = await getAdminToken();
  if (!token) {
    return Response.json({ detail: "未登录" }, { status: 401 });
  }
  const target = new URL(`${getApiBaseUrl()}/api/admin/${path.join("/")}`);
  const incoming = new URL(request.url);
  incoming.searchParams.forEach((value, key) => target.searchParams.set(key, value));

  const init: RequestInit = {
    method,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  };
  if (method !== "GET") {
    const body = await request.text();
    if (body) {
      init.body = body;
    }
  }
  try {
    const response = await fetch(target.toString(), init);
    const text = await response.text();
    return new Response(text || "{}", {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    return Response.json(
      { detail: error instanceof Error ? error.message : "后台服务不可用" },
      { status: 502 },
    );
  }
}

type Params = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, { params }: Params) {
  return forward(request, (await params).path, "GET");
}

export async function POST(request: Request, { params }: Params) {
  return forward(request, (await params).path, "POST");
}

export async function PATCH(request: Request, { params }: Params) {
  return forward(request, (await params).path, "PATCH");
}

export async function PUT(request: Request, { params }: Params) {
  return forward(request, (await params).path, "PUT");
}

export async function DELETE(request: Request, { params }: Params) {
  return forward(request, (await params).path, "DELETE");
}
