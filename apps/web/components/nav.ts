import {
  Podcast,
  Bookmark,
  Bot,
  Hash,
  History,
  Info,
  MessageSquare,
  Newspaper,
  ShieldCheck,
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
  { id: "all", label: "全部 AI 动态", group: "内容", href: "/all", icon: Podcast },
  { id: "daily", label: "AI 日报", group: "内容", href: "/daily", icon: Newspaper },
  { id: "topics", label: "主题", group: "内容", href: "/topics", icon: Hash },
  { id: "bookmarks", label: "收藏", group: "内容", href: "/bookmarks", icon: Bookmark },
  { id: "agent", label: "Agent 接入", group: "接入", href: "/agent", icon: Bot },
  { id: "about", label: "关于", group: "更多", href: "/about", icon: Info },
  { id: "changelog", label: "更新日志", group: "更多", href: "/changelog", icon: History },
  { id: "feedback", label: "反馈", group: "更多", href: "/feedback", icon: MessageSquare },
  { id: "admin", label: "管理后台", group: "更多", href: "/admin", icon: ShieldCheck },
];

export function navGroupItems(group: NavItem["group"]) {
  return navItems.filter((item) => item.group === group);
}
