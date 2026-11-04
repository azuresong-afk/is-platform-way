import { Bell } from "lucide-react";
import { useEffect, useState } from "react";

import { useAuth } from "../hooks/useAuth";
import { useProject } from "../hooks/useProject";
import { PLATFORM_API } from "../lib/api";
import { ProductTabs, type TabProduct } from "./ProductTabs";
import { UserMenu } from "./UserMenu";

export interface PlatformTabsProps {
  /** "home" в оболочке, иначе id продукта. */
  active: string;
  apiBase?: string;
  notificationsHref?: string;
  /** Есть непрочитанные уведомления (рисует точку на колокольчике). */
  unread?: number;
}

/** Строка вкладок с данными платформы: GET /api/platform/products (только продукты с ролями). */
export function PlatformTabs({ active, apiBase = PLATFORM_API, notificationsHref = "/notifications", unread = 0 }: PlatformTabsProps) {
  const auth = useAuth();
  const { projectId } = useProject();
  const [products, setProducts] = useState<TabProduct[]>([]);

  useEffect(() => {
    if (!auth.ready) return;
    let cancelled = false;
    auth
      .json<TabProduct[]>(`${apiBase}/products`, { noRedirect: true })
      .then((items) => !cancelled && setProducts(items))
      .catch(() => !cancelled && setProducts([]));
    return () => {
      cancelled = true;
    };
    // Состав вкладок меняется вместе с токеном (роли).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.ready, auth.token, apiBase]);

  return (
    <ProductTabs
      products={products}
      active={active}
      projectId={projectId}
      right={
        <>
          <a className="icon-btn" href={notificationsHref} aria-label={unread ? `Уведомления: ${unread}` : "Уведомления"}>
            <Bell size={18} aria-hidden="true" />
            {unread > 0 && <span className="dot" aria-hidden="true" />}
          </a>
          {auth.user && <UserMenu name={auth.user.name} subtitle={auth.user.username} onLogout={auth.logout} />}
        </>
      }
    />
  );
}
