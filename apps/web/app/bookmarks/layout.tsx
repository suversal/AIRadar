import type { ReactNode } from "react";

// 收藏页是 "use client" 组件，metadata 只能由这层 layout 提供
export const metadata = {
  title: "收藏",
  description: "收藏过的 AI 动态都在这里，保存在本设备的浏览器中。",
};

export default function BookmarksLayout({ children }: { children: ReactNode }) {
  return children;
}
