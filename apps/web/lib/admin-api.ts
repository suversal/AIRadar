import { cookies } from "next/headers";
import { getApiBaseUrl } from "./api";

export const ADMIN_COOKIE = "admin_token";

export async function getAdminToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(ADMIN_COOKIE)?.value ?? null;
}

/** Server-side fetch against the API with the admin token attached. */
export async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAdminToken();
  return fetch(`${getApiBaseUrl()}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
}

export async function verifyAdminToken(token: string): Promise<boolean> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/admin/ping`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
    return response.ok;
  } catch {
    return false;
  }
}
