import { Drawer, Empty, ErrorAlert, formatDateTime, Loading, PageHead, Pager } from "@platform/ui";
import { Radio, RotateCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { type AdminProduct, API, type BusEvent, type BusEventDetail, errorText, get, paged, send, type Subscription } from "../../api";
import { DELIVERY_STATUS } from "../../labels";

const LIMIT = 50;

function StatusPill({ status }: { status: string }) {
  const s = DELIVERY_STATUS[status] ?? DELIVERY_STATUS.none;
  return <span className={`pill ${s.pill}`}>{s.label}</span>;
}

type Titles = { products: AdminProduct[]; title: (id: string) => string };

/** Названия продуктов для администратора — из реестра, а не из ролей текущего пользователя. */
function useTitles(): Titles {
  const [products, setProducts] = useState<AdminProduct[]>([]);
  useEffect(() => {
    get<AdminProduct[]>("/admin/products").then((xs) => setProducts(Array.isArray(xs) ? xs : []), () => setProducts([]));
  }, []);
  const title = (id: string) => (id === "platform" ? "Платформа" : (products.find((p) => p.id === id)?.title ?? id));
  return { products, title };
}

export function EventsPage() {
  const [tab, setTab] = useState<"events" | "subscriptions">("events");
  const titles = useTitles();
  return (
    <>
      <PageHead breadcrumbs="Администрирование" title="События" />
      <div className="seg" role="group" aria-label="Раздел" style={{ marginBottom: 16 }}>
        <button type="button" aria-pressed={tab === "events"} onClick={() => setTab("events")}>
          Журнал событий
        </button>
        <button type="button" aria-pressed={tab === "subscriptions"} onClick={() => setTab("subscriptions")}>
          Подписки продуктов
        </button>
      </div>
      {tab === "events" ? <EventsList titles={titles} /> : <Subscriptions titles={titles} />}
    </>
  );
}

function EventsList({ titles }: { titles: Titles }) {
  const [source, setSource] = useState("");
  const [type, setType] = useState("");
  const [delivery, setDelivery] = useState<"" | "problems">("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: BusEvent[]; total: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
    if (source) params.set("source", source);
    if (type.trim()) params.set("type", type.trim());
    if (delivery) params.set("delivery", delivery);
    paged<BusEvent>(`${API}/admin/events?${params}`).then(setData, setError);
  }, [source, type, delivery, offset]);
  useEffect(load, [load]);

  const { title } = titles;

  return (
    <section className="card">
      <div className="card-head" style={{ flexWrap: "wrap", gap: 8, justifyContent: "flex-start" }}>
        <div className="seg" role="group" aria-label="Доставка">
          {(
            [
              ["", "Все"],
              ["problems", "С ошибками доставки"],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              type="button"
              aria-pressed={delivery === v}
              onClick={() => {
                setDelivery(v);
                setOffset(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <select
          className="select"
          aria-label="Источник"
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setOffset(0);
          }}
          style={{ width: "auto", minWidth: 180 }}
        >
          <option value="">Все источники</option>
          <option value="platform">Платформа</option>
          {titles.products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
        <input
          className="input"
          aria-label="Тип события"
          placeholder="Тип, например scanner.run"
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            setOffset(0);
          }}
          style={{ maxWidth: 260 }}
        />
        {data && (
          <span className="count" style={{ marginLeft: "auto" }}>
            {data.total}
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
        <Empty icon={Radio} title="Событий нет" text="Продукты присылают события после действий пользователей: завершение прогона, новая заявка и т. п." />
      ) : (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Получено</th>
                  <th>Источник</th>
                  <th>Тип</th>
                  <th>Объект</th>
                  <th>Доставка</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id} className={`clickable${e.id === openId ? " selected" : ""}`} onClick={() => setOpenId(e.id)}>
                    <td>{formatDateTime(e.received_at)}</td>
                    <td>{title(e.source)}</td>
                    <td className="mono">{e.type}</td>
                    <td className="mono">{e.subject || <span className="muted">—</span>}</td>
                    <td>
                      <StatusPill status={e.delivery} />
                      {e.deliveries_total > 1 && <small> · подписчиков: {e.deliveries_total}</small>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
        </>
      )}
      {openId && <EventDrawer key={openId} id={openId} title={title} onClose={() => setOpenId(null)} onChanged={load} />}
    </section>
  );
}

function EventDrawer({ id, title, onClose, onChanged }: { id: string; title: (id: string) => string; onClose: () => void; onChanged: () => void }) {
  const [event, setEvent] = useState<BusEventDetail | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get<BusEventDetail>(`/admin/events/${id}`).then(setEvent, (e) => setMessage({ kind: "danger", text: errorText(e) }));
  }, [id]);

  const redeliver = async (subscriptionId?: string) => {
    setBusy(true);
    setMessage(null);
    try {
      const fresh = await send<BusEventDetail>("POST", `/admin/events/${id}/redeliver`, subscriptionId ? { subscription_id: subscriptionId } : {});
      setEvent(fresh);
      setMessage({ kind: "ok", text: "Поставлено в очередь на отправку." });
      onChanged();
    } catch (e) {
      setMessage({ kind: "danger", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open title={event?.type ?? "Событие"} onClose={onClose}>
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      {!event ? (
        !message && <Loading />
      ) : (
        <>
          <dl className="stat-list">
            <div>
              <dt>Источник</dt>
              <dd>{title(event.source)}</dd>
            </div>
            <div>
              <dt>Время события</dt>
              <dd>{formatDateTime(event.time)}</dd>
            </div>
            <div>
              <dt>Получено</dt>
              <dd>{formatDateTime(event.received_at)}</dd>
            </div>
            <div>
              <dt>Объект</dt>
              <dd className="mono">{event.subject || "—"}</dd>
            </div>
            <div>
              <dt>id</dt>
              <dd className="mono">{event.id}</dd>
            </div>
          </dl>

          <h3>Доставка</h3>
          {event.deliveries.length === 0 ? (
            <p className="muted">На этот тип событий никто не подписан.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Получатель</th>
                    <th>Статус</th>
                    <th>Попыток</th>
                    <th>Следующая / доставлено</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {event.deliveries.map((d) => (
                    <tr key={d.id}>
                      <td>
                        {title(d.product_id)}
                        {d.last_error && (
                          <div>
                            <small className="mono">{d.last_error}</small>
                          </div>
                        )}
                      </td>
                      <td>
                        <StatusPill status={d.status} />
                      </td>
                      <td>{d.attempts}</td>
                      <td>{d.status === "ok" ? formatDateTime(d.delivered_at) : d.next_attempt_at ? formatDateTime(d.next_attempt_at) : "—"}</td>
                      <td>
                        {d.status !== "pending" && (
                          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => redeliver(d.subscription_id)}>
                            <RotateCw size={14} aria-hidden="true" />
                            Отправить ещё раз
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {event.notify && (
            <>
              <h3>Уведомление</h3>
              <p>
                {event.notify.title} <small>· адресатов: {event.notify.users.length}</small>
              </p>
            </>
          )}

          <h3>Данные</h3>
          <pre className="card card-pad" style={{ overflow: "auto", maxHeight: 360, fontSize: 12, margin: 0 }}>
            {JSON.stringify(event.data, null, 2)}
          </pre>
        </>
      )}
    </Drawer>
  );
}

function Subscriptions({ titles }: { titles: Titles }) {
  const [items, setItems] = useState<Subscription[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    get<Subscription[]>("/admin/subscriptions").then(setItems, setError);
  }, []);
  useEffect(load, [load]);

  const toggle = async (s: Subscription) => {
    setBusy(s.id);
    try {
      const fresh = await send<Subscription>("PATCH", `/admin/subscriptions/${s.id}`, { is_active: !s.is_active });
      setItems((xs) => (xs ?? []).map((x) => (x.id === s.id ? fresh : x)));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="alert-info">
        <div className="alert-body">
          Подписки продукт объявляет в своём манифесте (события и адрес приёма). Отключённая подписка не получает новых событий; включение
          не досылает пропущенные.
        </div>
      </div>
      <section className="card">
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : !items ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty icon={Radio} title="Подписок нет" text="Ни один подключённый продукт не объявил в манифесте приём событий." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Продукт</th>
                  <th>Типы событий</th>
                  <th>Адрес приёма</th>
                  <th>В очереди</th>
                  <th>Не доставлено</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((s) => (
                  <tr key={s.id}>
                    <td>{titles.title(s.product_id)}</td>
                    <td>
                      {s.types.map((t) => (
                        <span key={t} className="tag mono">
                          {t}
                        </span>
                      ))}
                    </td>
                    <td className="mono">{s.webhook_path || "—"}</td>
                    <td>{s.pending}</td>
                    <td>{s.dead ? <span className="pill pill-danger">{s.dead}</span> : 0}</td>
                    <td>
                      <span className={`pill ${s.is_active ? "pill-ok" : "pill-muted"}`}>{s.is_active ? "Включена" : "Отключена"}</span>
                    </td>
                    <td>
                      <button type="button" className="btn btn-sm" disabled={busy === s.id} onClick={() => toggle(s)}>
                        {s.is_active ? "Отключить" : "Включить"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
