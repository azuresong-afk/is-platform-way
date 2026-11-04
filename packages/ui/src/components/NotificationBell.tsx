import { Bell, CheckCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "../hooks/useAuth";
import { PLATFORM_API } from "../lib/api";
import { formatDateTime } from "../lib/format";

/** Уведомление пользователя (GET /api/platform/notifications). */
export interface NotificationItem {
  id: string;
  /** Продукт-источник: id продукта установки или "platform". */
  product: string;
  product_title: string;
  event_type: string;
  project_id: string | null;
  title: string;
  /** Относительный путь того же origin (контракт v1.1, п. 6.3). */
  link: string | null;
  created_at: string;
  read_at: string | null;
}

/** Событие окна: состояние уведомлений изменилось (страница списка ↔ колокольчик). */
export const NOTIFICATIONS_EVENT = "platform:notifications";

export function notificationsChanged(): void {
  window.dispatchEvent(new CustomEvent(NOTIFICATIONS_EVENT));
}

/** Только относительный путь того же origin — как проверяет платформа при приёме. */
export function safeLink(link: string | null | undefined): string | null {
  if (!link || !link.startsWith("/") || link.startsWith("//") || link.includes("\\")) return null;
  return link;
}

export interface NotificationBellProps {
  apiBase?: string;
  /** Страница со всеми уведомлениями (в оболочке платформы). */
  href?: string;
  /** Период фонового опроса счётчика, мс. */
  pollMs?: number;
  /** Сколько последних показывать в выпадающей панели. */
  limit?: number;
}

/**
 * Колокольчик в строке вкладок: счётчик непрочитанных и последние уведомления.
 * Работает в любом продукте: данные — из API платформы с тем же токеном.
 */
export function NotificationBell({ apiBase = PLATFORM_API, href = "/notifications", pollMs = 60_000, limit = 8 }: NotificationBellProps) {
  const auth = useAuth();
  const { json } = auth;
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const base = `${apiBase}/notifications`;

  const loadCount = useCallback(() => {
    json<{ unread: number }>(`${base}/unread-count`, { noRedirect: true })
      .then((r) => setUnread(typeof r?.unread === "number" ? r.unread : 0))
      .catch(() => {});
  }, [json, base]);

  const loadList = useCallback(() => {
    setFailed(false);
    json<NotificationItem[]>(`${base}?limit=${limit}`, { noRedirect: true })
      .then((r) => setItems(Array.isArray(r) ? r : []))
      .catch(() => {
        setItems([]);
        setFailed(true);
      });
  }, [json, base, limit]);

  useEffect(() => {
    if (!auth.ready || !auth.token) return;
    loadCount();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") loadCount();
    }, pollMs);
    const onChange = () => {
      loadCount();
      if (open) loadList();
    };
    window.addEventListener("focus", loadCount);
    window.addEventListener(NOTIFICATIONS_EVENT, onChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", loadCount);
      window.removeEventListener(NOTIFICATIONS_EVENT, onChange);
    };
  }, [auth.ready, auth.token, loadCount, loadList, open, pollMs]);

  useEffect(() => {
    if (!open) return;
    loadList();
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open, loadList]);

  const markRead = (n: NotificationItem) => {
    if (n.read_at) return;
    setItems((list) => list?.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)) ?? null);
    setUnread((u) => Math.max(0, u - 1));
    // keepalive: запрос доживёт до перехода по ссылке уведомления
    auth.fetch(`${base}/${n.id}/read`, { method: "POST", keepalive: true, noRedirect: true }).then(notificationsChanged, () => {});
  };

  const markAll = () => {
    auth
      .fetch(`${base}/read-all`, { method: "POST", noRedirect: true })
      .then(() => {
        setUnread(0);
        notificationsChanged();
      })
      .catch(() => {});
  };

  const label = unread ? `Уведомления: ${unread} непрочитанных` : "Уведомления";

  return (
    <div ref={ref} className="notif-bell">
      <button
        type="button"
        className="icon-btn"
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} aria-hidden="true" />
        {unread > 0 && (
          <span className="notif-count" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="popover notif-popover" role="dialog" aria-label="Уведомления">
          <div className="notif-head">
            <span className="notif-head-title">Уведомления</span>
            {unread > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={markAll}>
                <CheckCheck size={15} aria-hidden="true" />
                Прочитать все
              </button>
            )}
          </div>
          {items === null ? (
            <div className="palette-note">Загрузка…</div>
          ) : failed ? (
            <div className="palette-note">Не удалось загрузить уведомления</div>
          ) : items.length === 0 ? (
            <div className="palette-note">Новых уведомлений нет</div>
          ) : (
            <ul className="notif-list">
              {items.map((n) => (
                <li key={n.id}>
                  <NotificationRow item={n} onOpen={() => markRead(n)} />
                </li>
              ))}
            </ul>
          )}
          <div className="menu-sep" />
          <a className="menu-item notif-all" href={href}>
            Все уведомления
          </a>
        </div>
      )}
    </div>
  );
}

/** Строка уведомления: ссылка (если есть) или кнопка; непрочитанное — с маркером. */
export function NotificationRow({ item, onOpen }: { item: NotificationItem; onOpen: () => void }) {
  const link = safeLink(item.link);
  const body = (
    <>
      <span className={`notif-mark${item.read_at ? "" : " unread"}`} aria-hidden="true" />
      <span className="notif-body">
        <span className="notif-title">{item.title}</span>
        <span className="notif-meta">
          {item.product_title} · {formatDateTime(item.created_at)}
          {!item.read_at && <span className="sr-only"> · не прочитано</span>}
        </span>
      </span>
    </>
  );
  const cls = `notif-item${item.read_at ? "" : " unread"}`;
  return link ? (
    <a className={cls} href={link} onClick={onOpen}>
      {body}
    </a>
  ) : (
    <button type="button" className={cls} onClick={onOpen}>
      {body}
    </button>
  );
}
