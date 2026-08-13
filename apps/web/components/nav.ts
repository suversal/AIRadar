import {
  Podcast,
  Bookmark,
  Bot,
  Hash,
  History,
  Info,
  MessageSquare,
  Newspaper,
  Search,
  Send,
  SquareX,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  id: string;
  label: string;
  group: "内容" | "接入" | "更多";
  href?: string;
  icon: LucideIcon;
};

export const navItems: NavItem[] = [
  { id: "latest", label: "精选", group: "内容", href: "/latest", icon: Sparkles },
  { id: "x", label: "推文", group: "内容", href: "/x", icon: SquareX },
  { id: "telegram", label: "电报", group: "内容", href: "/telegram", icon: Send },
  { id: "all", label: "全部", group: "内容", href: "/all", icon: Podcast },
  { id: "daily", label: "日报", group: "内容", href: "/daily", icon: Newspaper },
  { id: "topics", label: "主题", group: "内容", href: "/topics", icon: Hash },
  { id: "search", label: "搜索", group: "内容", href: "/search", icon: Search },
  { id: "bookmarks", label: "收藏", group: "内容", href: "/bookmarks", icon: Bookmark },
  { id: "agent", label: "Agent 接入", group: "接入", href: "/agent", icon: Bot },
  { id: "changelog", label: "更新日志", group: "更多", href: "/changelog", icon: History },
  { id: "feedback", label: "反馈", group: "更多", href: "/feedback", icon: MessageSquare },
  { id: "about", label: "关于", group: "更多", href: "/about", icon: Info },
];

export function navGroupItems(group: NavItem["group"]) {
  return navItems.filter((item) => item.group === group);
}
