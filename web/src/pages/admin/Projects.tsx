import { ConfirmDanger, Drawer, Empty, ErrorAlert, formatDate, Loading, Modal, PageHead, Pager } from "@platform/ui";
import { FolderKanban, Plus } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { type AdminUser, API, errorText, get, type Member, paged, type Project, send } from "../../api";
import { useShell } from "../../components/ShellLayout";
import { PROJECT_STATUS } from "../../labels";

const LIMIT = 50;

type Draft = Pick<Project, "name" | "client" | "contract_ref"> & { period_from: string; period_to: string };
const EMPTY: Draft = { name: "", client: "", contract_ref: "", period_from: "", period_to: "" };

export function ProjectsPage() {
  const shell = useShell();
  const [status, setStatus] = useState<"" | "active" | "archived">("active");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: Project[]; total: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
    if (status) params.set("status", status);
    paged<Project>(`${API}/admin/projects?${params}`).then(setData, setError);
  }, [status, offset]);
  useEffect(load, [load]);

  const changed = () => {
    load();
    shell.reloadProjects();
  };
  const current = data?.items.find((p) => p.id === openId);

  return (
    <>
      <PageHead
        breadcrumbs="Администрирование"
        title="Проекты"
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden="true" />
            Новый проект
          </button>
        }
      />
      <section className="card">
        <div className="card-head">
          <div className="seg" role="group" aria-label="Статус проектов">
            {(
              [
                ["active", "Активные"],
                ["archived", "Архив"],
                ["", "Все"],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={status === v}
                onClick={() => {
                  setStatus(v);
                  setOffset(0);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {data && <span className="count">{data.total}</span>}
        </div>
        {error ? (
          <div className="card-pad">
            <ErrorAlert error={errorText(error)} onRetry={load} />
          </div>
        ) : !data ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <Empty
            icon={FolderKanban}
            title="Проектов нет"
            text="Проект — это договор на работы с заказчиком."
            action={
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                Новый проект
              </button>
            }
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Название</th>
                    <th>Заказчик</th>
                    <th>Договор</th>
                    <th>Период</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <tr key={p.id} className={`clickable${p.id === openId ? " selected" : ""}`} onClick={() => setOpenId(p.id)}>
                      <td>{p.name}</td>
                      <td>{p.client || <span className="muted">—</span>}</td>
                      <td>{p.contract_ref ? <span className="tag">{p.contract_ref}</span> : <span className="muted">—</span>}</td>
                      <td>
                        {formatDate(p.period_from)} — {formatDate(p.period_to)}
                      </td>
                      <td>
                        <span className={`pill ${PROJECT_STATUS[p.status].pill}`}>{PROJECT_STATUS[p.status].label}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </section>
      <ProjectModal open={creating} onClose={() => setCreating(false)} onSaved={changed} />
      {current && <ProjectDrawer key={current.id} project={current} onClose={() => setOpenId(null)} onChanged={changed} />}
    </>
  );
}

function ProjectForm({ draft, setDraft, id }: { draft: Draft; setDraft: (d: Draft) => void; id: string }) {
  const f = (k: keyof Draft) => ({ value: draft[k], onChange: (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value }) });
  return (
    <div className="form" id={id}>
      <label className="field">
        <span>Название</span>
        <input className="input" required {...f("name")} />
      </label>
      <label className="field">
        <span>Заказчик</span>
        <input className="input" {...f("client")} />
      </label>
      <label className="field">
        <span>Номер договора</span>
        <input className="input" {...f("contract_ref")} />
      </label>
      <div className="row-phi">
        <label className="field">
          <span>Начало работ</span>
          <input className="input" type="date" {...f("period_from")} />
        </label>
        <label className="field">
          <span>Окончание</span>
          <input className="input" type="date" {...f("period_to")} />
        </label>
      </div>
    </div>
  );
}

const toBody = (d: Draft) => ({ ...d, period_from: d.period_from || null, period_to: d.period_to || null });

function ProjectModal({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await send("POST", "/admin/projects", toBody(draft));
      setDraft(EMPTY);
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
      title="Новый проект"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" form="project-create" className="btn btn-primary">
            Создать
          </button>
        </>
      }
    >
      <form id="project-create" onSubmit={submit}>
        {error && <div className="alert-danger" role="alert"><div className="alert-body">{error}</div></div>}
        <ProjectForm draft={draft} setDraft={setDraft} id="project-create-fields" />
      </form>
    </Modal>
  );
}

function ProjectDrawer({ project, onClose, onChanged }: { project: Project; onClose: () => void; onChanged: () => void }) {
  const [draft, setDraft] = useState<Draft>({
    name: project.name,
    client: project.client,
    contract_ref: project.contract_ref,
    period_from: project.period_from ?? "",
    period_to: project.period_to ?? "",
  });
  const [members, setMembers] = useState<Member[] | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [message, setMessage] = useState<{ kind: "ok" | "danger"; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    get<Member[]>(`/admin/projects/${project.id}/members`).then(setMembers, () => setMembers([]));
    get<AdminUser[]>("/admin/users?limit=500&active=true").then(setUsers, () => setUsers([]));
  }, [project.id]);

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
  const isMember = (id: string) => members?.some((m) => m.user_id === id) ?? false;
  const toggle = (u: AdminUser) =>
    setMembers((m) =>
      (m ?? []).some((x) => x.user_id === u.id)
        ? (m ?? []).filter((x) => x.user_id !== u.id)
        : [...(m ?? []), { user_id: u.id, username: u.username, display_name: u.display_name, project_role: "member" }],
    );
  const archived = project.status === "archived";

  return (
    <Drawer open title={project.name} onClose={onClose}>
      {message && (
        <div className={`alert-${message.kind}`} role="status">
          <div className="alert-body">{message.text}</div>
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(() => send("PATCH", `/admin/projects/${project.id}`, toBody(draft)), "Проект сохранён.");
        }}
        className="form"
      >
        <ProjectForm draft={draft} setDraft={setDraft} id="project-edit-fields" />
        <div className="actions">
          <button type="submit" className="btn btn-primary">
            Сохранить
          </button>
        </div>
      </form>

      <h3>Участники</h3>
      {!members ? (
        <Loading />
      ) : (
        <div className="form">
          {users.map((u) => (
            <label key={u.id} className="checkbox">
              <input type="checkbox" checked={isMember(u.id)} onChange={() => toggle(u)} />
              {u.display_name} <span className="muted mono">{u.username}</span>
              {u.all_projects && <small>и так видит все проекты</small>}
            </label>
          ))}
          <div className="actions">
            <button
              type="button"
              className="btn"
              onClick={() =>
                run(
                  () => send("PUT", `/admin/projects/${project.id}/members`, members.map((m) => ({ user_id: m.user_id, project_role: m.project_role }))),
                  "Участники сохранены. Доступ изменится при следующем обновлении токена, не позже 15 минут.",
                )
              }
            >
              Сохранить участников
            </button>
          </div>
        </div>
      )}

      <h3>Архив</h3>
      {archived ? (
        <div className="actions">
          <button type="button" className="btn" onClick={() => run(() => send("POST", `/admin/projects/${project.id}/restore`), "Проект восстановлен.")}>
            Вернуть из архива
          </button>
        </div>
      ) : (
        <div className="actions">
          <button type="button" className="btn btn-danger" onClick={() => setConfirm(true)}>
            Отправить в архив
          </button>
        </div>
      )}
      <ConfirmDanger
        open={confirm}
        title="Отправить проект в архив?"
        confirmLabel="Отправить в архив"
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          run(() => send("POST", `/admin/projects/${project.id}/archive`), "Проект в архиве.");
        }}
      >
        <p>
          Проект «{project.name}» станет доступен только на чтение во всех продуктах: новые прогоны, заявки и документы по нему
          создать будет нельзя. Вернуть проект из архива можно в любой момент.
        </p>
      </ConfirmDanger>
    </Drawer>
  );
}
