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
import { Link } from "react-router-dom";

import { type AdminProduct, type AdminUser, errorText, paged, type Project, send, API, get, type Team } from "../../api";
import { RoleMatrix, rolesBody } from "../../components/RoleMatrix";

const LIMIT = 50;

export function UsersPage() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: AdminUser[]; total: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
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
  // Команды перечитываются вместе со списком: состав мог поменяться на соседнем экране.
  useEffect(() => {
    get<Team[]>("/admin/groups").then(setTeams, () => setTeams([]));
  }, [data]);

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
          teams={teams}
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
  teams: Team[];
  onClose: () => void;
  onChanged: () => void;
}

function UserDrawer({ user, products, projects, teams, onClose, onChanged }: DrawerProps) {
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

  const myTeams = teams.filter((t) => user.groups.includes(t.id));
  // Эффективная роль без своей — пришла из команды; называем команды, если они уже загружены.
  const inheritedFrom = (pid: string, role: string) => {
    if (!(user.roles[pid] ?? []).includes(role) || (user.own_roles[pid] ?? []).includes(role)) return null;
    const names = myTeams.filter((t) => (t.roles[pid] ?? []).includes(role)).map((t) => `«${t.name}»`);
    return names.length ? `из команды ${names.join(", ")}` : "из команды";
  };
  const teamProject = (projectId: string) => {
    const names = myTeams.filter((t) => t.projects.includes(projectId)).map((t) => `«${t.name}»`);
    return names.length ? `из команды ${names.join(", ")}` : null;
  };

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

      <h3>Команды</h3>
      {user.groups.length === 0 ? (
        <p className="muted">
          Не состоит в командах. Состав команд меняется на экране <Link to="/admin/groups">Команды</Link>.
        </p>
      ) : (
        <ul className="form" style={{ listStyle: "none", padding: 0, margin: 0 }} aria-label="Команды пользователя">
          {myTeams.map((t) => (
            <li key={t.id}>
              <Link to={`/admin/groups?open=${t.id}`}>{t.name}</Link>
              {t.description && <span className="muted"> — {t.description}</span>}
            </li>
          ))}
        </ul>
      )}

      <h3>Роли в продуктах</h3>
      <p className="muted">Отмечены эффективные роли: свои и полученные из команд. Роль из команды снимается в самой команде.</p>
      <RoleMatrix products={products} value={roles} onChange={setRoles} disabled={self} inheritedFrom={inheritedFrom} />
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={self}
          onClick={() =>
            run(
              () => send("PUT", `/admin/users/${user.id}/roles`, rolesBody(products, roles)),
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
              {teamProject(p.id) && <small className="muted">{teamProject(p.id)}</small>}
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
