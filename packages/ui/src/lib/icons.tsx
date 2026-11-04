import {
  Activity,
  BadgeCheck,
  Bell,
  Box,
  Building2,
  Calendar,
  ClipboardList,
  FileText,
  FolderKanban,
  Home,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Play,
  Radar,
  ScrollText,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  Users,
  Workflow,
  Wrench,
} from "lucide-react";

/** Иконки по именам lucide из манифестов продуктов. Неизвестное имя — нейтральная «коробка». */
const ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  "badge-check": BadgeCheck,
  bell: Bell,
  box: Box,
  "building-2": Building2,
  calendar: Calendar,
  "clipboard-list": ClipboardList,
  "file-text": FileText,
  "folder-kanban": FolderKanban,
  home: Home,
  "key-round": KeyRound,
  "layout-dashboard": LayoutDashboard,
  "list-checks": ListChecks,
  play: Play,
  radar: Radar,
  "scroll-text": ScrollText,
  server: Server,
  settings: Settings,
  shield: Shield,
  "shield-check": ShieldCheck,
  users: Users,
  workflow: Workflow,
  wrench: Wrench,
};

export function iconByName(name: string | undefined | null): LucideIcon {
  return (name && ICONS[name]) || Box;
}

export function registerIcons(extra: Record<string, LucideIcon>): void {
  Object.assign(ICONS, extra);
}
