import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  apiFetch,
  apiJson,
  decodeClaims,
  type FetchOptions,
  getToken,
  logout as doLogout,
  onLogoutElsewhere,
  redirectToLogin,
  refreshOnce,
  TOKEN_EVENT,
  type TokenClaims,
} from "../lib/api";

export interface AuthUser {
  id: string;
  username: string;
  name: string;
}

export interface AuthState {
  /** Токен проверен или обновлён; до этого компоненты показывают Loading. */
  ready: boolean;
  token: string | null;
  claims: TokenClaims | null;
  user: AuthUser | null;
  /** Роли текущего продукта (или всех продуктов, если product не задан). */
  roles: string[];
  products: Record<string, string[]>;
  projects: string[];
  isPlatformAdmin: boolean;
  /** Есть ли право: роль → права из permissions; без таблицы прав — совпадение с ролью. */
  has: (perm: string) => boolean;
  hasProduct: (productId: string) => boolean;
  canProject: (projectId: string | null | undefined) => boolean;
  fetch: (url: string, options?: FetchOptions) => Promise<Response>;
  json: <T>(url: string, options?: FetchOptions) => Promise<T>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export interface AuthProviderProps {
  children: ReactNode;
  /** Id продукта (scanner, vm, grc); для оболочки платформы — не задаётся. */
  product?: string;
  /** Таблица «роль → права» продукта, для has(perm). */
  permissions?: Record<string, string[]>;
  /** false — не уводить на страницу входа (сама страница входа). */
  requireAuth?: boolean;
}

function isExpired(claims: TokenClaims | null): boolean {
  return !claims?.exp || claims.exp * 1000 <= Date.now() + 5_000;
}

export function AuthProvider({ children, product, permissions, requireAuth = true }: AuthProviderProps) {
  const [token, setTokenState] = useState<string | null>(getToken);
  const [ready, setReady] = useState<boolean>(() => !isExpired(decodeClaims(getToken())));

  useEffect(() => {
    const onToken = () => setTokenState(getToken());
    window.addEventListener(TOKEN_EVENT, onToken);
    return () => window.removeEventListener(TOKEN_EVENT, onToken);
  }, []);

  // Выход в другой вкладке — эта тоже уходит на вход.
  useEffect(() => (requireAuth ? onLogoutElsewhere() : undefined), [requireAuth]);

  // Нет токена или он истёк — тихий refresh по cookie, иначе вход.
  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    refreshOnce().then((t) => {
      if (cancelled) return;
      if (!t && requireAuth) redirectToLogin();
      else setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [ready, requireAuth]);

  const claims = useMemo(() => decodeClaims(token), [token]);
  const products = useMemo(() => claims?.products ?? {}, [claims]);
  const roles = useMemo(
    () => (product ? (products[product] ?? []) : Array.from(new Set(Object.values(products).flat()))),
    [product, products],
  );

  const has = useCallback(
    (perm: string) =>
      roles.some((role) => role === perm || (permissions?.[role] ?? []).includes(perm)),
    [roles, permissions],
  );

  const value = useMemo<AuthState>(
    () => ({
      ready,
      token,
      claims,
      user: claims
        ? { id: claims.sub, username: claims.preferred_username ?? "", name: claims.name ?? claims.preferred_username ?? "" }
        : null,
      roles,
      products,
      projects: claims?.projects ?? [],
      isPlatformAdmin: Boolean(claims?.platform_admin),
      has,
      hasProduct: (id: string) => (products[id] ?? []).length > 0,
      canProject: (id) => Boolean(id) && ((claims?.projects ?? []).includes("*") || (claims?.projects ?? []).includes(id!)),
      fetch: apiFetch,
      json: apiJson,
      logout: () => doLogout(),
    }),
    [ready, token, claims, roles, products, has],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() вызван вне <AuthProvider>");
  return ctx;
}
