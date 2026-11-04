import { Empty, PageHead, useAuth } from "@platform/ui";
import { BellOff, Compass, ShieldOff } from "lucide-react";
import type { ReactNode } from "react";

export function NotificationsPage() {
  return (
    <>
      <PageHead breadcrumbs="Платформа" title="Уведомления" />
      <section className="card">
        <Empty icon={BellOff} title="Новых уведомлений нет" text="Здесь появятся назначенные заявки, завершённые прогоны и документы на утверждение." />
      </section>
    </>
  );
}

export function NotFoundPage() {
  return (
    <section className="card">
      <Empty icon={Compass} title="Страница не найдена" action={<a className="btn" href="/">На Главную</a>} />
    </section>
  );
}

export function AdminOnly({ children }: { children: ReactNode }) {
  const auth = useAuth();
  if (!auth.isPlatformAdmin)
    return (
      <section className="card">
        <Empty icon={ShieldOff} title="Нет доступа" text="Раздел доступен только администратору платформы." />
      </section>
    );
  return <>{children}</>;
}
