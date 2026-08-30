"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export type AccessTab = {
  id: string;
  name: string;
  method: string;
  hint: string;
  badge?: string;
  panel: ReactNode;
};

/**
 * 四条接入路径的 tab 切换。
 *
 * 关键取舍：**所有面板都渲染进 DOM**，非当前项用 hidden 收起，而不是只渲染
 * 选中的那一个。这页的读者有一半是 Agent——llms.txt 把它列成了入口，抓 HTML
 * 只拿到四分之一内容是实打实的损失。hidden 的内容对爬虫和 Ctrl+F 都还在，
 * 对人则是一次只看一条路。
 *
 * 同理，tab 状态同步到 URL hash：/agent#mcp 能直接把人带到那一条，文档和
 * 反馈里可以引用具体路径。
 */
export function AccessTabs({ tabs }: { tabs: AccessTab[] }) {
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  const baseId = useId();
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  // 首屏用 tabs[0] 渲染（服务端与客户端一致，不会 hydration 不匹配），
  // 挂载后再按 hash 纠正。带 hash 进来的人会看到一次切换，比让服务端去
  // 猜 hash（它根本拿不到）要诚实。
  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    if (fromHash && tabs.some((tab) => tab.id === fromHash)) {
      setActive(fromHash);
    }
  }, [tabs]);

  function select(id: string, options: { focus?: boolean } = {}) {
    setActive(id);
    // replaceState 而不是改 location.hash：后者会把页面滚到锚点上，
    // 从下方内容里点 tab 会莫名其妙跳一下。
    window.history.replaceState(null, "", `#${id}`);
    if (options.focus) {
      tabRefs.current[id]?.focus();
    }
  }

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = tabs[nextIndex];
    select(next.id, { focus: true });
  }

  return (
    <div>
      {/* 没有 JS 时 tab 按钮点了没反应，服务端渲染又只让第一个面板可见——
          读者会以为另外三条路不存在。这几行把面板全部展开、把失效的 tab 条
          收起来，退化成一页平铺的长文档，信息一条不少。 */}
      <noscript>
        <style
          dangerouslySetInnerHTML={{
            __html: `
              [data-access-tablist] { display: none; }
              [data-access-panel][hidden] { display: block !important; }
              [data-access-panel] { margin-top: 0.75rem; }
            `,
          }}
        />
      </noscript>

      <div
        role="tablist"
        aria-label="接入路径"
        data-access-tablist
        className="grid grid-cols-2 gap-2 sm:grid-cols-4"
      >
        {tabs.map((tab, index) => {
          const on = tab.id === active;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                tabRefs.current[tab.id] = node;
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={on}
              aria-controls={`${baseId}-panel-${tab.id}`}
              // 未选中的 tab 退出 tab 键序列，方向键在组内移动——这是 tablist
              // 的标准键盘模型，不这么做键盘用户要按四次才能越过这一排。
              tabIndex={on ? 0 : -1}
              onClick={() => select(tab.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={[
                "flex min-h-[5.5rem] flex-col rounded-md border px-3 py-2.5 text-left transition-colors",
                on
                  ? "border-signal/55 bg-signal/12 text-ink shadow-[inset_0_-2px_0_var(--color-signal)]"
                  : "border-line bg-panel text-ink-mid hover:border-signal/40 hover:text-ink",
              ].join(" ")}
            >
              <span className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden
                  className={[
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    on ? "bg-signal" : "bg-line-strong",
                  ].join(" ")}
                />
                  <span className="text-sm font-semibold">{tab.name}</span>
                </span>
                {tab.badge ? (
                  <span className="shrink-0 rounded border border-signal/35 px-1.5 py-0.5 text-[10px] text-signal">
                    {tab.badge}
                  </span>
                ) : null}
              </span>
              <span className="mt-1.5 text-xs font-semibold text-signal">{tab.method}</span>
              <span className={on ? "mt-1 text-xs leading-4 text-ink-mid" : "mt-1 text-xs leading-4 text-ink-dim"}>
                {tab.hint}
              </span>
            </button>
          );
        })}
      </div>

      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`${baseId}-panel-${tab.id}`}
          aria-labelledby={`${baseId}-tab-${tab.id}`}
          data-access-panel
          hidden={tab.id !== active}
          className="mt-2 space-y-4 rounded-md border border-line bg-panel p-4"
        >
          {tab.panel}
        </div>
      ))}
    </div>
  );
}
