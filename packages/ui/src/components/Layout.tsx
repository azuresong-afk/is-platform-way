import { LogOut, type LucideIcon, Menu } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { initials } from "../lib/format";
import { ThemeToggle } from "./ThemeToggle";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Точное совпадение пути для подсветки (для «Сводки» на корне). */
  end?: boolean;
}

export interface LayoutUser {
  name: string;
  /** Подписи ролей через запятую. */
  roles: string[];
}

export interface LayoutProps {
  brand: { title: string; subtitle?: string; icon: LucideIcon; href?: string };
  nav: NavItem[];
  /** Служебные разделы — отдельная группа «Администрирование». */
  adminNav?: NavItem[];
  user?: LayoutUser | null;
  onLogout?: () => void;
  /** Содержимое верхней полосы: выбор проекта, поиск, индикаторы задач. */
  topbar?: ReactNode;
  /** Приглушённая подпись-напоминание о рамках работ справа в верхней полосе. */
  topbarNote?: ReactNode;
  /**
   * Режим платформы: над каркасом рисуется строка вкладок продуктов.
   * Продукт передаёт platform={import.meta.env.VITE_PLATFORM === "1"} — пакет собирается
   * заранее и сам переменные сборки продукта не видит.
   */
  platform?: boolean;
  /** Строка вкладок (обычно <PlatformTabs product="…" />). */
  tabs?: ReactNode;
  children: ReactNode;
}

function NavList({ items, onNavigate }: { items: NavItem[]; onNavigate: () => void }) {
  return (
    <>
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className="nav-link" onClick={onNavigate}>
          <Icon size={18} aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </>
  );
}

/** Каркас страницы: боковая панель 248 px + верхняя полоса + контент (+ строка вкладок продуктов). */
export function Layout({
  brand,
  nav,
  adminNav,
  user,
  onLogout,
  topbar,
  topbarNote,
  platform = false,
  tabs,
  children,
}: LayoutProps) {
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setNavOpen(false), [location.pathname]);
  const BrandIcon = brand.icon;
  const close = () => setNavOpen(false);

  const shell = (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Меню">
        <NavLink to={brand.href ?? "/"} className="brand" onClick={close}>
          <span className="brand-logo" aria-hidden="true">
            <BrandIcon size={18} />
          </span>
          <span>
            <div className="brand-title">{brand.title}</div>
            {brand.subtitle && <div className="brand-subtitle">{brand.subtitle}</div>}
          </span>
        </NavLink>
        <nav className="nav">
          <NavList items={nav} onNavigate={close} />
          {adminNav && adminNav.length > 0 && (
            <>
              <div className="nav-group-title">Администрирование</div>
              <NavList items={adminNav} onNavigate={close} />
            </>
          )}
        </nav>
        <div className="sidebar-bottom">
          {user && (
            <div className="user-card">
              <span className="avatar" aria-hidden="true">
                {initials(user.name)}
              </span>
              <div className="user-card-info">
                <div className="user-card-name">{user.name}</div>
                <div className="user-card-roles">{user.roles.join(", ") || "Без ролей"}</div>
              </div>
              {onLogout && (
                <button type="button" className="icon-btn" onClick={onLogout} aria-label="Выйти" title="Выйти">
                  <LogOut size={18} aria-hidden="true" />
                </button>
              )}
            </div>
          )}
          <ThemeToggle />
        </div>
      </aside>
      <div className="sidebar-backdrop" onClick={close} aria-hidden="true" />
      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="icon-btn burger"
            onClick={() => setNavOpen((v) => !v)}
            aria-label="Открыть меню"
            aria-expanded={navOpen}
          >
            <Menu size={18} aria-hidden="true" />
          </button>
          {topbar}
          {topbarNote && <span className="topbar-note">{topbarNote}</span>}
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );

  if (!platform) return shell;
  return (
    <div className="platform-frame">
      {tabs}
      {shell}
    </div>
  );
}

export interface PageHeadProps {
  title: ReactNode;
  breadcrumbs?: ReactNode;
  actions?: ReactNode;
}

/** Заголовок страницы: хлебные крошки, h1 26 px, действия справа. */
export function PageHead({ title, breadcrumbs, actions }: PageHeadProps) {
  return (
    <div className="page-head">
      <div>
        {breadcrumbs && <div className="breadcrumbs">{breadcrumbs}</div>}
        <h1>{title}</h1>
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
