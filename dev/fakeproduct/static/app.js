// Крошечный «фронтенд продукта» для e2e. Ведёт себя по контракту v1.1:
// токен в sessionStorage['platform.token'], при 401 — один refresh по cookie, при неудаче — /login?next=;
// проект — ?project= или localStorage['platform.project']; выход — POST /auth/logout и сигнал другим вкладкам.
const TOKEN_KEY = "platform.token";
const PROJECT_KEY = "platform.project";
const LOGOUT_KEY = "platform.logout";
const PLATFORM_API = "/api/platform";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const product = document.documentElement.dataset.product;
const API = `/api/${product}`;
const $ = (id) => document.querySelector(`[data-testid="${id}"]`);

function claims(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const bytes = Uint8Array.from(atob(part.padEnd(Math.ceil(part.length / 4) * 4, "=")), (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
}

function toLogin() {
  const { pathname, search, hash } = window.location;
  window.location.assign(`/login?next=${encodeURIComponent(pathname + search + hash)}`);
}

let refreshing = null;
function refreshOnce() {
  refreshing ??= fetch(`${PLATFORM_API}/auth/refresh`, { method: "POST", credentials: "same-origin" })
    .then(async (r) => (r.ok ? (await r.json()).access_token ?? null : null))
    .catch(() => null)
    .then((t) => {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
      return t;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function api(url) {
  const call = (t) => fetch(url, { credentials: "same-origin", headers: t ? { Authorization: `Bearer ${t}` } : {} });
  let r = await call(sessionStorage.getItem(TOKEN_KEY));
  if (r.status === 401) {
    const t = await refreshOnce();
    if (!t) {
      toLogin();
      throw new Error("unauthorized");
    }
    r = await call(t);
  }
  return r;
}

function currentProject() {
  const fromUrl = new URLSearchParams(window.location.search).get("project");
  const id = fromUrl && UUID_RE.test(fromUrl) ? fromUrl : localStorage.getItem(PROJECT_KEY);
  if (!id || !UUID_RE.test(id)) return null;
  if (localStorage.getItem(PROJECT_KEY) !== id) localStorage.setItem(PROJECT_KEY, id);
  if (fromUrl !== id) {
    const url = new URL(window.location.href);
    url.searchParams.set("project", id);
    window.history.replaceState(null, "", url);
  }
  return id;
}

function withProject(href, project) {
  return project ? `${href}${href.includes("?") ? "&" : "?"}project=${project}` : href;
}

async function logout() {
  try {
    await fetch(`${PLATFORM_API}/auth/logout`, { method: "POST", credentials: "same-origin" });
  } finally {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.setItem(LOGOUT_KEY, String(Date.now()));
    window.location.assign("/login");
  }
}

// Выход в другой вкладке — эта вкладка тоже уходит на вход.
window.addEventListener("storage", (e) => {
  if (e.key === LOGOUT_KEY && e.newValue) {
    sessionStorage.removeItem(TOKEN_KEY);
    toLogin();
  }
});

async function main() {
  $("logout").addEventListener("click", logout);

  const token = sessionStorage.getItem(TOKEN_KEY);
  const c = token ? claims(token) : null;
  if (!c || !c.exp || c.exp * 1000 <= Date.now() + 5000) {
    if (!(await refreshOnce())) return toLogin();
  }

  const project = currentProject();
  $("project").textContent = project ?? "не выбран";

  const nav = document.querySelector("nav.tabs");
  const home = nav.querySelector('[data-tab="home"]');
  home.href = withProject("/", project);
  const products = await api(`${PLATFORM_API}/products`).then((r) => (r.ok ? r.json() : []));
  for (const p of products) {
    const a = document.createElement("a");
    a.href = withProject(p.base_path, project);
    a.textContent = p.title;
    a.dataset.product = p.id;
    if (p.id === product) a.setAttribute("aria-current", "page");
    nav.append(a);
  }

  const me = await api(`${API}/me`);
  $("user").textContent = me.ok ? (await me.json()).username : `ошибка ${me.status}`;

  if (project) {
    const s = await api(`${API}/summary?project=${project}`);
    $("summary").textContent = s.ok ? `ok: ${(await s.json()).project_id}` : `ошибка ${s.status}`;
  } else {
    $("summary").textContent = "—";
  }
  document.body.dataset.ready = "1";
}

main().catch((e) => {
  if (e.message !== "unauthorized") $("summary").textContent = `ошибка: ${e.message}`;
});
