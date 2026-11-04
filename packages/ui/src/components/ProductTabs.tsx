import { Home } from "lucide-react";
import type { ReactNode } from "react";

import { withProject } from "../hooks/useProject";
import { iconByName } from "../lib/icons";

export interface TabProduct {
  id: string;
  title: string;
  icon?: string;
  base_path: string;
}

export interface ProductTabsProps {
  products: TabProduct[];
  /** "home" — Главная оболочки, иначе id продукта. */
  active: string;
  projectId?: string | null;
  homeHref?: string;
  /** Справа: колокольчик уведомлений и меню пользователя. */
  right?: ReactNode;
}

/**
 * Строка вкладок продуктов над всем интерфейсом (40 px, фон --sidebar).
 * Переход между продуктами — обычная ссылка: это разные SPA на одном origin.
 */
export function ProductTabs({ products, active, projectId = null, homeHref = "/", right }: ProductTabsProps) {
  return (
    <nav className="product-tabs" aria-label="Продукты">
      <div className="product-tabs-list">
        <a
          className={`tab${active === "home" ? " active" : ""}`}
          href={withProject(homeHref, projectId)}
          aria-current={active === "home" ? "page" : undefined}
        >
          <Home size={15} aria-hidden="true" />
          Главная
        </a>
        {products.map((p) => {
          const Icon = iconByName(p.icon);
          const isActive = active === p.id;
          return (
            <a
              key={p.id}
              className={`tab${isActive ? " active" : ""}`}
              href={withProject(p.base_path, projectId)}
              aria-current={isActive ? "page" : undefined}
              data-product={p.id}
            >
              <Icon size={15} aria-hidden="true" />
              {p.title}
            </a>
          );
        })}
      </div>
      {right && <div className="product-tabs-right">{right}</div>}
    </nav>
  );
}
