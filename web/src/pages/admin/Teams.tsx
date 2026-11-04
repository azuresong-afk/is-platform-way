import { ConfirmDanger, Drawer, Empty, ErrorAlert, Loading, Modal, PageHead, useAuth } from "@platform/ui";
import { Lock, Plus, Search, UsersRound } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { type AdminProduct, type AdminUser, errorText, get, type Project, send, type Team } from "../../api";
import { RoleMatrix, rolesBody, rolesSummary } from "../../components/RoleMatrix";

const REFRESH_NOTE = "Изменения попадут в токены участников при следующем обновлении, не позже 15 минут.";

export function TeamsPage() {
  const [params, setParams] = useSearchParams();
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const openId = params.get("open");
  const setOpenId = (id: string | null) => setParams(id ? { open: id } : {}, { replace: true });

  const load = useCallback(() => {
    setError(null);
    get<Team[]>("/admin/groups").then(setTeams, setError);
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    get<AdminProduct[]>("/admin/products").then(setProducts, () => setProducts([]));
    get<Project[]>("/admin/projects?limit=500").then(setProjects, () => setProjects([]));
    get<AdminUser[]>("/admin/users?limit=500").then(setUsers, () => setUsers([]));
  }, []);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!teams || !needle) return teams;
    return teams.filter((t) => t.name.toLowerCase().includes(needle) || t.description.toLowerCase().includes(needle));
  }, [teams, q]);
  const current = teams?.find((t) => t.id === openId) ?? null;

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Команды"
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" />
            Новая команда
          </button>
        }
      />
      <section className="card">
        <div className="card-head">
          <label className="search-trigger" style={{ cursor: "text" }}>
            <Search size={15} aria-hidden="true" />
            <input
              style={{ border: 0, background: "transparent", color: "inherit", font: "inherit", flex: 1, outline: "none" }}
              placeholder="Название или описание"
              aria-label="Поиск команд"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          {teams && <span className="count">{teams.length}</span>}
        </div>
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : !shown ? (
          <Loading />
        ) : shown.length === 0 ? (
          teams?.length === 0 ? (
            <Empty
              icon={UsersRound}
              title="Команд нет"
              text="Команда выдаёт своим участникам роли в продуктах и доступ к проектам одним набором."
              action={
                <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                  Новая команда
                </button>
              }
            />
          ) : (
            <Empty icon={UsersRound} title="Ничего не нашли" text="Измените условия поиска." />
          )
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Участники</th>
                  <th>Роли в продуктах</th>
                  <th>Проекты</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => (
                  <tr key={t.id} className={`clickable${t.id === openId ? " selected" : ""}`} onClick={() => setOpenId(t.id)}>
                    <td>
                      {t.name}
                      {t.description && <div className="muted">{t.description}</div>}
                    </td>
                    <td>{t.members.length || <span className="muted">—</span>}</td>
                    <td>{rolesSummary(products, t.roles) || <span className="muted">—</span>}</td>
                    <td>
                      {t.projects.length === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        t.projects.map((id) => (
                          <span key={id} className="tag" style={{ marginRight: 4 }}>
                            {projects.find((p) => p.id === id)?.name ?? id}
                          </span>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <CreateTeamModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(t) => {
          load();
          setOpenId(t.id);
        }}
      />
      {current && (
        <TeamDrawer
          key={current.id}
          team={current}
          products={products}
          projects={projects}
          users={users}
          onClose={() => setOpenId(null)}
          onChanged={load}
          onDeleted={() => {
            setOpenId(null);
            load();
          }}
        />
      )}
    </>
  );
}

function TeamFields({ name, description, onChange }: { name: string; description: string; onChange: (v: { name: string; description: string }) => void }) {
  return (
    <>
      <label className="field">
        <span>Название</span>
        <input className="input" required maxLength={200} value={name} onChange={(e) => onChange({ name: e.target.value, description })} />
      </label>
      <label className="field">
        <span>Описание</span>
        <input
          className="input"
          maxLength={2000}
          placeholder="Для чего команда и кто в неё входит"
          value={description}
          onChange={(e) => onChange({ name, description: e.target.value })}
        />
      </label>
    </>
  );
}

function CreateTeamModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (t: Team) => void }) {
  const [form, setForm] = useState({ name: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const t = await send<Team>("POST", "/admin/groups", form);
      setForm({ name: "", description: "" });
      onClose();
      onCreated(t);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      title="Новая команда"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="team-create" className="btn btn-primary" disabled={busy}>
            Создать
          </button>
        </>
      }
    >
      <form id="team-create" className="form" onSubmit={submit}>
        {error && (
          <div className="alert-danger" role="alert">
            <div className="alert-body">{error}</div>
          </div>
        )}
        <TeamFields {...form} onChange={setForm} />
      </form>
    </Modal>
  );
}

interface DrawerProps {
  team: Team;
  products: AdminProduct[];
  projects: Project[];
  users: AdminUser[];
  onClose: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}

function TeamDrawer({ team, products, projects, users, onClose, onChanged, onDeleted }: DrawerProps) {
  const auth = useAuth();
  const meId = auth.user?.id;
  const [info, setInfo] = useState({ name: team.name, description: team.description });
  const [members, setMembers] = useState<string[]>(team.members);
  const [roles, setRoles] = useState<Record<string, string[]>>(team.roles);
  const [inProjects, setInProjects] = useState<string[]>(team.projects);
  const [who, setWho] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);

  // Разделение обязанностей (то же правило проверяет API): администратор не выдаёт себе доступ через команду.
  const iAmMember = !!meId && team.members.includes(meId);
  const grants = Object.values(team.roles).some((r) => r.length > 0) || team.projects.length > 0;

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

  const needle = who.trim().toLowerCase();
  const candidates = users
    .filter((u) => members.includes(u.id) || u.is_active)
    .filter((u) => !needle || u.username.toLowerCase().includes(needle) || u.display_name.toLowerCase().includes(needle))
    .sort((a, b) => Number(members.includes(b.id)) - Number(members.includes(a.id)));

  return (
    <Drawer open title={team.name} onClose={onClose}>
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          run(() => send("PATCH", `/admin/groups/${team.id}`, info), "Команда сохранена.");
        }}
      >
        <TeamFields {...info} onChange={setInfo} />
        <div className="actions">
          <button type="submit" className="btn btn-primary">
            Сохранить
          </button>
        </div>
      </form>

      <h3>
        Участники <span className="count">{members.length}</span>
      </h3>
      <div className="form">
        <label className="search-trigger" style={{ cursor: "text" }}>
          <Search size={15} aria-hidden="true" />
          <input
            style={{ border: 0, background: "transparent", color: "inherit", font: "inherit", flex: 1, outline: "none" }}
            placeholder="Логин или имя"
            aria-label="Поиск участников"
            value={who}
            onChange={(e) => setWho(e.target.value)}
          />
        </label>
        <div style={{ display: "grid", gap: 6, maxHeight: 280, overflowY: "auto" }}>
          {candidates.map((u) => {
            const blocked = u.id === meId && grants && !team.members.includes(u.id);
            return (
              <label key={u.id} className="checkbox">
                <input
                  type="checkbox"
                  checked={members.includes(u.id)}
                  disabled={blocked}
                  onChange={() => setMembers((m) => (m.includes(u.id) ? m.filter((x) => x !== u.id) : [...m, u.id]))}
                />
                {u.display_name || u.username} <span className="muted mono">{u.username}</span>
                {blocked && <small className="muted">себя в команду с ролями добавляет другой администратор</small>}
                {!u.is_active && <span className="pill pill-muted">Отключён</span>}
              </label>
            );
          })}
          {candidates.length === 0 && <span className="muted">Никого не нашли</span>}
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn"
            onClick={() => run(() => send("PUT", `/admin/groups/${team.id}/members`, { ids: members }), `Состав сохранён. ${REFRESH_NOTE}`)}
          >
            Сохранить состав
          </button>
        </div>
      </div>

      {iAmMember && (
        <div className="alert-info">
          <Lock size={18} aria-hidden="true" />
          <div className="alert-body">
            Разделение обязанностей: вы состоите в этой команде, поэтому её роли и проекты меняет другой администратор.
          </div>
        </div>
      )}

      <h3>Роли в продуктах</h3>
      <RoleMatrix products={products} value={roles} onChange={setRoles} disabled={iAmMember} />
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={iAmMember}
          onClick={() => run(() => send("PUT", `/admin/groups/${team.id}/roles`, rolesBody(products, roles)), `Роли команды сохранены. ${REFRESH_NOTE}`)}
        >
          Сохранить роли
        </button>
      </div>

      <h3>Проекты</h3>
      <fieldset className="form" disabled={iAmMember} style={{ border: 0, padding: 0, margin: 0 }}>
        {projects.length === 0 && <span className="muted">Проектов нет</span>}
        {projects.map((p) => (
          <label key={p.id} className="checkbox">
            <input
              type="checkbox"
              checked={inProjects.includes(p.id)}
              onChange={() => setInProjects((m) => (m.includes(p.id) ? m.filter((x) => x !== p.id) : [...m, p.id]))}
            />
            {p.name}
            {p.status === "archived" && <span className="pill pill-muted">Архив</span>}
          </label>
        ))}
        <div className="actions">
          <button
            type="button"
            className="btn"
            onClick={() => run(() => send("PUT", `/admin/groups/${team.id}/projects`, { ids: inProjects }), `Проекты команды сохранены. ${REFRESH_NOTE}`)}
          >
            Сохранить проекты
          </button>
        </div>
      </fieldset>

      <h3>Удаление</h3>
      <div className="actions">
        <button type="button" className="btn btn-danger" onClick={() => setConfirm(true)}>
          Удалить команду
        </button>
      </div>
      <ConfirmDanger
        open={confirm}
        title="Удалить команду?"
        confirmLabel="Удалить"
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          send("DELETE", `/admin/groups/${team.id}`).then(onDeleted, (e) => setMessage({ kind: "danger", text: errorText(e) }));
        }}
      >
        <p>
          Участники команды «{team.name}» потеряют роли и проекты, которые получали через неё, при следующем обновлении токена.
          Их собственные роли не изменятся.
        </p>
      </ConfirmDanger>
    </Drawer>
  );
}
