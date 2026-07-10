import { redirect } from "next/navigation";
import { ADMIN_COOKIE, verifyAdminToken } from "@/lib/admin-api";
import { cookies } from "next/headers";

export const metadata = {
  title: "管理员登录 · AI·RADAR",
};

async function login(formData: FormData) {
  "use server";

  const token = String(formData.get("token") ?? "").trim();
  const next = String(formData.get("next") ?? "/admin");
  if (!token) {
    redirect("/admin/login?error=empty");
  }
  const valid = await verifyAdminToken(token);
  if (!valid) {
    redirect("/admin/login?error=invalid");
  }
  const store = await cookies();
  store.set(ADMIN_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect(next.startsWith("/admin") ? next : "/admin");
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
          <input name="next" type="hidden" value={params.next ?? "/admin"} />
          <input
            autoFocus
            className="mt-5 w-full rounded-md border border-line bg-canvas px-4 py-3 text-sm text-ink outline-none placeholder:text-ink-dim focus:border-signal/60"
            name="token"
            placeholder="管理员 Token"
            type="password"
          />
          {errorMessage ? (
            <p className="mt-3 text-sm text-red-300">{errorMessage}</p>
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
