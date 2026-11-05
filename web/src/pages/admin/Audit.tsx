import { apiFetch, Drawer, Empty, ErrorAlert, formatDateTime, Loading, PageHead, Pager } from "@platform/ui";
import { Download, ScrollText } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { API, type AuditEntry, type AuditFacets, errorText, get, paged } from "../../api";
import { AUDIT_RESULT } from "../../labels";

const LIMIT = 50;
// Фильтры живут в адресе страницы: ссылкой на выборку можно поделиться.
const KEYS = ["product", "project", "action", "result", "actor", "from", "to"] as const;
type Key = (typeof KEYS)[number];

/** Дата из поля ввода (локальный день) → граница периода в UTC; «по» — включительно. */
function dayBound(value: string, end: boolean): string {
  const d = new Date(`${value}T00:00:00`);
  if (end) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

function apiParams(sp: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const k of KEYS) {
    const v = sp.get(k)?.trim();
    if (!v) continue;
    if (k === "from" || k === "to") out.set(k, dayBound(v, k === "to"));
    else out.set(k, v);
  }
  return out;
}

/** Действия из журнала + группы по первому сегменту: «auth.*» — все действия входа. */
function actionOptions(actions: string[]): string[] {
  const groups = new Set<string>();
  for (const a of actions) {
    const i = a.indexOf(".");
    if (i > 0) groups.add(`${a.slice(0, i)}.*`);
  }
  return [...groups].filter((g) => actions.filter((a) => a.startsWith(g.slice(0, -1))).length > 1).concat(actions).sort();
}

export function AuditPage() {
  const [sp, setSp] = useSearchParams();
  const offset = Number(sp.get("offset") ?? 0) || 0;
  const [data, setData] = useState<{ items: AuditEntry[]; total: number } | null>(null);
  const [facets, setFacets] = useState<AuditFacets | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"" | "csv" | "json">("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [actor, setActor] = useState(sp.get("actor") ?? "");

  const query = apiParams(sp).toString();

  const load = useCallback(() => {
    setError(null);
    const params = new URLSearchParams(query);
    params.set("limit", String(LIMIT));
    params.set("offset", String(offset));
    paged<AuditEntry>(`${API}/audit?${params}`).then(setData, setError);
  }, [query, offset]);
  useEffect(load, [load]);
  useEffect(() => {
    get<AuditFacets>("/audit/facets").then(setFacets, () => setFacets({ products: [], projects: [], actions: [] }));
  }, []);

  const setFilter = useCallback(
    (key: Key, value: string) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          next.delete("offset");
          return next;
        },
        { replace: true },
      );
    },
    [setSp],
  );

  // поиск по пользователю — с паузой, чтобы не дёргать API на каждую букву
  useEffect(() => {
    if (actor === (sp.get("actor") ?? "")) return;
    const t = setTimeout(() => setFilter("actor", actor.trim()), 350);
    return () => clearTimeout(t);
  }, [actor, sp, setFilter]);

  const setOffset = (n: number) =>
    setSp((prev) => {
      const next = new URLSearchParams(prev);
      if (n) next.set("offset", String(n));
      else next.delete("offset");
      return next;
    });

  const filtered = KEYS.some((k) => sp.get(k));
  const reset = () => {
    setActor("");
    setSp(new URLSearchParams(), { replace: true });
  };

  const download = async (format: "csv" | "json") => {
    setExportError(null);
    setExporting(format);
    try {
      const params = new URLSearchParams(query);
      params.set("format", format);
      const r = await apiFetch(`${API}/audit/export?${params}`, { platform: true });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${r.status}`);
      }
      const name = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") ?? "")?.[1] ?? `audit.${format}`;
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setExportError(errorText(e));
    } finally {
      setExporting("");
    }
  };

  const actions = useMemo(() => actionOptions(facets?.actions ?? []), [facets]);
  const current = data?.items.find((a) => a.id === openId);
  const v = (k: Key) => sp.get(k) ?? "";

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Журнал аудита"
        actions={
          <>
            <button type="button" className="btn" disabled={!!exporting} onClick={() => download("csv")}>
              <Download size={15} aria-hidden="true" />
              {exporting === "csv" ? "Выгружаем…" : "CSV"}
            </button>
            <button type="button" className="btn" disabled={!!exporting} onClick={() => download("json")}>
              <Download size={15} aria-hidden="true" />
              {exporting === "json" ? "Выгружаем…" : "JSON"}
            </button>
          </>
        }
      />
      {exportError && (
        <div className="alert-danger" role="alert">
          <div className="alert-body">Выгрузка не удалась: {exportError}</div>
        </div>
      )}
      <section className="card">
        <div className="card-head" style={{ flexWrap: "wrap", justifyContent: "flex-start" }}>
          <select className="select select-sm" style={{ width: 170 }} aria-label="Продукт" value={v("product")} onChange={(e) => setFilter("product", e.target.value)}>
            <option value="">Все продукты</option>
            {facets?.products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
          <select className="select select-sm" style={{ width: 220 }} aria-label="Проект" value={v("project")} onChange={(e) => setFilter("project", e.target.value)}>
            <option value="">Все проекты</option>
            {facets?.projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
          <select className="select select-sm" style={{ width: 220 }} aria-label="Действие" value={v("action")} onChange={(e) => setFilter("action", e.target.value)}>
            <option value="">Все действия</option>
            {actions.map((a) => (
              <option key={a} value={a}>
                {a.endsWith(".*") ? `${a} (все)` : a}
              </option>
            ))}
          </select>
          <input
            className="input input-sm"
            style={{ width: 180 }}
            placeholder="Пользователь"
            aria-label="Пользователь: имя или идентификатор"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          />
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span className="muted">с</span>
            <input className="input input-sm" type="date" style={{ width: 150 }} aria-label="Период с" value={v("from")} onChange={(e) => setFilter("from", e.target.value)} />
          </label>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span className="muted">по</span>
            <input className="input input-sm" type="date" style={{ width: 150 }} aria-label="Период по" value={v("to")} onChange={(e) => setFilter("to", e.target.value)} />
          </label>
          <div className="seg" role="group" aria-label="Результат">
            {(["", "success", "failure", "denied"] as const).map((r) => (
              <button key={r} type="button" aria-pressed={v("result") === r} onClick={() => setFilter("result", r)}>
                {r ? AUDIT_RESULT[r].label : "Все"}
              </button>
            ))}
          </div>
          {filtered && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={reset}>
              Сбросить
            </button>
          )}
          {data && (
            <span className="count" style={{ marginLeft: "auto" }} title="Записей по фильтру">
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
          <Empty
            icon={ScrollText}
            title={filtered ? "Ничего не найдено" : "Журнал пуст"}
            text={
              filtered
                ? "Измените или сбросьте фильтры."
                : "Здесь появятся входы, изменения доступа и действия в продуктах."
            }
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Продукт</th>
                    <th>Пользователь</th>
                    <th>Действие</th>
                    <th>Объект</th>
                    <th>Проект</th>
                    <th>Результат</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} className={`clickable${a.id === openId ? " selected" : ""}`} onClick={() => setOpenId(a.id)}>
                      <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(a.time)}</td>
                      <td>
                        <span className="tag">{a.product_title}</span>
                      </td>
                      <td>{a.actor_name || (a.actor_sub ? <span className="mono">{a.actor_sub}</span> : <span className="muted">—</span>)}</td>
                      <td className="mono">{a.action}</td>
                      <td>{a.object || <span className="muted">—</span>}</td>
                      <td>{a.project_name ?? (a.project_id ? <span className="mono">{a.project_id}</span> : <span className="muted">—</span>)}</td>
                      <td>
                        <ResultPill result={a.result} />
                      </td>
                      <td className="mono">{a.ip || <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </section>
      {current && <EntryDrawer entry={current} onClose={() => setOpenId(null)} />}
    </>
  );
}

function ResultPill({ result }: { result: string }) {
  const r = AUDIT_RESULT[result] ?? { label: result, pill: "pill-muted" };
  return <span className={`pill ${r.pill}`}>{r.label}</span>;
}

function EntryDrawer({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  const rows: [string, ReactNode][] = [
    ["Время", formatDateTime(entry.time)],
    ["Продукт", entry.product_title],
    ["Пользователь", entry.actor_name || "—"],
    ["Идентификатор пользователя", entry.actor_sub ? <span className="mono">{entry.actor_sub}</span> : "—"],
    ["Действие", <span className="mono">{entry.action}</span>],
    ["Объект", entry.object || "—"],
    ["Проект", entry.project_name ?? entry.project_id ?? "—"],
    ["Результат", <ResultPill result={entry.result} />],
    ["IP", entry.ip ? <span className="mono">{entry.ip}</span> : "—"],
    ["Номер записи", <span className="mono">{entry.id}</span>],
  ];
  if (entry.event_id) rows.push(["Событие", <span className="mono">{entry.event_id}</span>]);
  const hasDetails = Object.keys(entry.details).length > 0;
  return (
    <Drawer open title="Запись журнала" onClose={onClose}>
      <dl className="stat-list">
        {rows.map(([k, val]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd style={{ textAlign: "right", wordBreak: "break-all" }}>{val}</dd>
          </div>
        ))}
      </dl>
      {hasDetails && (
        <section className="form">
          <span className="kpi-label">Подробности</span>
          <pre className="card card-pad" style={{ margin: 0, overflow: "auto", fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {JSON.stringify(entry.details, null, 2)}
          </pre>
        </section>
      )}
    </Drawer>
  );
}
