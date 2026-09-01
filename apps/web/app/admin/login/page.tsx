import { redirect } from "next/navigation";
import { ADMIN_COOKIE, verifyAdminToken } from "@/lib/admin-api";
import { cookies } from "next/headers";

export const metadata = {
  title: "管理员登录 · AI·RADAR",
};

function safeNextPath(value: string) {
  if (value === "/admin" || value.startsWith("/admin/") || value === "/newsletter/subscribe") {
    return value;
  }
  return "/admin";
}

async function login(formData: FormData) {
  "use server";

  const token = String(formData.get("token") ?? "").trim();
  const next = safeNextPath(String(formData.get("next") ?? "/admin"));
  if (!token) {
    redirect(`/admin/login?error=empty&next=${encodeURIComponent(next)}`);
  }
  const valid = await verifyAdminToken(token);
  if (!valid) {
    redirect(`/admin/login?error=invalid&next=${encodeURIComponent(next)}`);
  }
  const store = await cookies();
  store.set(ADMIN_COOKIE, token, {
    httpOnly: true,
    // 线上全程走 HTTPS（CF → nginx → web），加 secure 让这个 cookie 永远不会
    // 被明文发出去。本地开发是 http://localhost，加了就登不进去，所以按环境区分。
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect(next);
}

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const params = await searchParams;
  const errorMessage =
    params.error === "invalid"
      ? "Token 无效，请检查后重试"
      : params.error === "empty"
        ? "请输入管理员 Token"
        : null;

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-5 text-ink">
      <div className="w-full max-w-sm">
        <div aria-label="AI·RADAR" className="text-center text-2xl font-semibold tracking-[0.2em]">
          AI<span className="text-signal">·RADAR</span>
        </div>
        <form
          action={login}
          className="mt-8 rounded-md border border-line bg-panel p-6"
        >
          <h1 className="text-lg font-semibold">管理员登录</h1>
          <p className="mt-2 text-sm text-ink-mid">
            输入部署时配置的 ADMIN_TOKEN
          </p>
          <input name="next" type="hidden" value={safeNextPath(params.next ?? "/admin")} />
          <input
            autoFocus
            className="mt-5 w-full rounded-md border border-line bg-canvas px-4 py-3 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
            name="token"
            placeholder="管理员 Token"
            type="password"
          />
          {errorMessage ? (
            <p className="mt-3 text-sm text-danger">{errorMessage}</p>
          ) : null}
          <button
            className="mt-5 w-full rounded-md border border-signal bg-signal px-4 py-3 text-sm font-semibold text-canvas hover:border-signal-bright hover:bg-signal-bright"
            type="submit"
          >
            登录
          </button>
        </form>
        <p className="mt-4 text-center text-xs text-ink-dim">
          <a className="hover:text-signal" href="/latest">
            返回站点
          </a>
        </p>
      </div>
    </main>
  );
}
