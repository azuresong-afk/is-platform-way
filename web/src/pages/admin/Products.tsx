import { Empty, ErrorAlert, formatDateTime, iconByName, Loading, PageHead } from "@platform/ui";
import { Boxes, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { type AdminProduct, errorText, get, send } from "../../api";
import { HEALTH } from "../../labels";

export function ProductsPage() {
  const [items, setItems] = useState<AdminProduct[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    get<AdminProduct[]>("/admin/products").then(setItems, setError);
  }, []);
  useEffect(load, [load]);

  const refresh = async (id: string) => {
    setBusy(id);
    try {
      const p = await send<AdminProduct>("POST", `/admin/products/${id}/refresh`);
      setItems((xs) => (xs ?? []).map((x) => (x.id === id ? p : x)));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHead breadcrumbs="Администрирование" title="Продукты" />
      <div className="alert-info">
        <div className="alert-body">
          Продукт появляется в кабинете, если его id указан в <code>PLATFORM_PRODUCTS</code> в .env платформы и задан адрес{" "}
          <code>&lt;ID&gt;_API_UPSTREAM</code>. Название, роли и вкладка берутся из манифеста продукта; манифест и
          состояние опрашиваются раз в минуту.
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
          <Empty icon={Boxes} title="Продукты не подключены" text="Задайте адреса продуктов в .env платформы и перезапустите её." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Продукт</th>
                  <th>Версия</th>
                  <th>Состояние</th>
                  <th>Манифест</th>
                  <th>Роли</th>
                  <th>Проверено</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((p) => {
                  const Icon = iconByName(p.icon);
                  const h = HEALTH[p.health] ?? HEALTH.unknown;
                  return (
                    <tr key={p.id}>
                      <td>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                          <Icon size={15} aria-hidden="true" />
                          {p.title} <span className="tag">{p.id}</span>
                        </span>
                      </td>
                      <td className="mono">{p.version || "—"}</td>
                      <td>
                        <span className={`pill ${h.pill}`}>{h.label}</span>
                        {p.last_error && <div><small>{p.last_error}</small></div>}
                      </td>
                      <td>{p.manifest_source === "product" ? "от продукта" : <span className="muted">встроенный</span>}</td>
                      <td>{Object.values(p.manifest.roles ?? {}).join(", ")}</td>
                      <td>{formatDateTime(p.health_checked_at)}</td>
                      <td className="num">
                        <button type="button" className="btn btn-sm" onClick={() => refresh(p.id)} disabled={busy === p.id}>
                          <RefreshCw size={15} aria-hidden="true" />
                          Проверить
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
