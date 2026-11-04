import "../src/styles.css";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FolderKanban,
  Info,
  LayoutDashboard,
  Play,
  Plus,
  Radar,
  Server,
  Settings,
  ShieldAlert,
  Users,
} from "lucide-react";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import {
  applyTheme,
  ConfirmDanger,
  Drawer,
  Empty,
  ErrorAlert,
  formatDateTime,
  formatNumber,
  Kpi,
  Layout,
  Loading,
  Modal,
  PageHead,
  Pager,
  ProductTabs,
  ProjectPicker,
  QuickSearch,
  SEVERITIES,
  SeverityBadge,
  SeverityBar,
  UserMenu,
} from "../src";

// ?theme=light|dark — для скриншотов.
const forced = new URLSearchParams(window.location.search).get("theme");
if (forced === "light" || forced === "dark") {
  window.localStorage.setItem("platform.theme", forced);
  applyTheme(forced);
}

const PROJECTS = [
  { id: "11111111-1111-4111-8111-111111111111", name: "Пентест ООО «Ромашка», Д-17/2026" },
  { id: "22222222-2222-4222-8222-222222222222", name: "Аттестация ГИС «Учёт обращений»" },
  { id: "33333333-3333-4333-8333-333333333333", name: "Аудит 2025", status: "archived" },
];

const ROWS = [
  { id: 1, title: "OpenSSH regreSSHion", host: "10.0.0.5:22", sev: "critical", tag: "CVE-2024-6387", st: "pill-danger", stl: "Новая" },
  { id: 2, title: "Устаревшая версия nginx", host: "10.0.0.7:443", sev: "high", tag: "BDU:2024-04835", st: "pill-warn", stl: "Регрессия" },
  { id: 3, title: "Слабые шифры TLS", host: "10.0.0.9:443", sev: "medium", tag: "CWE-327", st: "pill-info", stl: "Открыта" },
  { id: 4, title: "Баннер сервиса раскрывает версию", host: "10.0.0.9:25", sev: "low", tag: "УПД.3", st: "pill-ok", stl: "Исправлена" },
  { id: 5, title: "Открытый порт SNMP", host: "10.0.0.12:161", sev: "info", tag: "CVE-2002-0013", st: "pill-muted", stl: "Ложное" },
] as const;

const COUNTS = { critical: 3, high: 12, medium: 37, low: 54, info: 118 };

function Showcase() {
  const [project, setProject] = useState<string | null>(PROJECTS[0].id);
  const [modal, setModal] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [seg, setSeg] = useState("full");
  const [tab, setTab] = useState("findings");
  const [chips, setChips] = useState<string[]>(["critical", "high"]);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(2);

  return (
    <Layout
      platform
      tabs={
        <ProductTabs
          active="scanner"
          projectId={project}
          products={[
            { id: "scanner", title: "Сканер", icon: "radar", base_path: "#/" },
            { id: "vm", title: "Устранение", icon: "wrench", base_path: "#/" },
            { id: "grc", title: "Аттестация", icon: "shield-check", base_path: "#/" },
          ]}
          right={
            <>
              <button type="button" className="icon-btn" aria-label="Уведомления">
                <Activity size={18} aria-hidden="true" />
                <span className="dot" aria-hidden="true" />
              </button>
              <UserMenu name="Иванов И. И." subtitle="ivanov" onLogout={() => undefined} />
            </>
          }
        />
      }
      brand={{ title: "Сканер", subtitle: "уязвимости и соответствие", icon: Radar }}
      nav={[
        { to: "/", label: "Сводка", icon: LayoutDashboard, end: true },
        { to: "/runs", label: "Прогоны", icon: Play },
        { to: "/assets", label: "Активы", icon: Server },
      ]}
      adminNav={[
        { to: "/users", label: "Пользователи", icon: Users },
        { to: "/projects", label: "Проекты", icon: FolderKanban },
        { to: "/settings", label: "Настройки", icon: Settings },
      ]}
      user={{ name: "Иванов Иван Иванович", roles: ["Оператор", "Аудитор"] }}
      onLogout={() => undefined}
      topbar={
        <>
          <ProjectPicker projects={PROJECTS} value={project} onChange={setProject} />
          <QuickSearch
            commands={[
              { id: "scanner", label: "Перейти в Сканер", href: "#/" },
              { id: "vm", label: "Перейти в Устранение", href: "#/" },
            ]}
            sources={[
              {
                id: "scanner",
                title: "Сканер",
                search: async (q) => ROWS.filter((r) => r.title.toLowerCase().includes(q.toLowerCase())).map((r) => ({
                  title: r.title,
                  subtitle: r.host,
                  link: "#/",
                  severity: r.sev,
                })),
              },
            ]}
          />
          <span className="task-indicator">
            <span className="spinner" style={{ width: 14, height: 14 }} aria-hidden="true" />
            Прогон: 42 %
          </span>
        </>
      }
      topbarNote="Работы только по согласованному списку целей"
    >
      <PageHead
        breadcrumbs="Витрина / @platform/ui"
        title="Компоненты"
        actions={
          <>
            <button type="button" className="btn">
              Выгрузить
            </button>
            <button type="button" className="btn btn-primary">
              <Plus size={15} aria-hidden="true" />
              Новый прогон
            </button>
          </>
        }
      />

      <div className="row-phi">
        <section className="card">
          <div className="card-head">
            <h2>Открытые уязвимости</h2>
            <span className="pill pill-running">Идёт прогон</span>
          </div>
          <div className="card-pad hero">
            <div style={{ display: "flex", alignItems: "baseline", gap: 13 }}>
              <span className="hero-number">{formatNumber(224)}</span>
              <span className="pill pill-ok">−18 к прошлому прогону</span>
            </div>
            <SeverityBar counts={COUNTS} />
            <div className="legend">
              {SEVERITIES.map((s) => (
                <span key={s} style={{ display: "inline-flex", gap: 6 }}>
                  <SeverityBadge level={s} /> <span className="muted">{formatNumber(COUNTS[s])}</span>
                </span>
              ))}
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-head">
            <h2>Последний прогон</h2>
          </div>
          <div className="card-pad">
            <dl className="stat-list">
              <div>
                <dt>Статус</dt>
                <dd>
                  <span className="pill pill-warn">Частично</span>
                </dd>
              </div>
              <div>
                <dt>Завершён</dt>
                <dd>{formatDateTime("2026-11-04T13:54:00Z")}</dd>
              </div>
              <div>
                <dt>Хостов</dt>
                <dd>{formatNumber(1284)}</dd>
              </div>
            </dl>
          </div>
        </section>
      </div>

      <div className="kpi-row">
        <Kpi label="Критические" value="3" delta="−2 за неделю" trend="good" />
        <Kpi label="Высокие" value="12" delta="+4 за неделю" trend="bad" />
        <Kpi label="Выполнение мер" value="78 %" delta="без изменений" />
        <Kpi label="Заявок в работе" value={formatNumber(1234)} />
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Находки</h2>
          <div className="actions">
            <div className="seg" role="group" aria-label="Вид отчёта">
              <button type="button" aria-pressed={seg === "full"} onClick={() => setSeg("full")}>
                Полный
              </button>
              <button type="button" aria-pressed={seg === "brief"} onClick={() => setSeg("brief")}>
                Краткий
              </button>
            </div>
          </div>
        </div>
        <div className="tabs" role="tablist" style={{ padding: "0 21px" }}>
          {[
            ["findings", "Находки", 224],
            ["fixes", "Что исправить", 31],
            ["coverage", "Покрытие", 0],
          ].map(([id, label, n]) => (
            <button key={id} type="button" role="tab" className="tab" aria-selected={tab === id} onClick={() => setTab(String(id))}>
              {label} {Number(n) > 0 && <span className="count">{n}</span>}
            </button>
          ))}
        </div>
        <div className="card-pad" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {SEVERITIES.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              aria-pressed={chips.includes(s)}
              onClick={() => setChips((c) => (c.includes(s) ? c.filter((x) => x !== s) : [...c, s]))}
            >
              <SeverityBadge level={s} />
            </button>
          ))}
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th className="sortable">Уровень</th>
                <th>Находка</th>
                <th>Хост</th>
                <th>Идентификатор</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => (
                <tr key={r.id} className={`clickable${selected === r.id ? " selected" : ""}`} onClick={() => { setSelected(r.id); setDrawer(true); }}>
                  <td>
                    <SeverityBadge level={r.sev} />
                  </td>
                  <td>{r.title}</td>
                  <td className="mono">{r.host}</td>
                  <td>
                    <span className="tag">{r.tag}</span>
                  </td>
                  <td>
                    <span className={`pill ${r.st}`}>{r.stl}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager total={224} limit={50} offset={offset} onChange={setOffset} />
      </section>

      <div className="row-phi-rev">
        <section className="card">
          <div className="card-head">
            <h2>Форма</h2>
          </div>
          <div className="card-pad form">
            <label className="field">
              <span>Название прогона</span>
              <input className="input" placeholder="Ежемесячный прогон" />
              <small>Видно в отчётах и журнале</small>
            </label>
            <label className="field">
              <span>Профиль скорости</span>
              <select className="select" defaultValue="normal">
                <option value="gentle">Щадящий</option>
                <option value="normal">Обычный</option>
                <option value="fast">Быстрый</option>
              </select>
            </label>
            <label className="field">
              <span>Цели</span>
              <textarea className="textarea" placeholder="10.0.0.0/24" />
            </label>
            <label className="checkbox">
              <input type="checkbox" defaultChecked /> Аудит конфигураций
            </label>
            <div className="actions">
              <button type="button" className="btn btn-sm">
                Маленькая
              </button>
              <button type="button" className="btn btn-ghost">
                Прозрачная
              </button>
              <button type="button" className="btn btn-danger" onClick={() => setConfirm(true)}>
                Удалить
              </button>
              <button type="button" className="btn" onClick={() => setModal(true)}>
                Модальное окно
              </button>
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-head">
            <h2>Пояснения и состояния</h2>
          </div>
          <div className="card-pad form">
            <div className="alert-info">
              <Info size={18} aria-hidden="true" />
              <div className="alert-body">Отсутствие находки считается исправлением, только если хост проверен полностью.</div>
            </div>
            <div className="alert-warn">
              <AlertTriangle size={18} aria-hidden="true" />
              <div className="alert-body">Две цели вне списка разрешённых отклонены.</div>
            </div>
            <div className="alert-ok">
              <CheckCircle2 size={18} aria-hidden="true" />
              <div className="alert-body">Прогон завершён.</div>
            </div>
            <ErrorAlert error="Сервер «Устранения» не ответил" onRetry={() => undefined} />
            <Loading />
          </div>
        </section>
      </div>

      <section className="card">
        <Empty
          icon={ShieldAlert}
          title="Прогонов ещё не было"
          text="Запустите первый прогон по согласованному списку целей."
          action={
            <button type="button" className="btn btn-primary">
              Новый прогон
            </button>
          }
        />
      </section>

      <Modal
        open={modal}
        title="Новый прогон"
        onClose={() => setModal(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setModal(false)}>
              Отмена
            </button>
            <button type="button" className="btn btn-primary" onClick={() => setModal(false)}>
              Запустить
            </button>
          </>
        }
      >
        <label className="field">
          <span>Название</span>
          <input className="input" />
        </label>
      </Modal>
      <ConfirmDanger
        open={confirm}
        title="Удалить проект?"
        confirmLabel="Удалить проект"
        onConfirm={() => setConfirm(false)}
        onClose={() => setConfirm(false)}
      >
        <p>Проект и все прогоны будут удалены без возможности восстановления. Журнал аудита сохранится.</p>
      </ConfirmDanger>
      <Drawer open={drawer} title="Находка" onClose={() => setDrawer(false)}>
        <p>Карточка записи открывается без ухода со страницы.</p>
        <span className="tag">CVE-2024-6387</span>
      </Drawer>
    </Layout>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HashRouter>
      <Showcase />
    </HashRouter>
  </StrictMode>,
);
