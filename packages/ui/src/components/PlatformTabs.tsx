import { useEffect, useState } from "react";

import { useAuth } from "../hooks/useAuth";
import { useProject } from "../hooks/useProject";
import { PLATFORM_API } from "../lib/api";
import { NotificationBell } from "./NotificationBell";
import { ProductTabs, type TabProduct } from "./ProductTabs";
import { UserMenu } from "./UserMenu";

export interface PlatformTabsProps {
  /** "home" в оболочке, иначе id продукта. */
  active: string;
  apiBase?: string;
  /** Страница всех уведомлений (в оболочке платформы). */
  notificationsHref?: string;
  /** @deprecated Счётчик колокольчик берёт сам из API платформы; значение игнорируется. */
  unread?: number;
}

/** Строка вкладок с данными платформы: GET /api/platform/products (только продукты с ролями). */
export function PlatformTabs({ active, apiBase = PLATFORM_API, notificationsHref = "/notifications" }: PlatformTabsProps) {
  const auth = useAuth();
  const { projectId } = useProject();
  const [products, setProducts] = useState<TabProduct[]>([]);

  useEffect(() => {
    if (!auth.ready) return;
    let cancelled = false;
    auth
      .json<TabProduct[]>(`${apiBase}/products`, { noRedirect: true })
      .then((items) => !cancelled && setProducts(Array.isArray(items) ? items : []))
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
          <NotificationBell apiBase={apiBase} href={notificationsHref} />
          {auth.user && <UserMenu name={auth.user.name} subtitle={auth.user.username} onLogout={auth.logout} />}
        </>
      }
    />
  );
}
