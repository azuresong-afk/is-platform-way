import {
  apiJson,
  ConfirmDanger,
  Drawer,
  Empty,
  ErrorAlert,
  formatDateTime,
  Loading,
  Modal,
  PageHead,
  Pager,
  SeverityBadge,
  useProject,
} from "@platform/ui";
import { Plus, Search, Server, Upload } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  type AdminProduct,
  API,
  type Asset,
  type AssetFacets,
  type Criticality,
  errorText,
  get,
  type ImportReport,
  paged,
  type Project,
  send,
} from "../../api";
import { ASSET_FIELDS, CRITICALITY } from "../../labels";

const LIMIT = 50;
const PLATFORM = "platform";
const LIST_FIELDS = ["tags", "groups"] as const;

type Draft = Record<"hostname" | "os_family" | "os" | "owner" | "criticality" | (typeof LIST_FIELDS)[number], string>;

const toDraft = (a?: Asset): Draft => ({
  hostname: a?.hostname ?? "",
  os_family: a?.os_family ?? "",
  os: a?.os ?? "",
  owner: a?.owner ?? "",
  criticality: a?.criticality ?? "",
  tags: (a?.tags ?? []).join(", "),
  groups: (a?.groups ?? []).join(", "),
});

const splitList = (s: string) =>
  s
    .split(/[;,]/)
    .map((x) => x.trim())
    .filter(Boolean);

/** Тело запроса: только поля, которые отличаются от исходных (иначе они стали бы «ручными»). */
function diff(draft: Draft, base: Draft): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(draft) as (keyof Draft)[]) {
    if (draft[k] === base[k]) continue;
    out[k] = (LIST_FIELDS as readonly string[]).includes(k) ? splitList(draft[k]) : k === "criticality" ? draft[k] || null : draft[k];
  }
  return out;
}

function Crit({ level }: { level: Criticality | null }) {
  if (!level) return <span className="muted">—</span>;
  return <SeverityBadge level={level} label={CRITICALITY[level]} />;
}

/** Сводный реестр активов проекта: события продуктов, ручная правка, импорт CSV. */
export function AssetsPage() {
  const { projectId: shellProject } = useProject();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState<string>("");
  const [productTitles, setProductTitles] = useState<Record<string, string>>({});
  const [q, setQ] = useState("");
  const [crit, setCrit] = useState("");
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("");
  const [manualOnly, setManualOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: Asset[]; total: number } | null>(null);
  const [facets, setFacets] = useState<AssetFacets | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    get<Project[]>("/admin/projects?limit=500").then(
      (list) => setProjects(list),
      (e) => {
        setProjects([]);
        setError(e);
      },
    );
    get<AdminProduct[]>("/admin/products").then(
      (list) => setProductTitles(Object.fromEntries(list.map((p) => [p.id, p.manifest?.title ?? p.title ?? p.id]))),
      () => setProductTitles({}),
    );
  }, []);

  // Проект по умолчанию — выбранный в оболочке, иначе первый активный.
  useEffect(() => {
    if (!projects || projectId) return;
    const pick = projects.find((p) => p.id === shellProject) ?? projects.find((p) => p.status === "active") ?? projects[0];
    if (pick) setProjectId(pick.id);
  }, [projects, projectId, shellProject]);

  const load = useCallback(() => {
    if (!projectId) return;
    setError(null);
    const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
    if (q.trim()) params.set("q", q.trim());
    if (crit) params.set("criticality", crit);
    if (source) params.set("source", source);
    if (tag) params.set("tag", tag);
    if (manualOnly) params.set("manual", "true");
    paged<Asset>(`${API}/projects/${projectId}/assets?${params}`).then(setData, setError);
  }, [projectId, offset, q, crit, source, tag, manualOnly]);
  useEffect(load, [load]);

  const loadFacets = useCallback(() => {
    if (!projectId) return;
    get<AssetFacets>(`/projects/${projectId}/assets/facets`).then(setFacets, () => setFacets(null));
  }, [projectId]);
  useEffect(loadFacets, [loadFacets]);

  const changed = () => {
    load();
    loadFacets();
  };
  const title = useCallback((id: string) => (id === PLATFORM ? "Платформа" : productTitles[id] ?? id), [productTitles]);
  const project = projects?.find((p) => p.id === projectId);
  const readOnly = project?.status === "archived";
  const current = data?.items.find((a) => a.id === openId);
  const reset = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Реестр активов"
        actions={
          <>
            {projects && projects.length > 0 && (
              <select
                className="select"
                style={{ width: "auto", maxWidth: 320 }}
                aria-label="Проект"
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setOffset(0);
                  setOpenId(null);
                }}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.status === "archived" ? " (архив)" : ""}
                  </option>
                ))}
              </select>
            )}
            <button type="button" className="btn" disabled={!projectId || readOnly} onClick={() => setImporting(true)}>
              <Upload size={15} aria-hidden="true" />
              Импорт CSV
            </button>
            <button type="button" className="btn btn-primary" disabled={!projectId || readOnly} onClick={() => setCreating(true)}>
              <Plus size={15} aria-hidden="true" />
              Новый актив
            </button>
          </>
        }
      />
      {readOnly && (
        <div className="alert-info" role="status">
          <div className="alert-body">Проект в архиве: реестр доступен только для чтения.</div>
        </div>
      )}
      <section className="card">
        <div className="card-head" style={{ flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", flex: 1 }}>
            <label className="search-trigger" style={{ cursor: "text", minWidth: 220 }}>
              <Search size={15} aria-hidden="true" />
              <input
                style={{ border: 0, background: "transparent", color: "inherit", font: "inherit", flex: 1, outline: "none" }}
                placeholder="Адрес, хост, владелец, ОС"
                aria-label="Поиск активов"
                value={q}
                onChange={(e) => reset(() => setQ(e.target.value))}
              />
            </label>
            <select className="select select-sm" style={{ width: "auto" }} aria-label="Критичность" value={crit} onChange={(e) => reset(() => setCrit(e.target.value))}>
              <option value="">Любая критичность</option>
              {Object.entries(CRITICALITY).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
              <option value="none">Не задана</option>
            </select>
            <select className="select select-sm" style={{ width: "auto" }} aria-label="Источник" value={source} onChange={(e) => reset(() => setSource(e.target.value))}>
              <option value="">Все источники</option>
              {(facets?.sources ?? []).map((s) => (
                <option key={s} value={s}>
                  {title(s)}
                </option>
              ))}
            </select>
            {(facets?.tags.length ?? 0) > 0 && (
              <select className="select select-sm" style={{ width: "auto" }} aria-label="Тег" value={tag} onChange={(e) => reset(() => setTag(e.target.value))}>
                <option value="">Любой тег</option>
                {facets?.tags.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            )}
            <button type="button" className="chip" aria-pressed={manualOnly} onClick={() => reset(() => setManualOnly((v) => !v))}>
              Правленые вручную
            </button>
          </div>
          {data && <span className="count">{data.total}</span>}
        </div>
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : projects && projects.length === 0 ? (
          <Empty icon={Server} title="Проектов нет" text="Реестр активов ведётся по проектам. Сначала создайте проект." />
        ) : !data ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <Empty
            icon={Server}
            title="Активов нет"
            text="Активы появятся, когда продукты пришлют события об обнаруженных хостах. Их можно добавить вручную или загрузить из CSV."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Адрес</th>
                    <th>Имя хоста</th>
                    <th>ОС</th>
                    <th>Владелец</th>
                    <th>Критичность</th>
                    <th>Теги</th>
                    <th>Источники</th>
                    <th>Обновлён</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} className={`clickable${a.id === openId ? " selected" : ""}`} onClick={() => setOpenId(a.id)}>
                      <td className="mono">{a.address}</td>
                      <td>{a.hostname || <span className="muted">—</span>}</td>
                      <td>{a.os || a.os_family || <span className="muted">—</span>}</td>
                      <td>{a.owner || <span className="muted">—</span>}</td>
                      <td>
                        <Crit level={a.criticality} />
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {a.tags.length ? a.tags.map((t) => <span key={t} className="tag">{t}</span>) : <span className="muted">—</span>}
                      </td>
                      <td>
                        {a.sources.map((s) => (
                          <span key={s.product} className="pill pill-muted">
                            {title(s.product)}
                          </span>
                        ))}
                        {a.manual_fields.length > 0 && <span className="pill pill-info">правки</span>}
                      </td>
                      <td className="muted" style={{ whiteSpace: "nowrap" }}>{formatDateTime(a.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </section>
      {projectId && (
        <>
          <CreateModal open={creating} projectId={projectId} onClose={() => setCreating(false)} onSaved={changed} />
          <ImportModal open={importing} projectId={projectId} onClose={() => setImporting(false)} onDone={changed} />
        </>
      )}
      {current && (
        <AssetDrawer
          key={current.id + current.updated_at}
          asset={current}
          readOnly={readOnly}
          title={title}
          onClose={() => setOpenId(null)}
          onChanged={changed}
          onDeleted={() => {
            setOpenId(null);
            changed();
          }}
        />
      )}
    </>
  );
}

function AssetFields({ draft, setDraft, manual, onReset }: { draft: Draft; setDraft: (d: Draft) => void; manual?: string[]; onReset?: (f: string) => void }) {
  const label = (k: keyof Draft) => (
    <span>
      {ASSET_FIELDS[k]}
      {manual?.includes(k) && (
        <>
          {" "}
          <span className="pill pill-info">вручную</span>
          {onReset && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => onReset(k)} title="Вернуть значение из продукта">
              Сбросить
            </button>
          )}
        </>
      )}
    </span>
  );
  const f = (k: keyof Draft) => ({ value: draft[k], onChange: (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value }) });
  return (
    <>
      <div className="row-phi">
        <label className="field">
          {label("hostname")}
          <input className="input" {...f("hostname")} />
        </label>
        <label className="field">
          {label("criticality")}
          <select className="select" {...f("criticality")}>
            <option value="">Не задана</option>
            {Object.entries(CRITICALITY).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row-phi">
        <label className="field">
          {label("os")}
          <input className="input" {...f("os")} />
        </label>
        <label className="field">
          {label("os_family")}
          <input className="input" placeholder="linux, windows…" {...f("os_family")} />
        </label>
      </div>
      <label className="field">
        {label("owner")}
        <input className="input" {...f("owner")} />
      </label>
      <label className="field">
        {label("tags")}
        <input className="input" placeholder="через запятую" {...f("tags")} />
      </label>
      <label className="field">
        {label("groups")}
        <input className="input" placeholder="через запятую" {...f("groups")} />
      </label>
    </>
  );
}

function CreateModal({ open, projectId, onClose, onSaved }: { open: boolean; projectId: string; onClose: () => void; onSaved: () => void }) {
  const [address, setAddress] = useState("");
  const [draft, setDraft] = useState<Draft>(toDraft());
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await send("POST", `/projects/${projectId}/assets`, { address, ...diff(draft, toDraft()) });
      setAddress("");
      setDraft(toDraft());
      setError(null);
      onClose();
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <Modal
      open={open}
      title="Новый актив"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="asset-create" className="btn btn-primary">
            Добавить
          </button>
        </>
      }
    >
      <form id="asset-create" className="form" onSubmit={submit}>
        {error && (
          <div className="alert-danger" role="alert">
            <div className="alert-body">{error}</div>
          </div>
        )}
        <label className="field">
          <span>Адрес</span>
          <input className="input mono" required placeholder="10.0.0.5 или host.example.ru" value={address} onChange={(e) => setAddress(e.target.value)} />
          <small>IP-адрес или имя хоста. Пара «проект + адрес» уникальна.</small>
        </label>
        <AssetFields draft={draft} setDraft={setDraft} />
      </form>
    </Modal>
  );
}

function ImportModal({ open, projectId, onClose, onDone }: { open: boolean; projectId: string; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    setFile(null);
    setReport(null);
    setError(null);
    onClose();
  };
  const upload = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const r = await apiJson<ImportReport>(`${API}/projects/${projectId}/assets/import${dryRun ? "?dry_run=true" : ""}`, {
        method: "POST",
        body,
        platform: true,
      });
      setReport(r);
      if (!dryRun) onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const done = report && !report.dry_run;
  return (
    <Modal
      open={open}
      title="Импорт активов из CSV"
      onClose={close}
      size="lg"
      footer={
        done ? (
          <button type="button" className="btn btn-primary" onClick={close}>
            Готово
          </button>
        ) : (
          <>
            <button type="button" className="btn" onClick={close}>
              Отмена
            </button>
            <button type="button" className="btn" disabled={!file || busy} onClick={() => upload(true)}>
              Проверить
            </button>
            <button type="button" className="btn btn-primary" disabled={!file || busy} onClick={() => upload(false)}>
              Импортировать
            </button>
          </>
        )
      }
    >
      <div className="form">
        <p className="muted">
          Первая строка — заголовки: <span className="mono">address</span> (обязательно), <span className="mono">hostname</span>,{" "}
          <span className="mono">os_family</span>, <span className="mono">os</span>, <span className="mono">owner</span>,{" "}
          <span className="mono">criticality</span>, <span className="mono">tags</span>, <span className="mono">groups</span> — или русские
          названия колонок, как в таблице. Разделитель — запятая или точка с запятой, кодировка UTF-8 или Windows-1251. Теги и группы
          внутри ячейки — через запятую.
        </p>
        <p className="muted">
          Значения из файла считаются ручными: события продуктов их не перезапишут. Пустая ячейка поле не меняет.
        </p>
        {error && (
          <div className="alert-danger" role="alert">
            <div className="alert-body">{error}</div>
          </div>
        )}
        {!done && (
          <label className="field">
            <span>Файл CSV</span>
            <input
              className="input"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setReport(null);
              }}
            />
          </label>
        )}
        {report && <ReportView report={report} />}
      </div>
    </Modal>
  );
}

function ReportView({ report }: { report: ImportReport }) {
  return (
    <>
      <div className={report.error_count ? "alert-warn" : "alert-ok"} role="status">
        <div className="alert-body">
          {report.dry_run ? "Проверка: ничего не сохранено. " : "Импорт выполнен. "}
          Строк: {report.rows}, новых: {report.created}, изменено: {report.updated}, без изменений: {report.unchanged}, с ошибками:{" "}
          {report.error_count}.
        </div>
      </div>
      {report.errors.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Строка</th>
                <th>Ошибка</th>
              </tr>
            </thead>
            <tbody>
              {report.errors.map((e) => (
                <tr key={`${e.line}-${e.error}`}>
                  <td className="mono">{e.line}</td>
                  <td>{e.error}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function AssetDrawer({
  asset,
  readOnly,
  title,
  onClose,
  onChanged,
  onDeleted,
}: {
  asset: Asset;
  readOnly: boolean;
  title: (id: string) => string;
  onClose: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const base = useMemo(() => toDraft(asset), [asset]);
  const [draft, setDraft] = useState<Draft>(base);
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const body = diff(draft, base);
  const dirty = Object.keys(body).length > 0;

  const run = async (action: () => Promise<unknown>, after: () => void) => {
    setMessage(null);
    try {
      await action();
      after();
    } catch (e) {
      setMessage({ kind: "danger", text: errorText(e) });
    }
  };

  return (
    <Drawer open title={<span className="mono">{asset.address}</span>} onClose={onClose}>
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          run(() => send("PATCH", `/assets/${asset.id}`, body), onChanged);
        }}
      >
        <fieldset disabled={readOnly} style={{ border: 0, padding: 0, margin: 0, display: "contents" }}>
          <AssetFields
            draft={draft}
            setDraft={setDraft}
            manual={asset.manual_fields}
            onReset={readOnly ? undefined : (f) => run(() => send("PATCH", `/assets/${asset.id}`, { reset: [f] }), onChanged)}
          />
          <small className="muted">Изменённые здесь поля станут ручными: события продуктов их больше не перезапишут, пока вы не нажмёте «Сбросить».</small>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={!dirty}>
              Сохранить
            </button>
          </div>
        </fieldset>
      </form>

      <h3>Источники</h3>
      {asset.sources.length === 0 ? (
        <p className="muted">Нет источников.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Источник</th>
                <th>Внешний id</th>
                <th>Видели</th>
              </tr>
            </thead>
            <tbody>
              {asset.sources.map((s) => (
                <tr key={s.product}>
                  <td>{s.product === PLATFORM ? "Платформа (вручную, CSV)" : title(s.product)}</td>
                  <td className="mono">{s.external_id ?? <span className="muted">—</span>}</td>
                  <td>{formatDateTime(s.seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!readOnly && (
        <>
          <h3>Удаление</h3>
          <div className="actions">
            <button type="button" className="btn btn-danger" onClick={() => setConfirm(true)}>
              Удалить актив
            </button>
          </div>
        </>
      )}
      <ConfirmDanger
        open={confirm}
        title="Удалить актив из реестра?"
        confirmLabel="Удалить"
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          run(() => send("DELETE", `/assets/${asset.id}`), onDeleted);
        }}
      >
        <p>
          Актив <span className="mono">{asset.address}</span> и его ручные поля будут удалены из сводного реестра. Если продукт снова пришлёт
          событие об этом хосте, актив появится заново — уже без ручных правок.
        </p>
      </ConfirmDanger>
    </Drawer>
  );
}
