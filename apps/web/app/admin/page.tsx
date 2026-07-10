import { adminFetch } from "@/lib/admin-api";

export const metadata = {
  title: "管理后台 · AI·RADAR",
};

export default async function AdminHomePage() {
  const ping = await adminFetch("/api/admin/ping");
  const authorized = ping.ok;

  return (
    <main className="min-h-screen bg-canvas px-8 py-10 text-ink">
      <div className="mx-auto max-w-5xl">
        <header className="flex items-center justify-between">
          <div aria-label="AI·RADAR 管理后台" className="text-xl font-semibold tracking-[0.15em]">
            AI<span className="text-signal">·RADAR</span>
            <span className="ml-3 text-sm font-normal text-ink-mid">管理后台</span>
          </div>
          <form action="/admin/logout" method="post">
            <button className="text-sm text-ink-mid hover:text-signal" type="submit">
              退出登录
            </button>
          </form>
        </header>

        <div className="mt-8 rounded-md border border-line bg-panel p-6">
          {authorized ? (
            <p className="text-sm text-ink-mid">
              认证正常。仪表盘、信源管理与内容修正模块即将在此展示。
            </p>
          ) : (
            <p className="text-sm text-red-300">
              API 认证失败（{ping.status}）——请确认后端 ADMIN_TOKEN 配置并重新登录。
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
