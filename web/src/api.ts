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
  /** Пароль задал администратор: роли не действуют, пока пользователь не сменит его сам. */
  password_temporary: boolean;
}

export interface ServiceAccount {
  id: string;
  client_id: string;
  name: string;
  target_product: string;
  roles: string[];
  all_projects: boolean;
  projects: string[];
  is_active: boolean;
  created_at: string;
  secret_rotated_at: string;
  last_used_at: string | null;
}

export interface AuditEntry {
  id: number;
  time: string;
  product: string;
  product_title: string;
  actor_sub: string | null;
  actor_name: string;
  action: string;
  object: string;
  project_id: string | null;
  project_name: string | null;
  result: string;
  ip: string;
  details: Record<string, unknown>;
  event_id: string | null;
  /** Действие, которым администратор мог бы обойти разделение обязанностей (docs/SECURITY.md, п. 6). */
  sod: boolean;
}

export interface AuditFacets {
  products: { id: string; title: string }[];
  projects: { id: string; title: string }[];
  actions: string[];
}

export type DeliveryStatus = "ok" | "pending" | "failed" | "dead";

export interface BusEvent {
  id: string;
  type: string;
  source: string;
  time: string;
  received_at: string;
  project_id: string | null;
  subject: string;
  delivery: DeliveryStatus | "none";
  deliveries_total: number;
}

export interface BusDelivery {
  id: string;
  subscription_id: string;
  product_id: string;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  last_status_code: number | null;
  delivered_at: string | null;
}

export interface BusEventDetail extends BusEvent {
  data: Record<string, unknown>;
  notify: { users: string[]; title: string; link?: string | null } | null;
  deliveries: BusDelivery[];
}

export interface Subscription {
  id: string;
  product_id: string;
  webhook_path: string;
  types: string[];
  is_active: boolean;
  pending: number;
  dead: number;
}

export interface SigningKey {
  kid: string;
  status: "next" | "active" | "retired" | "revoked";
  alg: string;
  crv: string;
  created_at: string;
  activated_at: string | null;
  retired_at: string | null;
  in_jwks: boolean;
  until: string | null;
}

export interface SigningKeys {
  keys: SigningKey[];
  schedule: {
    rotation_days: number;
    next_lead_seconds: number;
    jwks_retain_seconds: number;
    access_ttl_seconds: number;
    next_rotation_at: string | null;
    scheduler_enabled: boolean;
  };
  warnings: string[];
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

export type Criticality = "low" | "medium" | "high" | "critical";

export interface AssetSource {
  product: string;
  external_id: string | null;
  seen_at: string | null;
}

export interface Asset {
  id: string;
  project_id: string;
  address: string;
  hostname: string;
  os_family: string;
  os: string;
  owner: string;
  criticality: Criticality | null;
  tags: string[];
  groups: string[];
  sources: AssetSource[];
  manual_fields: string[];
  created_at: string;
  updated_at: string;
}

export interface AssetFacets {
  tags: string[];
  groups: string[];
  sources: string[];
  os_families: string[];
}

export interface ImportReport {
  dry_run: boolean;
  rows: number;
  created: number;
  updated: number;
  unchanged: number;
  error_count: number;
  errors: { line: number; error: string }[];
}

export interface Team {
  id: string;
  name: string;
  description: string;
  members: string[];
  roles: Record<string, string[]>;
  projects: string[];
}
