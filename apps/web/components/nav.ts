export type NavItem = {
  id: string;
  label: string;
  group: "内容" | "接入" | "更多";
  href?: string;
};

export const navItems: NavItem[] = [
  { id: "latest", label: "精选", group: "内容", href: "/latest" },
  { id: "all", label: "全部 AI 动态", group: "内容", href: "/all" },
  { id: "daily", label: "AI 日报", group: "内容", href: "/daily" },
  { id: "topics", label: "主题", group: "内容", href: "/topics" },
  { id: "bookmarks", label: "收藏", group: "内容" },
  { id: "agent", label: "Agent 接入", group: "接入", href: "/agent" },
  { id: "about", label: "关于", group: "更多", href: "/about" },
  { id: "changelog", label: "更新日志", group: "更多", href: "/changelog" },
  { id: "feedback", label: "反馈", group: "更多", href: "/feedback" },
];

export function navGroupItems(group: NavItem["group"]) {
  return navItems.filter((item) => item.group === group);
}

export function navMarker(label: string) {
  return label.slice(0, 1);
}
