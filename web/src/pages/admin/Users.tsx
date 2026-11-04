import {
  Drawer,
  Empty,
  ErrorAlert,
  formatDateTime,
  Loading,
  Modal,
  PageHead,
  Pager,
  useAuth,
} from "@platform/ui";
import { Lock, Plus, Search, Users } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type AdminProduct, type AdminUser, errorText, paged, type Project, send, API, get } from "../../api";

const LIMIT = 50;

export function UsersPage() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: AdminUser[]; total: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setError(null);
    const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
    if (q.trim()) params.set("q", q.trim());
    paged<AdminUser>(`${API}/admin/users?${params}`).then(setData, setError);
  }, [q, offset]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  useEffect(() => {
    get<AdminProduct[]>("/admin/products").then(setProducts, () => setProducts([]));
    get<Project[]>("/admin/projects?limit=500").then(setProjects, () => setProjects([]));
  }, []);

  const roleLabel = (pid: string, role: string) => products.find((p) => p.id === pid)?.manifest.roles?.[role] ?? role;
  const productTitle = (pid: string) => products.find((p) => p.id === pid)?.title ?? pid;
  const current = data?.items.find((u) => u.id === openId) ?? null;

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Пользователи и доступ"
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" />
            Новый пользователь
          </button>
        }
      />
      <section className="card">
        <div className="card-head">
          <label className="search-trigger" style={{ cursor: "text" }}>
            <Search size={15} aria-hidden="true" />
            <input
              style={{ border: 0, background: "transparent", color: "inherit", font: "inherit", flex: 1, outline: "none" }}
              placeholder="Логин, имя или почта"
              aria-label="Поиск пользователей"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
            />
          </label>
          {data && <span className="count">{data.total}</span>}
        </div>
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : !data ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <Empty icon={Users} title="Никого не нашли" text="Измените условия поиска." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Логин</th>
                    <th>Имя</th>
                    <th>Роли в продуктах</th>
                    <th>Проекты</th>
                    <th>Состояние</th>
                    <th>Последний вход</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((u) => (
                    <tr key={u.id} className={`clickable${u.id === openId ? " selected" : ""}`} onClick={() => setOpenId(u.id)}>
                      <td className="mono">{u.username}</td>
                      <td>
                        {u.display_name}
                        {u.is_platform_admin && (
                          <>
                            {" "}
                            <span className="pill pill-info">Администратор платформы</span>
                          </>
                        )}
                      </td>
                      <td>
                        {Object.entries(u.roles).length === 0 ? (
                          <span className="muted">—</span>
                        ) : (
                          Object.entries(u.roles)
                            .map(([pid, roles]) => `${productTitle(pid)}: ${roles.map((r) => roleLabel(pid, r)).join(", ")}`)
                            .join("; ")
                        )}
                      </td>
                      <td>{u.all_projects ? "Все проекты" : u.projects.length || <span className="muted">—</span>}</td>
                      <td>
                        {!u.is_active ? (
                          <span className="pill pill-muted">Отключён</span>
                        ) : u.locked ? (
                          <span className="pill pill-warn">Заблокирован</span>
                        ) : (
                          <span className="pill pill-ok">Активен</span>
                        )}
                      </td>
                      <td>{formatDateTime(u.last_login_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </section>
      {current && (
        <UserDrawer
          key={current.id}
          user={current}
          products={products}
          projects={projects}
          onClose={() => setOpenId(null)}
          onChanged={load}
        />
      )}
      <CreateUserModal open={creating} onClose={() => setCreating(false)} onCreated={(u) => { load(); setOpenId(u.id); }} />
    </>
  );
}

function CreateUserModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (u: AdminUser) => void }) {
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await send<AdminUser>("POST", "/admin/users", { ...form, email: form.email || null });
      setForm({ username: "", display_name: "", email: "", password: "" });
      onClose();
      onCreated(u);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const field = (k: keyof typeof form) => ({ value: form[k], onChange: (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value }) });
  return (
    <Modal
      open={open}
      title="Новый пользователь"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="create-user" className="btn btn-primary" disabled={busy}>
            Создать
          </button>
        </>
      }
    >
      <form id="create-user" className="form" onSubmit={submit}>
        {error && <div className="alert-danger" role="alert"><div className="alert-body">{error}</div></div>}
        <label className="field">
          <span>Логин</span>
          <input className="input" required autoFocus {...field("username")} />
          <small>Латиница, цифры и . _ @ -</small>
        </label>
        <label className="field">
          <span>Имя</span>
          <input className="input" placeholder="Иванов И. И." {...field("display_name")} />
        </label>
        <label className="field">
          <span>Почта</span>
          <input className="input" type="email" {...field("email")} />
        </label>
        <label className="field">
          <span>Временный пароль</span>
          <input className="input" type="password" required minLength={10} autoComplete="new-password" {...field("password")} />
          <small>Не короче 10 символов</small>
        </label>
      </form>
    </Modal>
  );
}

interface DrawerProps {
  user: AdminUser;
  products: AdminProduct[];
  projects: Project[];
  onClose: () => void;
  onChanged: () => void;
}

function UserDrawer({ user, products, projects, onClose, onChanged }: DrawerProps) {
  const auth = useAuth();
  const self = auth.user?.id === user.id;
  const [roles, setRoles] = useState<Record<string, string[]>>(user.own_roles);
  const [allProjects, setAllProjects] = useState(user.all_projects);
  const [memberOf, setMemberOf] = useState<string[]>(user.projects.map((p) => p.project_id));
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [password, setPassword] = useState("");

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

  const toggleRole = (pid: string, role: string) =>
    setRoles((r) => {
      const cur = r[pid] ?? [];
      return { ...r, [pid]: cur.includes(role) ? cur.filter((x) => x !== role) : [...cur, role] };
    });

  const inherited = (pid: string, role: string) => (user.roles[pid] ?? []).includes(role) && !(user.own_roles[pid] ?? []).includes(role);

  return (
    <Drawer open title={user.display_name || user.username} onClose={onClose}>
      {self && (
        <div className="alert-info">
          <Lock size={18} aria-hidden="true" />
          <div className="alert-body">
            Разделение обязанностей: свои роли в продуктах, доступ к проектам и статус меняет другой администратор.
          </div>
        </div>
      )}
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      <dl className="stat-list">
        <div>
          <dt>Логин</dt>
          <dd className="mono">{user.username}</dd>
        </div>
        <div>
          <dt>Источник</dt>
          <dd>{user.auth_source === "local" ? "Платформа" : user.auth_source}</dd>
        </div>
        <div>
          <dt>Создан</dt>
          <dd>{formatDateTime(user.created_at)}</dd>
        </div>
      </dl>

      <h3>Роли в продуктах</h3>
      {products.map((p) => (
        <fieldset key={p.id} className="card card-pad" style={{ gap: 8 }} disabled={self}>
          <legend className="kpi-label" style={{ padding: "0 4px" }}>
            {p.title}
          </legend>
          {Object.entries(p.manifest.roles ?? {}).map(([role, label]) => (
            <label key={role} className="checkbox">
              <input
                type="checkbox"
                checked={(roles[p.id] ?? []).includes(role) || inherited(p.id, role)}
                disabled={inherited(p.id, role)}
                onChange={() => toggleRole(p.id, role)}
              />
              {label}
              {inherited(p.id, role) && <small>через команду</small>}
              {(p.manifest.admin_roles ?? []).includes(role) && <span className="pill pill-muted">администрирование продукта</span>}
            </label>
          ))}
        </fieldset>
      ))}
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={self}
          onClick={() =>
            run(
              () => send("PUT", `/admin/users/${user.id}/roles`, { products: Object.fromEntries(products.map((p) => [p.id, roles[p.id] ?? []])) }),
              "Роли сохранены. Изменения вступят в силу при следующем обновлении токена, не позже 15 минут.",
            )
          }
        >
          Сохранить роли
        </button>
      </div>

      <h3>Проекты</h3>
      <fieldset className="form" disabled={self} style={{ border: 0, padding: 0, margin: 0 }}>
        <label className="checkbox">
          <input type="checkbox" checked={allProjects} onChange={(e) => setAllProjects(e.target.checked)} />
          Все проекты
        </label>
        {!allProjects &&
          projects.map((p) => (
            <label key={p.id} className="checkbox">
              <input
                type="checkbox"
                checked={memberOf.includes(p.id)}
                onChange={() => setMemberOf((m) => (m.includes(p.id) ? m.filter((x) => x !== p.id) : [...m, p.id]))}
              />
              {p.name}
              {p.status === "archived" && <span className="pill pill-muted">Архив</span>}
            </label>
          ))}
        <div className="actions">
          <button
            type="button"
            className="btn"
            onClick={() =>
              run(
                () =>
                  send("PUT", `/admin/users/${user.id}/projects`, {
                    all_projects: allProjects,
                    projects: allProjects ? [] : memberOf.map((id) => ({ project_id: id })),
                  }),
                "Доступ к проектам сохранён.",
              )
            }
          >
            Сохранить проекты
          </button>
        </div>
      </fieldset>

      <h3>Учётная запись</h3>
      <div className="actions">
        {user.locked && (
          <button type="button" className="btn" onClick={() => run(() => send("POST", `/admin/users/${user.id}/unlock`), "Блокировка снята.")}>
            Снять блокировку
          </button>
        )}
        <button
          type="button"
          className={user.is_active ? "btn btn-danger" : "btn"}
          disabled={self}
          onClick={() =>
            run(
              () => send("PATCH", `/admin/users/${user.id}`, { is_active: !user.is_active }),
              user.is_active ? "Пользователь отключён, все его сессии закрыты." : "Пользователь включён.",
            )
          }
        >
          {user.is_active ? "Отключить" : "Включить"}
        </button>
        <button
          type="button"
          className="btn"
          disabled={self}
          onClick={() =>
            run(
              () => send("PATCH", `/admin/users/${user.id}`, { is_platform_admin: !user.is_platform_admin }),
              "Права администратора платформы изменены.",
            )
          }
        >
          {user.is_platform_admin ? "Снять права администратора" : "Сделать администратором платформы"}
        </button>
      </div>
      {user.auth_source === "local" && (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            run(() => send("POST", `/admin/users/${user.id}/password`, { password }), "Пароль изменён, сессии пользователя закрыты.").then(() =>
              setPassword(""),
            );
          }}
        >
          <label className="field">
            <span>Новый пароль</span>
            <input className="input" type="password" minLength={10} required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <div className="actions">
            <button type="submit" className="btn">
              Сменить пароль
            </button>
          </div>
        </form>
      )}
    </Drawer>
  );
}
