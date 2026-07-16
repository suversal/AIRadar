import { getApiBaseUrl } from "@/lib/api";
import { getAdminToken } from "@/lib/admin-api";

export async function POST(request: Request) {
  const token = await getAdminToken();
  if (!token) return Response.json({ detail: "未登录" }, { status: 401 });
  try {
    const form = await request.formData();
    const response = await fetch(`${getApiBaseUrl()}/api/admin/uploads/images`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      cache: "no-store",
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json(
      { detail: { code: "image_host_failed", message: "图片上传服务不可用" } },
      { status: 502 },
    );
  }
}
