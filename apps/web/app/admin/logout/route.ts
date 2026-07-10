import { NextResponse } from "next/server";
import { ADMIN_COOKIE } from "@/lib/admin-api";

export async function POST(request: Request) {
  const response = NextResponse.redirect(new URL("/admin/login", request.url));
  response.cookies.set(ADMIN_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
