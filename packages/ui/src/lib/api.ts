/**
 * Клиент API с токеном платформы (контракт v1.1, п. 2.4):
 * Bearer из sessionStorage['platform.token'], при 401 — один общий тихий refresh на вкладку,
 * при неудаче — переход на /login?next=<текущий путь>.
 */
import { TOKEN_KEY, safeGet, safeSet, session } from "./storage";

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
  window.dispatchEvent(new CustomEvent(TOKEN_EVENT));
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

/** Безопасный путь возврата после входа: только относительный путь того же origin. */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (next.startsWith("/login")) return fallback;
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
}

/** fetch с токеном платформы. Возвращает Response (для заголовков вроде X-Total-Count). */
export async function apiFetch(url: string, options: FetchOptions = {}): Promise<Response> {
  const { noRedirect, json, ...init } = options;
  const build = (token: string | null): RequestInit => {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (json !== undefined) headers.set("Content-Type", "application/json");
    return { credentials: "same-origin", ...init, headers, body: json !== undefined ? JSON.stringify(json) : init.body };
  };
  let r = await fetch(url, build(getToken()));
  if (r.status === 401) {
    const token = await refreshOnce();
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
    setToken(null);
    window.location.assign("/login");
  }
}
