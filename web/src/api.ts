/** Типы и вызовы API платформы (через шлюз: /api/platform). */
import { apiFetch, apiJson, PLATFORM_API } from "@platform/ui";

export const API = PLATFORM_API;

export interface Manifest {
  id: string;
  title: string;
  subtitle?: string;
  icon?: string;
  base_path: string;
  api_base?: string;
  version?: string;
  roles?: Record<string, string>;
  admin_roles?: string[];
  search_url?: string;
  summary_url?: string;
  health_url?: string;
}

export interface MyProduct extends Manifest {
  health: "ok" | "down" | "unknown";
  my_roles: string[];
}

export interface AdminProduct extends Manifest {
  health: "ok" | "down" | "unknown";
  manifest: Manifest;
  internal_url: string;
  enabled: boolean;
  version: string;
  health_checked_at: string | null;
  manifest_fetched_at: string | null;
  manifest_source: "product" | "default";
  last_error: string | null;
}

export interface Project {
  id: string;
  name: string;
  client: string;
  contract_ref: string;
  period_from: string | null;
  period_to: string | null;
  status: "active" | "archived";
  created_at: string;
  archived_at: string | null;
}

export interface AdminUser {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  is_active: boolean;
  locked: boolean;
  auth_source: string;
  is_platform_admin: boolean;
  all_projects: boolean;
  last_login_at: string | null;
  created_at: string;
  roles: Record<string, string[]>;
  own_roles: Record<string, string[]>;
  projects: { project_id: string; project_role: string; name: string }[];
  groups: string[];
}

export interface Member {
  user_id: string;
  username: string;
  display_name: string;
  project_role: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
}

export async function paged<T>(url: string): Promise<Paged<T>> {
  const r = await apiFetch(url);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Ошибка ${r.status}`);
  }
  return { items: (await r.json()) as T[], total: Number(r.headers.get("X-Total-Count") ?? 0) };
}

export const get = <T,>(path: string) => apiJson<T>(`${API}${path}`);
export const send = <T,>(method: string, path: string, json?: unknown) =>
  apiJson<T>(`${API}${path}`, { method, json });

/** Текст ошибки API для человека: detail строкой или первая ошибка валидации. */
export function errorText(e: unknown): string {
  if (e && typeof e === "object" && "detail" in e) {
    const d = (e as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg);
  }
  return e instanceof Error ? e.message : "Неизвестная ошибка";
}
