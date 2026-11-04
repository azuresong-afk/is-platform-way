import { ConfirmDanger, Drawer, Empty, ErrorAlert, formatDateTime, Loading, Modal, PageHead } from "@platform/ui";
import { Copy, KeyRound, Plus } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type AdminProduct, API, errorText, get, paged, type Project, send, type ServiceAccount } from "../../api";

type WithSecret = ServiceAccount & { client_secret: string };

interface Refs {
  products: AdminProduct[];
  projects: Project[];
}

function useRefs(): Refs {
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  useEffect(() => {
    get<AdminProduct[]>("/admin/products").then((xs) => setProducts(Array.isArray(xs) ? xs.filter((p) => p.enabled) : []), () => setProducts([]));
    paged<Project>(`${API}/admin/projects?limit=500&status=active`).then((d) => setProjects(d.items), () => setProjects([]));
  }, []);
  return { products, projects };
}

const roleLabel = (refs: Refs, product: string, role: string) =>
  refs.products.find((p) => p.id === product)?.manifest.roles?.[role] ?? role;

export function ServiceAccountsPage() {
  const refs = useRefs();
  const [items, setItems] = useState<ServiceAccount[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [secret, setSecret] = useState<WithSecret | null>(null);

  const load = useCallback(() => {
    setError(null);
    get<ServiceAccount[]>("/admin/service-accounts").then(setItems, setError);
  }, []);
  useEffect(load, [load]);

  const current = items?.find((x) => x.id === openId);
  const productTitle = (id: string) => refs.products.find((p) => p.id === id)?.title ?? id;

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Сервисные учётные записи"
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" />
            Новая запись
          </button>
        }
      />
      <div className="alert-info">
        <div className="alert-body">
          Для вызовов продукт → продукт: сервис получает токен по <code>POST /api/platform/auth/token</code> (client credentials) только для
          одного целевого продукта и только с выданными здесь ролями. Войти в интерфейс сервис не может.
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
          <Empty
            icon={KeyRound}
            title="Сервисных записей нет"
            text="Например, «Устранение» обращается к «Сканеру» за находками под записью vm-to-scanner с ролью «Аудитор»."
            action={
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                Новая запись
              </button>
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>client_id</th>
                  <th>Назначение</th>
                  <th>Продукт</th>
                  <th>Роли</th>
                  <th>Проекты</th>
                  <th>Последний токен</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {items.map((x) => (
                  <tr key={x.id} className={`clickable${x.id === openId ? " selected" : ""}`} onClick={() => setOpenId(x.id)}>
                    <td className="mono">{x.client_id}</td>
                    <td>{x.name}</td>
                    <td>{productTitle(x.target_product)}</td>
                    <td>
                      {x.roles.map((r) => (
                        <span key={r} className="tag">
                          {roleLabel(refs, x.target_product, r)}
                        </span>
                      ))}
                    </td>
                    <td>{x.all_projects ? "Все" : x.projects.length}</td>
                    <td>{x.last_used_at ? formatDateTime(x.last_used_at) : <span className="muted">не выдавался</span>}</td>
                    <td>
                      <span className={`pill ${x.is_active ? "pill-ok" : "pill-muted"}`}>{x.is_active ? "Активна" : "Отключена"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <CreateModal
        open={creating}
        refs={refs}
        onClose={() => setCreating(false)}
        onCreated={(x) => {
          setCreating(false);
          setSecret(x);
          load();
        }}
      />
      {secret && <SecretModal account={secret} onClose={() => setSecret(null)} />}
      {current && (
        <AccountDrawer
          key={current.id}
          account={current}
          refs={refs}
          onClose={() => setOpenId(null)}
          onChanged={load}
          onSecret={setSecret}
          onDeleted={() => {
            setOpenId(null);
            load();
          }}
        />
      )}
    </>
  );
}

interface Access {
  roles: string[];
  all_projects: boolean;
  projects: string[];
}

function AccessFields({ refs, product, value, onChange }: { refs: Refs; product: string; value: Access; onChange: (v: Access) => void }) {
  const roles = refs.products.find((p) => p.id === product)?.manifest.roles ?? {};
  const toggle = <T,>(xs: T[], x: T) => (xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x]);
  return (
    <>
      <fieldset className="card card-pad" style={{ gap: 8 }}>
        <legend className="kpi-label" style={{ padding: "0 4px" }}>
          Роли в продукте
        </legend>
        {Object.entries(roles).map(([role, label]) => (
          <label key={role} className="checkbox">
            <input type="checkbox" checked={value.roles.includes(role)} onChange={() => onChange({ ...value, roles: toggle(value.roles, role) })} />
            {label}
          </label>
        ))}
        {Object.keys(roles).length === 0 && <span className="muted">Выберите продукт</span>}
      </fieldset>
      <fieldset className="form" style={{ border: 0, padding: 0, margin: 0 }}>
        <label className="checkbox">
          <input type="checkbox" checked={value.all_projects} onChange={(e) => onChange({ ...value, all_projects: e.target.checked })} />
          Все проекты
        </label>
        {!value.all_projects &&
          refs.projects.map((p) => (
            <label key={p.id} className="checkbox">
              <input type="checkbox" checked={value.projects.includes(p.id)} onChange={() => onChange({ ...value, projects: toggle(value.projects, p.id) })} />
              {p.name}
            </label>
          ))}
      </fieldset>
    </>
  );
}

function CreateModal({ open, refs, onClose, onCreated }: { open: boolean; refs: Refs; onClose: () => void; onCreated: (x: WithSecret) => void }) {
  const [clientId, setClientId] = useState("");
  const [name, setName] = useState("");
  const [product, setProduct] = useState("");
  const [access, setAccess] = useState<Access>({ roles: [], all_projects: true, projects: [] });
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const x = await send<WithSecret>("POST", "/admin/service-accounts", { client_id: clientId, name, target_product: product, ...access });
      setClientId("");
      setName("");
      setProduct("");
      setAccess({ roles: [], all_projects: true, projects: [] });
      setError(null);
      onCreated(x);
    } catch (err) {
      setError(errorText(err));
    }
  };

  return (
    <Modal
      open={open}
      title="Новая сервисная учётная запись"
      onClose={onClose}
      size="lg"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="svc-create" className="btn btn-primary" disabled={!product || access.roles.length === 0}>
            Создать и показать секрет
          </button>
        </>
      }
    >
      <form id="svc-create" className="form" onSubmit={submit}>
        {error && (
          <div className="alert-danger" role="alert">
            <div className="alert-body">{error}</div>
          </div>
        )}
        <label className="field">
          <span>client_id</span>
          <input
            className="input mono"
            required
            pattern="[a-z0-9][a-z0-9._\-]{1,98}[a-z0-9]"
            placeholder="vm-to-scanner"
            value={clientId}
            onChange={(e) => setClientId(e.target.value.toLowerCase())}
          />
          <small className="muted">Латиница в нижнем регистре, цифры, точка, дефис, подчёркивание.</small>
        </label>
        <label className="field">
          <span>Назначение</span>
          <input className="input" required placeholder="Устранение → Сканер" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Целевой продукт</span>
          <select
            className="select"
            required
            value={product}
            onChange={(e) => {
              setProduct(e.target.value);
              setAccess((a) => ({ ...a, roles: [] }));
            }}
          >
            <option value="">Выберите…</option>
            {refs.products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        <AccessFields refs={refs} product={product} value={access} onChange={setAccess} />
      </form>
    </Modal>
  );
}

function SecretModal({ account, onClose }: { account: WithSecret; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(account.client_secret).then(
      () => setCopied(true),
      () => setCopied(false),
    );
  };
  return (
    <Modal
      open
      title="Секрет сервисной учётной записи"
      onClose={onClose}
      footer={
        <button type="button" className="btn btn-primary" onClick={onClose}>
          Секрет сохранён
        </button>
      }
    >
      <div className="alert-warn" role="alert">
        <div className="alert-body">Секрет показывается один раз. Сохраните его в секретах продукта (.env), платформа хранит только хэш.</div>
      </div>
      <dl className="stat-list">
        <div>
          <dt>client_id</dt>
          <dd className="mono">{account.client_id}</dd>
        </div>
        <div>
          <dt>client_secret</dt>
          <dd className="mono" style={{ wordBreak: "break-all" }} data-testid="svc-secret">
            {account.client_secret}
          </dd>
        </div>
      </dl>
      <div className="actions">
        <button type="button" className="btn" onClick={copy}>
          <Copy size={15} aria-hidden="true" />
          {copied ? "Скопировано" : "Скопировать секрет"}
        </button>
      </div>
    </Modal>
  );
}

function AccountDrawer({
  account,
  refs,
  onClose,
  onChanged,
  onSecret,
  onDeleted,
}: {
  account: ServiceAccount;
  refs: Refs;
  onClose: () => void;
  onChanged: () => void;
  onSecret: (x: WithSecret) => void;
  onDeleted: () => void;
}) {
  const [name, setName] = useState(account.name);
  const [access, setAccess] = useState<Access>({ roles: account.roles, all_projects: account.all_projects, projects: account.projects });
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [confirm, setConfirm] = useState<"rotate" | "delete" | null>(null);

  const run = async (action: () => Promise<unknown>, ok: string) => {
    setMessage(null);
    try {
      await action();
      setMessage({ kind: "ok", text: ok });
      onChanged();
    } catch (e) {
      setMessage({ kind: "danger", text: errorText(e) });
    }
  };

  return (
    <Drawer open title={account.client_id} onClose={onClose}>
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      <dl className="stat-list">
        <div>
          <dt>Целевой продукт</dt>
          <dd>{refs.products.find((p) => p.id === account.target_product)?.title ?? account.target_product}</dd>
        </div>
        <div>
          <dt>Секрет выпущен</dt>
          <dd>{formatDateTime(account.secret_rotated_at)}</dd>
        </div>
        <div>
          <dt>Последний токен</dt>
          <dd>{account.last_used_at ? formatDateTime(account.last_used_at) : "не выдавался"}</dd>
        </div>
      </dl>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          run(
            () => send("PATCH", `/admin/service-accounts/${account.id}`, { name, ...access }),
            "Сохранено. Уже выданные токены действуют до истечения, не дольше 15 минут.",
          );
        }}
      >
        <label className="field">
          <span>Назначение</span>
          <input className="input" required value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <AccessFields refs={refs} product={account.target_product} value={access} onChange={setAccess} />
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={access.roles.length === 0}>
            Сохранить
          </button>
        </div>
      </form>

      <h3>Состояние</h3>
      <div className="actions">
        <button
          type="button"
          className="btn"
          onClick={() =>
            run(
              () => send("PATCH", `/admin/service-accounts/${account.id}`, { is_active: !account.is_active }),
              account.is_active ? "Запись отключена: новые токены не выдаются." : "Запись включена.",
            )
          }
        >
          {account.is_active ? "Отключить" : "Включить"}
        </button>
        <button type="button" className="btn" onClick={() => setConfirm("rotate")}>
          Перевыпустить секрет
        </button>
        <button type="button" className="btn btn-danger" onClick={() => setConfirm("delete")}>
          Удалить
        </button>
      </div>
      <ConfirmDanger
        open={confirm === "rotate"}
        title="Перевыпустить секрет?"
        confirmLabel="Перевыпустить"
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          run(async () => onSecret(await send<WithSecret>("POST", `/admin/service-accounts/${account.id}/secret`)), "Секрет перевыпущен.");
        }}
      >
        <p>Старый секрет перестанет действовать сразу: сервис «{account.name}» не получит новый токен, пока секрет не заменят в его настройках.</p>
      </ConfirmDanger>
      <ConfirmDanger
        open={confirm === "delete"}
        title="Удалить сервисную учётную запись?"
        confirmLabel="Удалить"
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          send("DELETE", `/admin/service-accounts/${account.id}`).then(onDeleted, (e) => setMessage({ kind: "danger", text: errorText(e) }));
        }}
      >
        <p>
          Запись <span className="mono">{account.client_id}</span> будет удалена, новые токены не выдаются. Уже выданные действуют до истечения, не
          дольше 15 минут. Действие записывается в журнал аудита.
        </p>
      </ConfirmDanger>
    </Drawer>
  );
}
