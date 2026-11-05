/**
 * Клиент API с токеном платформы (контракт v1.1, п. 2.4):
 * Bearer из sessionStorage['platform.token'], при 401 — один общий тихий refresh на вкладку,
 * при неудаче — переход на /login?next=<текущий путь>.
 *
 * Оболочка ходит в API платформы с отдельным коротким токеном (aud=["platform"], п. 2.6): он живёт
 * только в памяти вкладки и берётся по refresh-cookie через POST /auth/platform-token.
 */
import { LOGOUT_KEY, local, TOKEN_KEY, safeGet, safeSet, session } from "./storage";

export const PLATFORM_API = "/api/platform";
export const TOKEN_EVENT = "platform:token";

export interface TokenClaims {
  sub: string;
  typ?: "user" | "service";
  preferred_username?: string;
  name?: string;
  aud?: string[] | string;
  products?: Record<string, string[]>;
  projects?: string[];
  platform_admin?: boolean;
  /** local — пароль платформы (можно сменить в оболочке); иначе внешний источник. */
  auth_source?: string;
  /**
   * Пароль задал администратор: в токене нет ролей, пока пользователь не сменит пароль сам
   * (контракт v1.1, п. 2.1; docs/SECURITY.md, п. 6). Оболочка показывает смену пароля.
   */
  password_change_required?: boolean;
  exp?: number;
  iat?: number;
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? (typeof detail === "string" ? detail : `Ошибка ${status}`));
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  return safeGet(session, TOKEN_KEY);
}

export function setToken(token: string | null): void {
  safeSet(session, TOKEN_KEY, token);
  if (token === null) clearPlatformToken();
  window.dispatchEvent(new CustomEvent(TOKEN_EVENT));
}

/** Токен истёк или истекает в ближайшие 5 с. */
export function isTokenExpired(claims: TokenClaims | null): boolean {
  return !claims?.exp || claims.exp * 1000 <= Date.now() + 5_000;
}

export function decodeClaims(token: string | null): TokenClaims | null {
  if (!token) return null;
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
    const bin = atob(b64);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes)) as TokenClaims;
  } catch {
    return null;
  }
}

let refreshing: Promise<string | null> | null = null;

/** Одна попытка обновления на вкладку: параллельные 401 ждут общий результат. */
export function refreshOnce(apiBase: string = PLATFORM_API): Promise<string | null> {
  if (!refreshing) {
    refreshing = fetch(`${apiBase}/auth/refresh`, { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) return null;
        const body = (await r.json()) as { access_token?: string };
        return body.access_token ?? null;
      })
      .catch(() => null)
      .then((token) => {
        setToken(token);
        return token;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

// --- Токен оболочки для API платформы (контракт v1.1, п. 2.6) ---

let platformToken: string | null = null;
let platformRequest: Promise<string | null> | null = null;

/** Забыть токен оболочки (выход, неудачный refresh). */
export function clearPlatformToken(): void {
  platformToken = null;
}

/**
 * Новый токен оболочки (aud=["platform"]) по refresh-cookie; одна попытка на вкладку.
 * Не попадает ни в sessionStorage, ни в запросы к продуктам: бэкенд продукта не получает токен,
 * которым можно вызвать администрирование платформы (docs/SECURITY.md, п. 11).
 */
export function platformTokenOnce(apiBase: string = PLATFORM_API): Promise<string | null> {
  if (!platformRequest) {
    platformRequest = fetch(`${apiBase}/auth/platform-token`, { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) return null;
        const body = (await r.json()) as { access_token?: string };
        return body.access_token ?? null;
      })
      .catch(() => null)
      .then((token) => {
        platformToken = token;
        return token;
      })
      .finally(() => {
        platformRequest = null;
      });
  }
  return platformRequest;
}

async function currentPlatformToken(): Promise<string | null> {
  if (platformToken && !isTokenExpired(decodeClaims(platformToken))) return platformToken;
  return platformTokenOnce();
}

/** Адрес API платформы, кроме /auth/* (вход, refresh и выдача токенов — без Bearer). */
export function isPlatformApiUrl(url: string): boolean {
  return url.startsWith(`${PLATFORM_API}/`) && !url.startsWith(`${PLATFORM_API}/auth/`);
}

/**
 * Путь от корня этого origin. Браузер выбрасывает из URL табуляцию и переводы строк, а «\\» считает «/»,
 * поэтому «/\\t/evil.example» ведёт на чужой сайт: такие символы не допускаются вовсе
 * (docs/SECURITY.md, п. 9; та же проверка в API — app/security/links.py).
 */
export function isSafePath(path: unknown): path is string {
  // eslint-disable-next-line no-control-regex
  return typeof path === "string" && path.startsWith("/") && !path.startsWith("//") && !/[\u0000-\u0020\u007f\\]/.test(path);
}

/** Безопасный путь возврата после входа: только путь того же origin. */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (!isSafePath(next) || next.startsWith("/login")) return fallback;
  return next;
}

export function loginUrl(): string {
  const { pathname, search, hash } = window.location;
  return `/login?next=${encodeURIComponent(pathname + search + hash)}`;
}

export function redirectToLogin(): void {
  window.location.assign(loginUrl());
}

async function parse(r: Response): Promise<unknown> {
  if (r.status === 204) return null;
  const type = r.headers.get("content-type") ?? "";
  return type.includes("json") ? r.json() : r.text();
}

export interface FetchOptions extends RequestInit {
  /** Не переходить на страницу входа при неудачном refresh (страница входа, фоновые опросы). */
  noRedirect?: boolean;
  json?: unknown;
  /** Токен оболочки (aud=["platform"]) вместо sessionStorage — только для запросов оболочки к API платформы. */
  platform?: boolean;
}

/** fetch с токеном платформы. Возвращает Response (для заголовков вроде X-Total-Count). */
export async function apiFetch(url: string, options: FetchOptions = {}): Promise<Response> {
  const { noRedirect, json, platform, ...init } = options;
  const build = (token: string | null): RequestInit => {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (json !== undefined) headers.set("Content-Type", "application/json");
    return { credentials: "same-origin", ...init, headers, body: json !== undefined ? JSON.stringify(json) : init.body };
  };
  let r = await fetch(url, build(platform ? await currentPlatformToken() : getToken()));
  if (r.status === 401) {
    const token = platform ? await platformTokenOnce() : await refreshOnce();
    if (token) r = await fetch(url, build(token));
    if (r.status === 401 && !noRedirect) redirectToLogin();
  }
  return r;
}

/** apiFetch + разбор JSON; ошибка HTTP — ApiError с detail из ответа. */
export async function apiJson<T>(url: string, options: FetchOptions = {}): Promise<T> {
  const r = await apiFetch(url, options);
  const body = await parse(r);
  if (!r.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : body;
    throw new ApiError(r.status, detail);
  }
  return body as T;
}

export async function logout(apiBase: string = PLATFORM_API): Promise<void> {
  try {
    await fetch(`${apiBase}/auth/logout`, { method: "POST", credentials: "same-origin" });
  } finally {
    setToken(null); // и токен оболочки

    // Остальные вкладки этого браузера (оболочка и продукты) уходят на вход: см. onLogoutElsewhere.
    safeSet(local, LOGOUT_KEY, String(Date.now()));
    window.location.assign("/login");
  }
}

/**
 * Выход в другой вкладке (контракт v1.1, п. 2.4, 11): refresh-cookie уже отозвана,
 * но access-токен этой вкладки ещё жив — очищаем его и уходим на вход. Возвращает отписку.
 */
export function onLogoutElsewhere(handler: () => void = redirectToLogin): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === LOGOUT_KEY && e.newValue) {
      setToken(null); // и токен оболочки
      handler();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}
