import {
  apiFetch,
  Empty,
  ErrorAlert,
  Loading,
  type NotificationItem,
  NotificationRow,
  notificationsChanged,
  NOTIFICATIONS_EVENT,
  PageHead,
  Pager,
} from "@platform/ui";
import { BellOff, CheckCheck, Mail, MailOpen } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { API, errorText, send } from "../api";
import { useShell } from "../components/ShellLayout";

const LIMIT = 50;

interface Data {
  items: NotificationItem[];
  total: number;
  unread: number;
}

/** Центр уведомлений: всё, что продукты адресовали пользователю через поле notify событий. */
export function NotificationsPage() {
  const shell = useShell();
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [product, setProduct] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    setError(null);
    const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
    if (onlyUnread) params.set("unread", "true");
    if (product) params.set("product", product);
    apiFetch(`${API}/notifications?${params}`, { platform: true })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Ошибка ${r.status}`);
        setData({
          items: (await r.json()) as NotificationItem[],
          total: Number(r.headers.get("X-Total-Count") ?? 0),
          unread: Number(r.headers.get("X-Unread-Count") ?? 0),
        });
      })
      .catch(setError);
  }, [onlyUnread, product, offset]);
  useEffect(load, [load]);

  // Колокольчик отметил прочитанным — обновляем список.
  useEffect(() => {
    window.addEventListener(NOTIFICATIONS_EVENT, load);
    return () => window.removeEventListener(NOTIFICATIONS_EVENT, load);
  }, [load]);

  const toggle = (n: NotificationItem, read: boolean) => {
    if (Boolean(n.read_at) === read) return;
    send("POST", `/notifications/${n.id}/${read ? "read" : "unread"}`)
      .then(notificationsChanged)
      .catch(setError);
  };

  const readAll = () => {
    send("POST", "/notifications/read-all", product ? { product } : {})
      .then(notificationsChanged)
      .catch(setError);
  };

  const filtered = onlyUnread || product;

  return (
    <>
      <PageHead
        breadcrumbs="Платформа"
        title="Уведомления"
        actions={
          data && data.unread > 0 ? (
            <button type="button" className="btn" onClick={readAll}>
              <CheckCheck size={15} aria-hidden="true" />
              {product ? "Прочитать все по продукту" : "Прочитать все"}
            </button>
          ) : undefined
        }
      />
      <section className="card">
        <div className="card-head">
          <div style={{ display: "flex", alignItems: "center", gap: "var(--s2)", flexWrap: "wrap" }}>
            <div className="seg" role="group" aria-label="Какие уведомления показать">
              {(
                [
                  [false, "Все"],
                  [true, "Непрочитанные"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={onlyUnread === v}
                  onClick={() => {
                    setOnlyUnread(v);
                    setOffset(0);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <select
              className="select"
              style={{ width: "auto" }}
              aria-label="Продукт"
              value={product}
              onChange={(e) => {
                setProduct(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Все продукты</option>
              <option value="platform">Платформа</option>
              {shell.products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          </div>
          {data && (
            <span className="count" title="Непрочитанных">
              {data.unread}
            </span>
          )}
        </div>
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : !data ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <Empty
            icon={BellOff}
            title={filtered ? "Ничего не найдено" : "Уведомлений нет"}
            text={
              filtered
                ? "Попробуйте снять фильтр."
                : "Здесь появятся назначенные заявки, завершённые прогоны и документы на утверждение."
            }
          />
        ) : (
          <>
            <ul className="notif-page-list">
              {data.items.map((n) => (
                <li key={n.id}>
                  <NotificationRow item={n} onOpen={() => toggle(n, true)} />
                  <button
                    type="button"
                    className="icon-btn"
                    style={{ marginRight: "var(--s1)" }}
                    onClick={() => toggle(n, !n.read_at)}
                    aria-label={n.read_at ? "Отметить непрочитанным" : "Отметить прочитанным"}
                    title={n.read_at ? "Отметить непрочитанным" : "Отметить прочитанным"}
                  >
                    {n.read_at ? <Mail size={18} aria-hidden="true" /> : <MailOpen size={18} aria-hidden="true" />}
                  </button>
                </li>
              ))}
            </ul>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </section>
    </>
  );
}
